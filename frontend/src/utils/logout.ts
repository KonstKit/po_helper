/**
 * Complete logout utility
 *
 * This utility handles comprehensive cleanup of all application state
 * when a user logs out, including:
 * - Redux state (via authSlice.logout action)
 * - localStorage user-specific data
 * - Cache storage
 * - Session data
 *
 * Usage:
 *   import { performLogout } from '@/utils/logout';
 *
 *   const handleLogout = () => {
 *     performLogout(dispatch, navigate);
 *   };
 */

import { Dispatch } from '@reduxjs/toolkit';
import { NavigateFunction } from 'react-router-dom';
import { logout as logoutAction } from '../store/authSlice';
import { storage } from './storage';
import { analytics } from '../services/analytics';
import api from '../services/api/client';

/**
 * Keys to preserve across logout (non-sensitive, user-preference data)
 * These are typically UI preferences that can persist between sessions
 */
const PRESERVED_KEYS: string[] = [
  // None for now - clear everything for security
  // Add keys here if needed in the future, e.g.:
  // 'theme_preference',
  // 'language',
];

/**
 * Keys that MUST be cleared on logout (security-sensitive)
 * These are explicitly listed to ensure they're always cleared
 */
const CRITICAL_KEYS = [
  'token',                    // Auth token
  'account_created_at',       // User account timestamp
  'first_login_at',           // User first login
  'smart_defaults',           // User-specific defaults
];

/**
 * Patterns to match for bulk clearing
 * Any key matching these patterns will be cleared
 */
const CLEAR_PATTERNS = [
  /^cache_/,                  // All cache entries
  /^dashboard_/,              // Dashboard preferences
  /^knowledge_/,              // Knowledge page state
  /^onboarding_/,             // Onboarding state
  /^navigation_/,             // Navigation state
  /^po_helper_/,              // App-namespaced prefs (e.g. selected project) — codex P3
  /analytics_/,               // Analytics data
  /adoption_/,                // Feature adoption tracking
  /metrics_/,                 // User metrics
];

/**
 * Clear all user-specific data from localStorage
 *
 * This function iterates through all localStorage keys and removes:
 * 1. Critical security keys (token, user data)
 * 2. Keys matching clear patterns (cache, preferences)
 * 3. All other keys except those in PRESERVED_KEYS
 *
 * @returns Array of cleared keys (for logging/debugging)
 */
function clearLocalStorage(extraPreserve?: readonly string[]): string[] {
  const clearedKeys: string[] = [];
  const preservedSet = new Set<string>(PRESERVED_KEYS);
  if (extraPreserve) {
    extraPreserve.forEach((key) => preservedSet.add(key));
  }

  try {
    // Get all keys first (to avoid modification during iteration)
    const allKeys: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key) allKeys.push(key);
    }

    // Clear keys
    for (const key of allKeys) {
      // Skip preserved keys (PRESERVED_KEYS + caller-provided extras).
      // CRITICAL_KEYS / CLEAR_PATTERNS are not skipped automatically; the
      // caller must opt in by adding the key to extraPreserve so security-
      // sensitive defaults stay aggressive on full logout.
      if (preservedSet.has(key)) {
        continue;
      }

      // Check if key matches any clear pattern
      const shouldClear =
        CRITICAL_KEYS.includes(key) ||
        CLEAR_PATTERNS.some(pattern => pattern.test(key));

      if (shouldClear) {
        localStorage.removeItem(key);
        clearedKeys.push(key);
      }
    }

  } catch (error) {
    console.error('[Logout] Error clearing localStorage:', error);
  }

  return clearedKeys;
}

/**
 * Clear all sessionStorage data
 */
function clearSessionStorage(): void {
  try {
    sessionStorage.clear();
  } catch (error) {
    console.error('[Logout] Error clearing sessionStorage:', error);
  }
}

/**
 * Perform complete logout
 *
 * This is the main logout function that should be called when user logs out.
 * It performs the following steps:
 * 1. Clear cache storage (via SafeStorage)
 * 2. Clear localStorage (user data, preferences, tokens)
 * 3. Clear sessionStorage
 * 4. Dispatch Redux logout action (clears Redux state)
 * 5. Navigate to login page
 *
 * @param dispatch Redux dispatch function
 * @param navigate React Router navigate function
 * @param redirectPath Optional path to redirect after logout (default: '/login')
 */
let cookieClearPromise: Promise<void> | null = null;

/** Resolves when any in-flight backend cookie-clear settles (or null). */
export function waitForCookieClear(): Promise<void> | null {
  return cookieClearPromise;
}

