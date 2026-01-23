interface CacheEntry<T> {
  data: T;
  timestamp: number;
  size?: number;
}

interface CacheOptions {
  ttl?: number; // Time to live in milliseconds
  maxSize?: number; // Maximum size in bytes
  compress?: boolean; // Whether to compress data
}

const DEFAULT_TTL = 5 * 60 * 1000; // 5 minutes
const MAX_STORAGE_SIZE = 10 * 1024 * 1024; // 10MB - Increased from 2MB to prevent constant evictions
const STORAGE_USAGE_KEY = '__storage_usage__';

export class SafeStorage {
  private static instance: SafeStorage;
  private storageUsage: number = 0;

  private constructor() {
    this.calculateStorageUsage();
  }

  static getInstance(): SafeStorage {
    if (!SafeStorage.instance) {
      SafeStorage.instance = new SafeStorage();
    }
    return SafeStorage.instance;
  }

  private calculateStorageUsage(): void {
    try {
      let totalSize = 0;
      for (const key in localStorage) {
        if (Object.prototype.hasOwnProperty.call(localStorage, key)) {
          const item = localStorage.getItem(key);
          if (item) {
            totalSize += key.length + item.length;
          }
        }
      }
      this.storageUsage = totalSize * 2; // UTF-16 uses 2 bytes per character
    } catch (error) {
      console.warn('Failed to calculate storage usage:', error);
      this.storageUsage = 0;
    }
  }

  private getItemSize(key: string, value: string): number {
    return (key.length + value.length) * 2; // UTF-16
  }

  private evictOldestItems(requiredSpace: number): void {
    const items: { key: string; timestamp: number }[] = [];

    // Collect all cache items with timestamps
    for (const key in localStorage) {
      if (key.startsWith('cache_') && key !== STORAGE_USAGE_KEY) {
        try {
          const item = localStorage.getItem(key);
          if (item) {
            const parsed = JSON.parse(item);
            if (parsed.timestamp) {
              items.push({ key, timestamp: parsed.timestamp });
            }
          }
        } catch {
          // Remove invalid items
          localStorage.removeItem(key);
        }
      }
    }

    // Sort by timestamp (oldest first)
    items.sort((a, b) => a.timestamp - b.timestamp);

    // Evict oldest items until we have enough space
    let freedSpace = 0;
    for (const item of items) {
      if (freedSpace >= requiredSpace) break;

      const value = localStorage.getItem(item.key);
      if (value) {
        freedSpace += this.getItemSize(item.key, value);
        localStorage.removeItem(item.key);
      }
    }

    this.calculateStorageUsage();
  }

  set<T>(key: string, data: T, options: CacheOptions = {}): boolean {
    const cacheKey = `cache_${key}`;
    const ttl = options.ttl ?? DEFAULT_TTL;

    try {
      const entry: CacheEntry<T> = {
        data,
        timestamp: Date.now() + ttl,
      };

      const serialized = JSON.stringify(entry);
      const itemSize = this.getItemSize(cacheKey, serialized);

      // Check if item is too large
      if (itemSize > MAX_STORAGE_SIZE) {
        console.warn(`[Cache] Item ${key} is too large (${itemSize} bytes), not caching`);
        return false;
      }

      // Check if we need to evict items
      if (this.storageUsage + itemSize > MAX_STORAGE_SIZE) {
        this.evictOldestItems(itemSize);
      }

      // Try to set the item
      try {
        localStorage.setItem(cacheKey, serialized);
        this.storageUsage += itemSize;
        return true;
      } catch (error) {
        // QuotaExceededError - clear some space and retry
        if (error instanceof DOMException && error.name === 'QuotaExceededError') {
          console.warn('[Cache] QuotaExceededError, clearing old cache...');
          this.clearExpired();
          this.evictOldestItems(itemSize);

          // Try one more time
          try {
            localStorage.setItem(cacheKey, serialized);
            this.storageUsage += itemSize;
            return true;
          } catch {
            console.error(`[Cache] Failed to store ${key} after clearing`);
            return false;
          }
        }
        throw error;
      }
    } catch (error) {
      console.error(`[Cache] Failed to set ${key}:`, error);
      return false;
    }
  }

  get<T>(key: string, options?: { ignoreExpiry?: boolean }): T | null {
    const cacheKey = `cache_${key}`;

    try {
      const item = localStorage.getItem(cacheKey);
      if (!item) return null;

      const entry: CacheEntry<T> = JSON.parse(item);

      // Check if expired (unless ignoreExpiry is set for stale-while-revalidate)
      if (!options?.ignoreExpiry && Date.now() > entry.timestamp) {
        localStorage.removeItem(cacheKey);
        this.calculateStorageUsage();
        return null;
      }

      return entry.data;
    } catch (error) {
      console.error(`[Cache] Failed to get ${key}:`, error);
      // Remove corrupted item
      localStorage.removeItem(cacheKey);
      this.calculateStorageUsage();
      return null;
    }
  }

  remove(key: string): void {
    const cacheKey = `cache_${key}`;
    localStorage.removeItem(cacheKey);
    this.calculateStorageUsage();
  }

  clearExpired(): void {
    const now = Date.now();
    const keysToRemove: string[] = [];

    for (const key in localStorage) {
      if (key.startsWith('cache_') && key !== STORAGE_USAGE_KEY) {
        try {
          const item = localStorage.getItem(key);
          if (item) {
            const entry = JSON.parse(item);
            if (entry.timestamp && now > entry.timestamp) {
              keysToRemove.push(key);
            }
          }
        } catch {
          // Remove corrupted items
          keysToRemove.push(key);
        }
      }
    }

    for (const key of keysToRemove) {
      localStorage.removeItem(key);
    }

    if (keysToRemove.length > 0) {
      this.calculateStorageUsage();
    }
  }

  clearAll(): void {
    const keysToRemove: string[] = [];

    for (const key in localStorage) {
      if (key.startsWith('cache_')) {
        keysToRemove.push(key);
      }
    }

    for (const key of keysToRemove) {
      localStorage.removeItem(key);
    }

    this.storageUsage = 0;
  }

  getUsageInfo(): { used: number; max: number; percentage: number } {
    return {
      used: this.storageUsage,
      max: MAX_STORAGE_SIZE,
      percentage: (this.storageUsage / MAX_STORAGE_SIZE) * 100
    };
  }
}

export const storage = SafeStorage.getInstance();

// Clean up expired items periodically
if (typeof window !== 'undefined') {
  setInterval(() => {
    storage.clearExpired();
  }, 60000); // Every minute
}
