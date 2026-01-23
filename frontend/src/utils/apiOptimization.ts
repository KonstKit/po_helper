/**
 * API Optimization Utilities
 *
 * Provides:
 * 1. Request deduplication - prevents duplicate concurrent requests
 * 2. Debouncing - delays execution for search/filter inputs
 * 3. Request batching - combines multiple requests into one
 * 4. Parallel loading - load multiple resources concurrently
 * 5. Caching layer - in-memory cache with TTL
 */

// =============================================================================
// Request Deduplication
// =============================================================================

import type {
  BudgetHoursResponse,
  DoraMetrics,
  RisksResponse,
  TeamHealthMetrics,
  ValueMetricsResponse,
  VelocityResponse,
} from '../services/api';

type PendingRequest<T> = Promise<T>;

const pendingRequests = new Map<string, PendingRequest<unknown>>();

/**
 * Deduplicate concurrent identical requests.
 *
 * If a request with the same key is already in-flight, returns the existing promise.
 * This prevents N+1 fetch calls in React StrictMode or when multiple components
 * request the same data simultaneously.
 *
 * @example
 * // These will only make ONE API call:
 * const p1 = deduplicateRequest('project-123', () => fetchProject(123));
 * const p2 = deduplicateRequest('project-123', () => fetchProject(123));
 * const [r1, r2] = await Promise.all([p1, p2]);
 */
export async function deduplicateRequest<T>(
  key: string,
  requestFn: () => Promise<T>
): Promise<T> {
  // Check if request is already in-flight
  const pending = pendingRequests.get(key);
  if (pending) {
    console.debug(`[API] Reusing in-flight request: ${key}`);
    return pending as Promise<T>;
  }

  // Create new request and track it
  const promise = requestFn()
    .finally(() => {
      // Clean up after request completes
      pendingRequests.delete(key);
    });

  pendingRequests.set(key, promise);
  return promise;
}

/**
 * Generate a cache key from request parameters.
 */
export function makeCacheKey(
  endpoint: string,
  params?: Record<string, unknown>
): string {
  if (!params || Object.keys(params).length === 0) {
    return endpoint;
  }

  const sortedParams = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => `${k}=${String(v)}`)
    .join('&');

  return `${endpoint}?${sortedParams}`;
}


// =============================================================================
// Debouncing
// =============================================================================

type DebouncedFunction<T extends (...args: unknown[]) => unknown> = {
  (...args: Parameters<T>): void;
  cancel: () => void;
  flush: () => void;
};

/**
 * Create a debounced version of a function.
 *
 * Use for search inputs, filters, and other user input that triggers API calls.
 *
 * @example
 * const debouncedSearch = debounce((query: string) => {
 *   searchTasks(query);
 * }, 300);
 *
 * // In component:
 * <input onChange={(e) => debouncedSearch(e.target.value)} />
 *
 * // Cleanup on unmount:
 * useEffect(() => () => debouncedSearch.cancel(), []);
 */
export function debounce<T extends (...args: unknown[]) => unknown>(
  fn: T,
  delayMs: number
): DebouncedFunction<T> {
  let timeoutId: ReturnType<typeof setTimeout> | null = null;
  let lastArgs: Parameters<T> | null = null;

  const debounced = (...args: Parameters<T>) => {
    lastArgs = args;

    if (timeoutId) {
      clearTimeout(timeoutId);
    }

    timeoutId = setTimeout(() => {
      timeoutId = null;
      fn(...args);
    }, delayMs);
  };

  debounced.cancel = () => {
    if (timeoutId) {
      clearTimeout(timeoutId);
      timeoutId = null;
    }
    lastArgs = null;
  };

  debounced.flush = () => {
    if (timeoutId && lastArgs) {
      clearTimeout(timeoutId);
      timeoutId = null;
      fn(...lastArgs);
    }
  };

  return debounced;
}

// =============================================================================
// Request Batching
// =============================================================================

interface BatchConfig<TKey, TResult> {
  /** Maximum batch size before auto-flush */
  maxSize: number;
  /** Maximum wait time in ms before auto-flush */
  maxWaitMs: number;
  /** Function to execute the batched request */
  batchFn: (keys: TKey[]) => Promise<Map<TKey, TResult>>;
}

interface BatchedLoader<TKey, TResult> {
  load: (key: TKey) => Promise<TResult>;
  loadMany: (keys: TKey[]) => Promise<TResult[]>;
}

/**
 * Create a batching loader that combines multiple requests.
 *
 * Instead of N individual requests, batches them into a single request.
 * Useful for fetching related data (e.g., user details for a list of IDs).
 *
 * @example
 * const userLoader = createBatchLoader({
 *   maxSize: 100,
 *   maxWaitMs: 10,
 *   batchFn: async (userIds) => {
 *     const users = await fetchUsersByIds(userIds);
 *     return new Map(users.map(u => [u.id, u]));
 *   }
 * });
 *
 * // These will be batched into a single API call:
 * const user1 = await userLoader.load(1);
 * const user2 = await userLoader.load(2);
 * const users = await userLoader.loadMany([3, 4, 5]);
 */
