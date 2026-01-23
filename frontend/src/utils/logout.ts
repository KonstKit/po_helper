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
function clearLocalStorage(): string[] {
  const clearedKeys: string[] = [];
  const preservedSet = new Set(PRESERVED_KEYS);

  try {
    // Get all keys first (to avoid modification during iteration)
    const allKeys: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key) allKeys.push(key);
    }

    // Clear keys
    for (const key of allKeys) {
      // Skip preserved keys
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
export function performLogout(
  dispatch: Dispatch,
  navigate: NavigateFunction,
  redirectPath: string = '/login'
): void {
  try {
    // Step 1: Clear cache storage
    storage.clearAll();

    // Step 2: Clear localStorage
    clearLocalStorage();

    // Step 3: Clear sessionStorage
    clearSessionStorage();

    // Step 4: Dispatch Redux logout action
    // This will clear auth state and trigger extraReducers in other slices
    dispatch(logoutAction());

    // Step 5: Navigate to login
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
