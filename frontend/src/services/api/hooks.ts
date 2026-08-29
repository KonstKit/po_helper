import { useQuery } from '@tanstack/react-query';

import { listProjects } from './index';
import type { Project } from './index';

/**
 * Server state for the projects list (roadmap E1).
 *
 * Single definition of the ['projects'] query: every page that needs the
 * list shares one cached request instead of re-fetching on each mount.
 */
export const PROJECTS_QUERY_KEY = ['projects'] as const;

export const useProjects = () =>
  useQuery<Project[], Error>({
    queryKey: PROJECTS_QUERY_KEY,
    queryFn: async () => {
      const resp = await listProjects();
      return resp.data;
    },
  });
