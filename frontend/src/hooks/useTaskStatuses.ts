/**
 * useTaskStatuses Hook
 *
 * Centralizes task status normalization and categorization logic.
 * Extracted from Dashboard.tsx for reusability across components.
 */

import { useCallback } from 'react';

/** Status bucket categories for task classification */
export type StatusBucket = 'todo' | 'in_progress' | 'blocked' | 'done' | 'other';

/** Status statistics interface */
export interface StatusStats {
  todo: number;
  in_progress: number;
  blocked: number;
  done: number;
  other: number;
  total: number;
}

/** Done status variations for matching */
const DONE_MATCHES = [
  'done',
  'closed',
  'resolved',
  'work done',
  'workdone',
  'requirements done',
  'completed',
  'complete',
];

/** Todo/backlog status variations */
const TODO_MATCHES = [
  'backlog',
  'to do',
  'todo',
  'design ready',
  'ready for refinement',
];

/** In-progress status variations (exact matches) */
const IN_PROGRESS_EXACT = [
  'in progress',
  'in review',
  'code review',
  'review',
  'testing',
  'ready for qa',
  'ready for test',
  'qa',
  'po review',
  'requirements review',
  'in ba',
  'in design',
];

/**
 * Normalize a status string to lowercase trimmed format.
 *
 * @param status - Raw status string (may be null/undefined)
 * @returns Normalized lowercase trimmed string
 */
export function normalizeStatus(status?: string | null): string {
  return (status ?? '').trim().toLowerCase();
}

/**
 * Categorize a task status into one of the standard buckets.
 *
 * @param status - Raw status string
 * @returns StatusBucket classification
 */
export function categorizeStatus(status?: string | null): StatusBucket {
  const normalized = normalizeStatus(status);

  if (!normalized) return 'other';

  // Check for blocked status first (highest priority)
  if (normalized.includes('block')) return 'blocked';

  // Check for done statuses
  if (
    DONE_MATCHES.includes(normalized) ||
    normalized.endsWith(' done') ||
    normalized.startsWith('done ')
  ) {
    return 'done';
  }

  // Check for todo/backlog statuses
  if (TODO_MATCHES.includes(normalized)) {
    return 'todo';
  }

  // Check for in-progress statuses (exact matches)
  if (IN_PROGRESS_EXACT.includes(normalized)) {
    return 'in_progress';
  }

  // Check for in-progress statuses (partial matches)
  if (
    normalized.includes('progress') ||
    normalized.includes('review') ||
    normalized.includes('qa') ||
    normalized.includes('testing')
  ) {
    return 'in_progress';
  }

  return 'other';
}

/**
 * Check if a status represents a completed task.
 *
 * @param status - Raw status string
 * @returns True if status is categorized as 'done'
 */
export function isDoneStatus(status?: string | null): boolean {
  return categorizeStatus(status) === 'done';
}

/**
 * Check if a status represents an in-progress task.
 *
 * @param status - Raw status string
 * @returns True if status is categorized as 'in_progress'
 */
export function isInProgressStatus(status?: string | null): boolean {
  return categorizeStatus(status) === 'in_progress';
}

/**
 * Check if a status represents a blocked task.
 *
 * @param status - Raw status string
 * @returns True if status is categorized as 'blocked'
 */
export function isBlockedStatus(status?: string | null): boolean {
  return categorizeStatus(status) === 'blocked';
}

/** Task item interface for status calculations */
interface TaskWithStatus {
  status?: string | null;
}

/**
 * Hook for task status utilities.
 *
 * Provides memoized functions and computed values for task status handling.
 *
 * @example
 * ```tsx
 * const { categorize, isDone, calculateStats } = useTaskStatuses();
 *
 * // Categorize a single task
 * const bucket = categorize(task.status);
 *
 * // Check if task is done
 * if (isDone(task.status)) { ... }
 *
 * // Calculate stats from array of tasks
 * const stats = calculateStats(tasks);
 * ```
 */
export function useTaskStatuses() {
  // Memoize categorization function
  const categorize = useCallback(categorizeStatus, []);
  const normalize = useCallback(normalizeStatus, []);
  const isDone = useCallback(isDoneStatus, []);
  const isInProgress = useCallback(isInProgressStatus, []);
  const isBlocked = useCallback(isBlockedStatus, []);

  /**
   * Calculate status statistics from an array of tasks.
   */
  const calculateStats = useCallback(
    <T extends TaskWithStatus>(tasks: T[]): StatusStats => {
      const stats: StatusStats = {
        todo: 0,
        in_progress: 0,
        blocked: 0,
        done: 0,
        other: 0,
        total: tasks.length,
      };

      for (const task of tasks) {
        const bucket = categorizeStatus(task.status);
        stats[bucket]++;
      }

      return stats;
    },
    []
  );

  /**
   * Filter tasks by status bucket.
   */
  const filterByBucket = useCallback(
    <T extends TaskWithStatus>(tasks: T[], bucket: StatusBucket): T[] => {
      return tasks.filter((task) => categorizeStatus(task.status) === bucket);
    },
    []
  );

  /**
   * Get color for status bucket (MUI theme colors).
   */
  const getBucketColor = useCallback(
    (bucket: StatusBucket): 'success' | 'info' | 'warning' | 'error' | 'default' => {
      switch (bucket) {
        case 'done':
          return 'success';
        case 'in_progress':
          return 'info';
        case 'blocked':
          return 'error';
        case 'todo':
          return 'warning';
        default:
          return 'default';
      }
    },
    []
  );

  return {
    // Core functions
    normalize,
    categorize,
    isDone,
    isInProgress,
    isBlocked,

    // Utility functions
    calculateStats,
    filterByBucket,
    getBucketColor,

    // Constants for external use
    DONE_MATCHES,
    TODO_MATCHES,
    IN_PROGRESS_EXACT,
  };
}

export default useTaskStatuses;
