import { logError } from './errorUtils';

export function readStoredJson<T>(key: string, fallback: T): T {
  if (typeof window === 'undefined') {
    return fallback;
  }

  const raw = window.localStorage.getItem(key);
  if (!raw) {
    return fallback;
  }

  try {
    return JSON.parse(raw) as T;
  } catch (error) {
    logError(`[storage] Failed to parse ${key}`, error);
    window.localStorage.removeItem(key);
    return fallback;
  }
}

export function writeStoredJson(key: string, value: unknown): void {
  if (typeof window === 'undefined') {
    return;
  }

  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch (error) {
    logError(`[storage] Failed to persist ${key}`, error);
  }
}
