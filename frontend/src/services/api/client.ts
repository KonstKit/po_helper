/**
 * Axios client configuration with interceptors and retry logic.
 *
 * This module provides:
 * - Configured axios instance with base URL and timeout
 * - Request interceptor for auth token injection
 * - Response interceptor for error handling and auth refresh
 * - Exponential backoff retry helper for transient failures
 */
import axios, { type InternalAxiosRequestConfig } from "axios";
import { API_TIMEOUT_MS } from '../../constants/app';
import { logError } from '../../utils/errorUtils';

// Avoid a static import cycle (client → analytics → usageAnalyticsApi → client).
// The analytics singleton registers a window-scoped callback in its
// constructor; the interceptor invokes it via window to capture the
// pending-batch owner marker before the token is removed.
type AuthSnapshotFn = () => void;
declare global {
  interface Window {
    __poAnalyticsSnapshotOwner?: AuthSnapshotFn;
  }
}

/** Base URL for API v1 endpoints */
export const API_BASE_URL = "/api/v1";

/**
 * Open the live-updates WebSocket.
 *
 * Browsers cannot set headers on a WebSocket handshake, so the JWT is
 * first exchanged for a short-lived single-use ticket over an
 * authenticated HTTP call; only the ticket goes into the URL (never the
 * token itself). Returns null when there is no session or the ticket
 * could not be obtained - callers must not open a socket in that case.
 */
export const openWebSocket = async (): Promise<WebSocket | null> => {
  try {
    const response = await api.post<{ ticket: string }>(
      '/v1/auth/ws-ticket',
      {},
    );
    const ticket = response.data?.ticket;
    if (!ticket) return null;
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    return new WebSocket(
      `${protocol}://${window.location.host}/api/v1/ws?ticket=${encodeURIComponent(ticket)}`,
    );
  } catch {
    return null;
  }
};

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
  timeout: API_TIMEOUT_MS,
  // JWT storage migration M2: the session lives in an httpOnly cookie;
  // cookies ride along automatically on same-origin XHR.
  withCredentials: true,
});

const SESSION_ERROR_SNIPPETS = [
  "not authenticated",
  "could not validate credentials",
  "invalid token",
  "token expired",
  "session expired",
  "invalid or expired temporary token",
];

const getStringHeader = (
  headers: unknown,
  key: string,
): string => {
  if (!headers || typeof headers !== "object") return "";
  const record = headers as Record<string, unknown>;
  const value = record[key] ?? record[key.toLowerCase()] ?? record[key.toUpperCase()];
  return typeof value === "string" ? value : "";
};

const getErrorDetail = (error: unknown): string => {
  if (!error || typeof error !== "object") return "";
  const response = (error as { response?: unknown }).response;
  if (!response || typeof response !== "object") return "";
  const data = (response as { data?: unknown }).data;
  if (!data || typeof data !== "object") return "";
  const detail = (data as { detail?: unknown }).detail;
  return typeof detail === "string" ? detail : "";
};

const shouldInvalidateSession = (error: unknown): boolean => {
  if (!error || typeof error !== "object") return false;
  const response = (error as { response?: { headers?: unknown } }).response;
  const headers = response?.headers;
  const authHeader = getStringHeader(headers, "www-authenticate").toLowerCase();
  const detail = getErrorDetail(error).toLowerCase();
  const matchesSessionDetail = SESSION_ERROR_SNIPPETS.some((snippet) => detail.includes(snippet));

  // Some backends return only a Bearer challenge without a structured error body.
  // Do not invalidate a session based solely on a Bearer challenge if we have a
  // non-session error detail (e.g. integration auth failures).
  if (matchesSessionDetail) return true;
  return authHeader.includes("bearer") && detail.length === 0;
};

const isCanceledError = (error: unknown): boolean => {
  if (axios.isCancel(error)) return true;
  if (!error || typeof error !== "object") return false;
  const code = (error as { code?: unknown }).code;
  const name = (error as { name?: unknown }).name;
  return code === "ERR_CANCELED" || name === "CanceledError";
};

