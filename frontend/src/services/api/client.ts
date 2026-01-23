/**
 * Axios client configuration with interceptors and retry logic.
 *
 * This module provides:
 * - Configured axios instance with base URL and timeout
 * - Request interceptor for auth token injection
 * - Response interceptor for error handling and auth refresh
 * - Exponential backoff retry helper for transient failures
 */
import axios from "axios";

/** Base URL for API v1 endpoints */
export const API_BASE_URL = "/api/v1";

/** Default cache TTL in milliseconds (1 minute) */
export const CACHE_TTL = 60000;

/**
 * Pre-configured axios instance for all API calls.
 *
 * Features:
 * - Base URL: /api
 * - Timeout: 15 seconds (fail-fast for better UX)
 * - Auth token injection via request interceptor
 * - Error broadcasting via CustomEvents for UI notifications
 */
const api = axios.create({
  baseURL: "/api",
  timeout: 15000,
});

// Request interceptor: inject auth token
api.interceptors.request.use((config) => {
  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;

  if (token) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${token}`;
  }

  return config;
});

// Response interceptor: handle errors and emit events for UI
api.interceptors.response.use(
  (response) => response,
  (error) => {
    // Handle timeout errors
    if (error.code === "ECONNABORTED" || error.message?.includes("timeout")) {
      console.error("Backend timeout - server may be unresponsive");

      if (typeof window !== 'undefined') {
        window.dispatchEvent(
          new CustomEvent("backend-error", {
            detail: {
              type: "timeout",
              message: "Backend server is not responding",
            },
          }),
        );
      }
    } else if (!error.response) {
      // Handle network errors (backend unreachable)
      console.error("Backend unreachable - network error");

      if (typeof window !== 'undefined') {
        window.dispatchEvent(
          new CustomEvent("backend-error", {
            detail: {
              type: "network",
              message: "Cannot connect to backend server",
            },
          }),
        );
      }
    }

    // Handle 401 Unauthorized - clear token and emit auth error
    if (error.response?.status === 401) {
      if (typeof window !== 'undefined') {
        localStorage.removeItem('token');
        window.dispatchEvent(
          new CustomEvent('auth-error', {
            detail: {
              type: 'unauthorized',
              message: 'Session expired. Please sign in again.',
            },
          }),
        );
      }
    }

    return Promise.reject(error);
  },
);

/**
 * Generic retry helper with exponential backoff and jitter.
 *
 * Automatically retries on:
 * - Timeout errors (ECONNABORTED)
 * - Rate limiting (429)
 * - Server errors (502, 503, 504)
 *
 * Does NOT retry on:
 * - Canceled requests (ERR_CANCELED)
 * - Client errors (4xx except 429)
 * - Non-retriable server errors
 *
 * @param fn - Async function to execute
 * @param opts - Retry options
 * @returns Promise resolving to the function result
 */
export async function withRetry<T>(
  fn: () => Promise<T>,
  opts?: { retries?: number; baseDelayMs?: number; maxDelayMs?: number },
): Promise<T> {
  const retries = opts?.retries ?? 2;
  const base = opts?.baseDelayMs ?? 300;
  const maxDelay = opts?.maxDelayMs ?? 4000;

  let attempt = 0;

  const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === 'object' && value !== null;

  const getErrorInfo = (err: unknown): { code?: string; message?: string; status?: number } => {
    if (!isRecord(err)) return {};
    const code = typeof err.code === 'string' ? err.code : undefined;
    const message = typeof err.message === 'string' ? err.message : undefined;
    let status: number | undefined;
    if (isRecord(err.response) && typeof err.response.status === 'number') {
      status = err.response.status;
    }
    return { code, message, status };
  };

  while (true) {
    try {
      return await fn();
    } catch (err: unknown) {
      const { code, message, status } = getErrorInfo(err);

      // Do not retry canceled/aborted requests
      if (code === "ERR_CANCELED") throw err;

      const retriable =
        code === "ECONNABORTED" ||
        message?.includes("timeout") ||
        [429, 502, 503, 504].includes(status || 0);

      if (!retriable || attempt >= retries) throw err;

      // Exponential backoff with jitter (0.8-1.2x multiplier)
      const delay =
        Math.min(maxDelay, base * Math.pow(2, attempt)) *
        (0.8 + Math.random() * 0.4);

      await new Promise((res) => setTimeout(res, delay));
      attempt++;
    }
  }
}

export default api;