export function createBatchLoader<TKey, TResult>(
  config: BatchConfig<TKey, TResult>
): BatchedLoader<TKey, TResult> {
  let batch: Map<TKey, {
    resolve: (result: TResult) => void;
    reject: (error: Error) => void;
  }[]> = new Map();

  let timer: ReturnType<typeof setTimeout> | null = null;

  const flush = async () => {
    if (batch.size === 0) return;

    const currentBatch = batch;
    batch = new Map();

    if (timer) {
      clearTimeout(timer);
      timer = null;
    }

    const keys = Array.from(currentBatch.keys());

    try {
      const results = await config.batchFn(keys);

      currentBatch.forEach((callbacks, key) => {
        const result = results.get(key);
        if (result !== undefined) {
          callbacks.forEach((cb) => cb.resolve(result));
        } else {
          callbacks.forEach((cb) =>
            cb.reject(new Error(`No result for key: ${String(key)}`))
          );
        }
      });
    } catch (error) {
      currentBatch.forEach((callbacks) => {
        callbacks.forEach((cb) => cb.reject(error as Error));
      });
    }
  };

  const scheduleFlush = () => {
    if (!timer) {
      timer = setTimeout(flush, config.maxWaitMs);
    }
  };

  const load = (key: TKey): Promise<TResult> => {
    return new Promise((resolve, reject) => {
      const callbacks = batch.get(key) || [];
      callbacks.push({ resolve, reject });
      batch.set(key, callbacks);

      if (batch.size >= config.maxSize) {
        flush();
      } else {
        scheduleFlush();
      }
    });
  };

  const loadMany = async (keys: TKey[]): Promise<TResult[]> => {
    return Promise.all(keys.map(load));
  };

  return { load, loadMany };
}


// =============================================================================
// Parallel Loading
// =============================================================================

export interface ParallelLoadResult<T extends object> {
  data: T;
  errors: Partial<Record<keyof T, Error>>;
  isComplete: boolean;
}

/**
 * Load multiple resources in parallel with error isolation.
 *
 * Unlike Promise.all, this doesn't fail if one request fails.
 * Returns partial results with error information.
 *
 * @example
 * const { data, errors, isComplete } = await loadParallel({
 *   velocity: () => fetchVelocity(projectId),
 *   teamHealth: () => fetchTeamHealth(projectId),
 *   burndown: () => fetchBurndown(sprintId),
 *   dora: () => fetchDora(projectId),
 * });
 *
 * if (data.velocity) {
 *   // Use velocity data
 * }
 *
 * if (errors.dora) {
 *   console.error('DORA metrics failed:', errors.dora);
 * }
 */
export async function loadParallel<T extends Record<string, () => Promise<unknown>>>(
  loaders: T
): Promise<ParallelLoadResult<{ [K in keyof T]: Awaited<ReturnType<T[K]>> | null }>> {
  type ResultType = { [K in keyof T]: Awaited<ReturnType<T[K]>> | null };

  const keys = Object.keys(loaders) as (keyof T)[];

  const results = await Promise.allSettled(
    keys.map(key => loaders[key]())
  );

  const data = {} as ResultType;
  const errors: Partial<Record<keyof T, Error>> = {};

  keys.forEach((key, index) => {
    const result = results[index];
    if (result.status === 'fulfilled') {
      data[key] = result.value as ResultType[typeof key];
    } else {
      data[key] = null as ResultType[typeof key];
      errors[key] = result.reason instanceof Error
        ? result.reason
        : new Error(String(result.reason));
    }
  });

  return {
    data,
    errors,
    isComplete: Object.keys(errors).length === 0,
  };
}


// =============================================================================
// In-Memory Cache with TTL
// =============================================================================

interface CacheEntry<T> {
  value: T;
  expiresAt: number;
  staleAt: number;
}

interface CacheOptions {
  /** Time-to-live in milliseconds */
  ttlMs: number;
  /** Stale-while-revalidate window in milliseconds */
  staleWhileRevalidateMs?: number;
}

class MemoryCache {
  private cache = new Map<string, CacheEntry<unknown>>();
  private maxSize = 1000;

  get<T>(key: string): { value: T; isStale: boolean } | null {
    const entry = this.cache.get(key);

    if (!entry) {
      return null;
    }

    const now = Date.now();

    if (now >= entry.expiresAt) {
      // Expired - remove and return null
      this.cache.delete(key);
      return null;
    }

    if (now >= entry.staleAt) {
      // Stale but usable
      return { value: entry.value as T, isStale: true };
    }

    return { value: entry.value as T, isStale: false };
  }

  set<T>(key: string, value: T, options: CacheOptions): void {
    const now = Date.now();

    // LRU eviction if at capacity
    if (this.cache.size >= this.maxSize) {
      const firstKey = this.cache.keys().next().value;
      if (firstKey) {
        this.cache.delete(firstKey);
      }
    }

    this.cache.set(key, {
      value,
      staleAt: now + options.ttlMs,
      expiresAt: now + options.ttlMs + (options.staleWhileRevalidateMs || 0),
    });
  }

  delete(key: string): boolean {
    return this.cache.delete(key);
  }

