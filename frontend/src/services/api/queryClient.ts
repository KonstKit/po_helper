import { QueryClient } from '@tanstack/react-query';

/**
 * Shared server-state cache (roadmap E1).
 *
 * Replaces the hand-rolled per-page "load projects on mount" effects and
 * the Redux TTL cache: one query key = one request, deduplicated across
 * mounted pages, with a 60s stale window matching the old CACHE_TTL.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

/** Single source of truth for the projects list query identity. */
export const PROJECTS_QUERY_KEY = ['projects'] as const;
