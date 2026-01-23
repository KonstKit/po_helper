/**
 * Debounce hooks for search/filter inputs.
 *
 * Prevents excessive API calls by delaying execution until user stops typing.
 */

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';

// =============================================================================
// useDebouncedValue - Debounce a value
// =============================================================================

/**
 * Returns a debounced version of the input value.
 *
 * The debounced value only updates after the specified delay has passed
 * without the input value changing.
 *
 * @example
 * function SearchInput() {
 *   const [query, setQuery] = useState('');
 *   const debouncedQuery = useDebouncedValue(query, 300);
 *
 *   useEffect(() => {
 *     if (debouncedQuery) {
 *       searchTasks(debouncedQuery);
 *     }
 *   }, [debouncedQuery]);
 *
 *   return <input value={query} onChange={(e) => setQuery(e.target.value)} />;
 * }
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedValue(value);
    }, delayMs);

    return () => {
      clearTimeout(timer);
    };
  }, [value, delayMs]);

  return debouncedValue;
}


// =============================================================================
// useDebouncedCallback - Debounce a callback function
// =============================================================================

/**
 * Returns a debounced version of the callback function.
 *
 * The callback will only be invoked after the specified delay has passed
 * without the function being called again.
 *
 * @example
 * function FilterPanel({ onFilterChange }) {
 *   const debouncedFilterChange = useDebouncedCallback(
 *     (filters) => onFilterChange(filters),
 *     300
 *   );
 *
 *   return (
 *     <select onChange={(e) => debouncedFilterChange({ status: e.target.value })}>
 *       <option value="">All</option>
 *       <option value="open">Open</option>
 *       <option value="closed">Closed</option>
 *     </select>
 *   );
 * }
 */
export function useDebouncedCallback<T extends (...args: unknown[]) => unknown>(
  callback: T,
  delayMs: number
): T {
  const callbackRef = useRef(callback);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Keep callback ref updated
  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, []);

  const debouncedCallback = useCallback(
    (...args: Parameters<T>) => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }

      timerRef.current = setTimeout(() => {
        callbackRef.current(...args);
      }, delayMs);
    },
    [delayMs]
  );

  return debouncedCallback as T;
}


// =============================================================================
// useThrottledCallback - Throttle a callback function
// =============================================================================

/**
 * Returns a throttled version of the callback function.
 *
 * Unlike debounce, throttle ensures the callback is called at most once
 * per specified interval, even if called multiple times.
 *
 * Use for scroll handlers, resize events, etc.
 *
 * @example
 * function InfiniteScroll() {
 *   const throttledScroll = useThrottledCallback(
 *     () => checkScrollPosition(),
 *     100
 *   );
 *
 *   useEffect(() => {
 *     window.addEventListener('scroll', throttledScroll);
 *     return () => window.removeEventListener('scroll', throttledScroll);
 *   }, [throttledScroll]);
 * }
 */
export function useThrottledCallback<T extends (...args: unknown[]) => unknown>(
  callback: T,
  intervalMs: number
): T {
  const callbackRef = useRef(callback);
  const lastCalledRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Keep callback ref updated
  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, []);

  const throttledCallback = useCallback(
    (...args: Parameters<T>) => {
      const now = Date.now();
      const timeSinceLastCall = now - lastCalledRef.current;

      if (timeSinceLastCall >= intervalMs) {
        lastCalledRef.current = now;
        callbackRef.current(...args);
      } else {
        // Schedule trailing call
        if (timerRef.current) {
          clearTimeout(timerRef.current);
        }

        timerRef.current = setTimeout(() => {
          lastCalledRef.current = Date.now();
          callbackRef.current(...args);
        }, intervalMs - timeSinceLastCall);
      }
    },
    [intervalMs]
  );

  return throttledCallback as T;
}


// =============================================================================
// useDebounceState - Debounced state with immediate and debounced values
// =============================================================================

interface DebounceStateResult<T> {
  /** Current value (updates immediately) */
  value: T;
  /** Debounced value (updates after delay) */
  debouncedValue: T;
  /** Set the value */
  setValue: (value: T) => void;
  /** Is the debounced value pending update? */
  isPending: boolean;
}

/**
 * Provides both immediate and debounced versions of state.
 *
 * Useful when you need immediate UI feedback but debounced API calls.
 *
 * @example
 * function SearchInput() {
 *   const { value, debouncedValue, setValue, isPending } = useDebounceState('', 300);
 *
 *   useEffect(() => {
 *     if (debouncedValue) {
 *       searchTasks(debouncedValue);
 *     }
 *   }, [debouncedValue]);
 *
 *   return (
 *     <div>
 *       <input value={value} onChange={(e) => setValue(e.target.value)} />
 *       {isPending && <span>Searching...</span>}
 *     </div>
 *   );
 * }
 */
export function useDebounceState<T>(
  initialValue: T,
  delayMs: number
): DebounceStateResult<T> {
  const [value, setValue] = useState<T>(initialValue);
  const [debouncedValue, setDebouncedValue] = useState<T>(initialValue);
  const [isPending, setIsPending] = useState(false);

  useEffect(() => {
    if (value !== debouncedValue) {
      setIsPending(true);
    }

    const timer = setTimeout(() => {
      setDebouncedValue(value);
      setIsPending(false);
    }, delayMs);

    return () => {
      clearTimeout(timer);
    };
  }, [value, delayMs]);

  return useMemo(
    () => ({
      value,
      debouncedValue,
      setValue,
      isPending,
    }),
    [value, debouncedValue, isPending]
  );
}


// =============================================================================
// Recommended delay constants
// =============================================================================

/**
 * Recommended debounce delays for different use cases.
 */
export const DEBOUNCE_DELAYS = {
  /** For instant search/autocomplete (fast typing expected) */
  SEARCH_FAST: 150,

  /** For standard search inputs */
  SEARCH: 300,

  /** For filter dropdowns and checkboxes */
  FILTER: 200,

  /** For form validation on blur */
  VALIDATION: 400,

  /** For expensive operations (analytics refresh) */
  EXPENSIVE: 500,

  /** For resize handlers */
  RESIZE: 100,
} as const;