export async function performLogout(
  dispatch: Dispatch,
  navigate: NavigateFunction,
  redirectPath: string = '/login',
): Promise<void> {
  try {
    // Step 0 (JWT storage migration M2): ask the backend to clear the
    // httpOnly auth cookie. Awaited (bounded by the axios timeout) so a
    // subsequent login is serialized after the cookie clear; on failure
    // we proceed anyway - the cookie expires with the JWT TTL, and M3
    // adds real server-side revocation.
    const existing = cookieClearPromise;
    if (existing) {
      // Idempotent: concurrent logouts reuse one in-flight clear so the
      // shared handle is never overwritten and a later clear can never
      // delete a cookie that a subsequent login just created.
      await existing;
    } else {
      const clear = api
        .post("/v1/auth/logout", undefined, { timeout: 5000 })
        .then(() => undefined)
        .catch((error) => {
          console.warn("[Logout] backend cookie clear failed; continuing local cleanup", error);
        });
      cookieClearPromise = clear;
      await clear;
      if (cookieClearPromise === clear) {
        cookieClearPromise = null;
      }
    }
    // Step 1: Clear cache storage
    storage.clearAll();

    // Step 2: Drop in-memory analytics queue + persisted pending batch.
    // Must happen before localStorage.clear so we don't race with the
    // singleton's own writes, and explicit so we cover the path that does
    // not hit the 'auth-error' listener (manual logout from UI).
    analytics.resetForLogout();

    // Step 3: Clear localStorage
    clearLocalStorage();

    // Step 4: Clear sessionStorage
    clearSessionStorage();

    // Step 5: Dispatch Redux logout action
    // This will clear auth state and trigger extraReducers in other slices
    dispatch(logoutAction());

    // Step 6: Navigate to login
    navigate(redirectPath);
  } catch (error) {
    console.error('[Logout] Error during logout:', error);

    // Even if there's an error, try to navigate to login
    try {
      navigate(redirectPath);
    } catch (navError) {
      console.error('[Logout] Error navigating to login:', navError);
    }
  }
}

/**
 * Cleanup on a forced 401 / session expiry.
 *
 * Differs from `performLogout` in exactly one way: the analytics backend
 * transport queue (`pendingBatch` + owner marker) is *preserved*. The
 * common case here is "the same user's token expired"; if that user
 * signs back in we want their queued events to flush. Owner-marker
 * comparison protects against the rare different-user case.
 *
 * Everything else — local storage cleanup, session storage, Redux
 * logout, navigation, plus per-user analytics UI state (events log,
 * onboarding/TTV/feature-visit/first_view markers, sessionId) — is
 * wiped exactly like `performLogout`.
 */
export function performAuthErrorCleanup(
  dispatch: Dispatch,
  navigate: NavigateFunction,
  redirectPath: string = '/login',
): void {
  try {
    storage.clearAll();
    // UI-only analytics reset: keeps the in-memory pendingBatch + owner
    // marker so a same-user re-auth still drains queued events.
    analytics.softResetForAuthError();
    // clearLocalStorage matches pattern /analytics_/ and will wipe the
    // persisted analytics transport keys along with everything else.
    // We explicitly preserve the keys that softResetForAuthError chose to
    // keep, so a same-user re-auth does not get pushed back through
    // onboarding or have their TTV baseline reset to "now".
    clearLocalStorage([
      'account_created_at',
      'first_login_at',
      'onboarding_progress',
      'onboarding_completed',
      'time_to_value_metrics',
      // NB: po_helper_selected_project_id is intentionally NOT preserved here.
      // Preserving it let a different user after a 401 inherit the previous
      // user's project (dropInheritedStateIfOwnerChanged doesn't clear it), so
      // it is cleared on both paths via the /^po_helper_/ pattern (codex P2).
      // Carries the owner of the soft-reset session so the next login can
      // detect cross-user signin and wipe the keys above. Same-user re-auth
      // consumes and clears it via dropInheritedStateIfOwnerChanged().
      'po_helper_analytics_previous_owner',
      // (JWT storage M2) The pending analytics batch keeps its ORIGINAL
      // owner marker through cleanup: an ownerless queue cannot be
      // attributed, so analytics flush must reject it instead of
      // transmitting a previous user's events under a new login.
      'po_helper_analytics_pending_owner',
    ]);
    clearSessionStorage();
    // Re-persist the singleton's authoritative in-memory pendingBatch.
    // This is race-safe: if a successful flush spliced the queue during
    // cleanup, we persist the already-shrunk version (no duplicate
    // delivery on next session). If no flush occurred, we persist the
    // original queue so re-auth can drain it.
    analytics.persistPendingBatchToStorage();

    dispatch(logoutAction());
    navigate(redirectPath);
  } catch (error) {
    console.error('[AuthErrorCleanup] Error during cleanup:', error);
    try {
      navigate(redirectPath);
    } catch (navError) {
      console.error('[AuthErrorCleanup] Error navigating to login:', navError);
    }
  }
}

/**
 * Get logout statistics (for debugging/monitoring)
 *
 * Returns information about what will be cleared on logout
 */
export function getLogoutStats(): {
  totalKeys: number;
  willClear: number;
  willPreserve: number;
  criticalKeys: string[];
  cacheKeys: number;
} {
  const stats = {
    totalKeys: localStorage.length,
    willClear: 0,
    willPreserve: 0,
    criticalKeys: [] as string[],
    cacheKeys: 0,
  };

  const preservedSet = new Set(PRESERVED_KEYS);

  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (!key) continue;

    if (preservedSet.has(key)) {
      stats.willPreserve++;
      continue;
    }

    const shouldClear =
      CRITICAL_KEYS.includes(key) ||
      CLEAR_PATTERNS.some(pattern => pattern.test(key));

    if (shouldClear) {
      stats.willClear++;

      if (CRITICAL_KEYS.includes(key)) {
        stats.criticalKeys.push(key);
      }

      if (key.startsWith('cache_')) {
        stats.cacheKeys++;
      }
    }
  }

  return stats;
}
