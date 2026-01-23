/**
 * useParallelLoading Hook
 *
 * React hook for parallel data loading with progress tracking and error handling.
 * Built on top of the loadParallel utility from apiOptimization.
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import { loadParallel } from '../utils/apiOptimization';

/** Progress state interface */
export interface LoadingProgress {
  loading: boolean;
  percent: number;
  step: string;
}

/** Loading state for a specific key */
export interface LoadingState<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
}

/** Configuration options for the hook */
export interface UseParallelLoadingOptions {
  /** Initial progress step message */
  initialStep?: string;
  /** Progress step when loading completes */
  completeStep?: string;
  /** Whether to reset data to null before loading */
  resetOnLoad?: boolean;
}

type LoadedData<T> = Partial<{ [K in keyof T]: T[K] | null }>;

/** Result type for the hook */
export interface UseParallelLoadingResult<T extends Record<string, unknown>> {
  /** Current data state (all loaded values) */
  data: LoadedData<T>;
  /** Current errors (per key) */
  errors: Partial<Record<keyof T, Error>>;
  /** Progress tracking state */
  progress: LoadingProgress;
  /** Whether any data is currently loading */
  isLoading: boolean;
  /** Whether all data has been loaded without errors */
  isComplete: boolean;
  /** Trigger a load operation */
  load: (loaders: { [K in keyof T]: () => Promise<T[K]> }) => Promise<void>;
  /** Reset all data and errors */
  reset: () => void;
  /** Update a single data key */
  setData: <K extends keyof T>(key: K, value: T[K]) => void;
}

const DEFAULT_OPTIONS: UseParallelLoadingOptions = {
  initialStep: 'Loading...',
  completeStep: 'Ready',
  resetOnLoad: true,
};

/**
 * Hook for parallel data loading with automatic state management.
 *
 * @example
 * ```tsx
 * interface AnalyticsData {
 *   velocity: VelocityResponse | null;
 *   burndown: BurndownResponse | null;
 *   risks: RisksResponse | null;
 * }
 *
 * const {
 *   data,
 *   errors,
 *   progress,
 *   isLoading,
 *   load
 * } = useParallelLoading<AnalyticsData>();
 *
 * useEffect(() => {
 *   if (projectId) {
 *     load({
 *       velocity: () => getVelocity(projectId),
 *       burndown: () => getBurndown(projectId),
 *       risks: () => getRisks(projectId),
 *     });
 *   }
 * }, [projectId, load]);
 *
 * if (progress.loading) {
 *   return <LoadingSpinner message={progress.step} />;
 * }
 *
 * return <AnalyticsView velocity={data.velocity} burndown={data.burndown} />;
 * ```
 */
export function useParallelLoading<T extends Record<string, unknown>>(
  options: UseParallelLoadingOptions = {}
): UseParallelLoadingResult<T> {
  const opts = { ...DEFAULT_OPTIONS, ...options };

  // State management
  const [data, setDataState] = useState<LoadedData<T>>({});
  const [errors, setErrors] = useState<Partial<Record<keyof T, Error>>>({});
  const [progress, setProgress] = useState<LoadingProgress>({
    loading: false,
    percent: 0,
    step: '',
  });

  // Track if component is mounted to prevent state updates after unmount
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // Abort controller for cancellation
  const abortRef = useRef<AbortController | null>(null);

  /**
   * Load data in parallel using the provided loaders.
   */
  const load = useCallback(
    async (loaders: { [K in keyof T]: () => Promise<T[K]> }): Promise<void> => {
      // Cancel any previous load
      if (abortRef.current) {
        abortRef.current.abort();
      }
      abortRef.current = new AbortController();

      if (!mountedRef.current) return;

      // Reset data if option is set
      if (opts.resetOnLoad) {
        const resetData: LoadedData<T> = {};
        const keys = Object.keys(loaders) as Array<keyof T>;
        keys.forEach((key) => {
          resetData[key] = null;
        });
        setDataState(resetData);
      }

      // Set loading state
      setProgress({
        loading: true,
        percent: 0,
        step: opts.initialStep || 'Loading...',
      });
      setErrors({});

      try {
        // Execute parallel load
        const result = await loadParallel(loaders);

        if (!mountedRef.current) return;

        // Update data state
        setDataState(result.data);

        // Update errors
        const newErrors: Partial<Record<keyof T, Error>> = {};
        const keys = Object.keys(loaders) as Array<keyof T>;
        keys.forEach((key) => {
          const error = result.errors[key];
          if (error) {
            newErrors[key] = error;
          }
        });
        setErrors(newErrors);

        // Set complete state
        setProgress({
          loading: false,
          percent: 100,
          step: opts.completeStep || 'Ready',
        });
      } catch (err) {
        if (!mountedRef.current) return;

        // Handle unexpected errors
        setProgress({
          loading: false,
          percent: 0,
          step: 'Error',
        });

        // Set a generic error for all keys
        const genericError = err instanceof Error ? err : new Error(String(err));
        const errorState: Partial<Record<keyof T, Error>> = {};
        const keys = Object.keys(loaders) as Array<keyof T>;
        keys.forEach((key) => {
          errorState[key] = genericError;
        });
        setErrors(errorState);
      }
    },
    [opts.initialStep, opts.completeStep, opts.resetOnLoad]
  );

  /**
   * Reset all data and errors.
   */
  const reset = useCallback(() => {
    setDataState({});
    setErrors({});
    setProgress({
      loading: false,
      percent: 0,
      step: '',
    });
  }, []);

  /**
   * Update a single data key.
   */
  const setData = useCallback(<K extends keyof T>(key: K, value: T[K]) => {
    setDataState((prev) => ({
      ...prev,
      [key]: value,
    }));
  }, []);

  return {
    data,
    errors,
    progress,
    isLoading: progress.loading,
    isComplete: !progress.loading && Object.keys(errors).length === 0,
    load,
    reset,
    setData,
  };
}

/**
 * Simplified hook for single-value loading with the same pattern.
 */
export function useAsyncData<T>(
  initialValue: T | null = null
): {
  data: T | null;
  error: Error | null;
  loading: boolean;
  load: (fetcher: () => Promise<T>) => Promise<void>;
  reset: () => void;
} {
  const [data, setData] = useState<T | null>(initialValue);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(false);

  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const load = useCallback(async (fetcher: () => Promise<T>) => {
    setLoading(true);
    setError(null);

    try {
      const result = await fetcher();
      if (mountedRef.current) {
        setData(result);
      }
    } catch (err) {
      if (mountedRef.current) {
        setError(err instanceof Error ? err : new Error(String(err)));
      }
    } finally {
      if (mountedRef.current) {
        setLoading(false);
      }
    }
  }, []);

  const reset = useCallback(() => {
    setData(initialValue);
    setError(null);
    setLoading(false);
  }, [initialValue]);

  return { data, error, loading, load, reset };
}

export default useParallelLoading;