// ---------------------------------------------------------------------------
// Silent session refresh (JWT storage M4): the browser holds only httpOnly
// cookies, so when an access cookie expires the interceptor rotates it via
// /auth/refresh and replays the original request once. Concurrent 401s share
// a single in-flight rotation; the refresh call itself never recurses.
// ---------------------------------------------------------------------------
const REFRESH_PATH = "/v1/auth/refresh";
const refreshClient = axios.create({
  baseURL: "/api",
  timeout: API_TIMEOUT_MS,
  withCredentials: true,
});

let refreshInFlight: Promise<boolean> | null = null;

const refreshSession = (): Promise<boolean> => {
  if (!refreshInFlight) {
    refreshInFlight = refreshClient
      .post(REFRESH_PATH)
      .then(() => true)
      .catch(() => false)
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
};

type ReplayingConfig = InternalAxiosRequestConfig & {
  _sessionReplayed?: boolean;
};

const isReplay = (config: unknown): boolean =>
  Boolean((config as ReplayingConfig | undefined)?._sessionReplayed);

const isRefreshCall = (config: unknown): boolean => {
  const url = (config as { url?: string } | undefined)?.url ?? "";
  return url.endsWith(REFRESH_PATH);
};

// Request interceptor: the httpOnly auth cookie rides along on same-origin
// requests automatically (withCredentials above); no Authorization header
// injection from localStorage anymore (JWT storage migration M2).
api.interceptors.request.use((config) => config);

// Response interceptor: handle errors and emit events for UI
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    // Ignore intentionally canceled requests (AbortController/navigation).
    // They are expected control flow and not backend availability issues.
    if (isCanceledError(error)) {
      return Promise.reject(error);
    }

    // Handle timeout errors
    if (error.code === "ECONNABORTED" || error.message?.includes("timeout")) {
      logError("Backend timeout - server may be unresponsive", error);

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
      logError("Backend unreachable - network error", error);

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

    // Session probes (boot restore) must stay silent: their 401 simply
    // means no cookie session and is reported through the thunk result,
    // never through the auth-error broadcast.
    const probeConfig = (error.config ?? {}) as { headers?: Record<string, unknown> };
    const probeHeaders = probeConfig.headers;
    const isSessionProbe = Boolean(
      probeHeaders && (probeHeaders["X-Session-Probe"] ?? probeHeaders["x-session-probe"])
    );
    if (isSessionProbe && error.response?.status === 401) {
      return Promise.reject(error);
    }

    // Session-related 401: attempt one silent refresh (shared single-flight)
    // and replay the original request once. On failure fall through to the
    // auth-error broadcast below. Skipped for the refresh call itself, the
    // boot probe, and replays (no loops).
    if (
      error.response?.status === 401 &&
      shouldInvalidateSession(error) &&
      !isSessionProbe &&
      !isRefreshCall(error.config) &&
      !isReplay(error.config)
    ) {
      const refreshed = await refreshSession();
      if (refreshed && error.config) {
        const config = error.config as ReplayingConfig;
        config._sessionReplayed = true;
        return api.request(config);
      }
    }

    // Handle session-related 401 Unauthorized only.
    // Integration checks may return 401 from external systems and must not logout the user.
    if (error.response?.status === 401 && shouldInvalidateSession(error)) {
      if (typeof window !== 'undefined') {
        // Snapshot the analytics queue owner marker synchronously, BEFORE
        // any cleanup, so the persisted pending batch keeps its previous
        // owner stamp once performAuthErrorCleanup wipes the token.
        try {
          window.__poAnalyticsSnapshotOwner?.();
        } catch {
          // Snapshot is best-effort; never let it block the auth flow.
        }
        // Token removal is intentionally deferred to performAuthErrorCleanup
        // (utils/logout.ts). Removing it here causes a startup race: if a
        // 401 fires before App.tsx mounts the 'auth-error' listener, the
        // event is lost AND the token is already gone, so subsequent
        // retries return plain "Not authenticated" 401s that
        // shouldInvalidateSession() filters out — leaving Redux's
        // isAuthenticated=true stuck until a hard refresh. App.tsx mounts
        // the listener before initializeAppData() runs (see useEffect
        // ordering there) so the event is observed and cleanup proceeds.
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