  deletePattern(pattern: string): number {
    let count = 0;
    Array.from(this.cache.keys()).forEach((key) => {
      if (key.startsWith(pattern)) {
        this.cache.delete(key);
        count++;
      }
    });
    return count;
  }

  clear(): void {
    this.cache.clear();
  }
}

export const apiCache = new MemoryCache();


// =============================================================================
// Cache-Aware Fetch Wrapper
// =============================================================================

interface FetchWithCacheOptions extends CacheOptions {
  /** Skip cache and force fresh fetch */
  skipCache?: boolean;
  /** Deduplicate concurrent requests */
  deduplicate?: boolean;
}

/**
 * Fetch with automatic caching and deduplication.
 *
 * @example
 * const projectData = await fetchWithCache(
 *   'project-123',
 *   () => api.get('/projects/123'),
 *   { ttlMs: 60000, staleWhileRevalidateMs: 30000 }
 * );
 */
export async function fetchWithCache<T>(
  key: string,
  fetchFn: () => Promise<T>,
  options: FetchWithCacheOptions
): Promise<T> {
  // Check cache first (unless skipCache)
  if (!options.skipCache) {
    const cached = apiCache.get<T>(key);
    if (cached) {
      if (!cached.isStale) {
        console.debug(`[Cache] Hit (fresh): ${key}`);
        return cached.value;
      }

      // Return stale value but trigger background refresh
      console.debug(`[Cache] Hit (stale, revalidating): ${key}`);
      fetchWithCache(key, fetchFn, { ...options, skipCache: true }).catch(
        err => console.warn(`[Cache] Background revalidation failed: ${key}`, err)
      );
      return cached.value;
    }
  }

  // Fetch with optional deduplication
  const fetchPromise = options.deduplicate !== false
    ? deduplicateRequest(key, fetchFn)
    : fetchFn();

  const result = await fetchPromise;

  // Store in cache
  apiCache.set(key, result, options);
  console.debug(`[Cache] Stored: ${key}`);

  return result;
}


// =============================================================================
// Invalidation Helpers
// =============================================================================

/**
 * Invalidate all cache entries for a project.
 *
 * Call after mutations that affect project data.
 */
export function invalidateProjectCache(projectId: number): void {
  const patterns = [
    `project-${projectId}`,
    `team_health_${projectId}`,
    `velocity_${projectId}`,
    `budget_hours_${projectId}`,
    `value_metrics_${projectId}`,
    `dora_${projectId}`,
    `risks_${projectId}`,
    `forecast_${projectId}`,
  ];

  patterns.forEach(pattern => apiCache.deletePattern(pattern));
  console.debug(`[Cache] Invalidated project: ${projectId}`);
}

/**
 * Invalidate all cache entries for a sprint.
 */
export function invalidateSprintCache(sprintId: number): void {
  const patterns = [
    `sprint_${sprintId}`,
    `burndown_${sprintId}`,
    `wip_status_${sprintId}`,
    `capacity_${sprintId}`,
  ];

  patterns.forEach(pattern => apiCache.deletePattern(pattern));
  console.debug(`[Cache] Invalidated sprint: ${sprintId}`);
}

/**
 * Clear all cached data.
 *
 * Useful after logout or major data refresh.
 */
export function clearAllCache(): void {
  apiCache.clear();
  pendingRequests.clear();
  console.debug('[Cache] Cleared all');
}


// =============================================================================
// Analytics Loading Helper
// =============================================================================

interface AnalyticsData {
  velocity: VelocityResponse | null;
  teamHealth: TeamHealthMetrics | null;
  budgetHours: BudgetHoursResponse | null;
  valueMetrics: ValueMetricsResponse | null;
  dora: DoraMetrics | null;
  risks: RisksResponse | null;
}

/**
 * Load all analytics data for a project in parallel.
 *
 * Replaces sequential loading pattern with parallel requests.
 *
 * @example
 * // Before (sequential - slow):
 * const velocity = await getVelocity(projectId);
 * const health = await getProjectTeamHealth(projectId);
 * const budget = await getBudgetHours(projectId);
 *
 * // After (parallel - fast):
 * const analytics = await loadProjectAnalytics(projectId, api);
 */
export async function loadProjectAnalytics(
  projectId: number,
  api: {
    getVelocity: (id: number) => Promise<VelocityResponse>;
    getProjectTeamHealth: (id: number) => Promise<TeamHealthMetrics>;
    getBudgetHours: (id: number) => Promise<BudgetHoursResponse>;
    getValueMetrics: (id: number) => Promise<ValueMetricsResponse>;
    getDora: (id: number, days?: number) => Promise<DoraMetrics>;
    getRisks: (id: number) => Promise<RisksResponse>;
  }
): Promise<ParallelLoadResult<AnalyticsData>> {
  return loadParallel({
    velocity: () => api.getVelocity(projectId),
    teamHealth: () => api.getProjectTeamHealth(projectId),
    budgetHours: () => api.getBudgetHours(projectId),
    valueMetrics: () => api.getValueMetrics(projectId),
    dora: () => api.getDora(projectId),
    risks: () => api.getRisks(projectId),
  });
}
