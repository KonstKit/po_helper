/**
 * Sprint APIs - Sprint listing, burndown, quality, capacity, WIP status.
 */
import api, { CACHE_TTL } from './client';
import { storage } from '../../utils/storage';
import { deduplicateRequest } from '../../utils/apiOptimization';
import type { AxiosRequestConfig } from 'axios';
import type { BurndownResponse } from './types';
import { normalizeBurndownResponse } from './contractNormalization';

// =============================================================================
// Types
// =============================================================================

export interface Sprint {
  id?: number;
  sprint_id?: number;
  project_id?: number;
  jira_id?: string;
  name: string;
  state?: string;
  status?: string;
  start_date?: string;
  end_date?: string;
  goal?: string;
  commitment?: number;
  commitment_hours?: number;
  completed?: number;
  completed_hours?: number;
  scope_added_hours?: number;
  predictability_pct?: number;
  carryover_hours?: number;
}

export interface SprintsResponse {
  total: number;
  sprints: Sprint[];
  board_id?: number;
  error?: string;
}

export interface SprintQuality {
  total_tasks: number;
  dod_pct: number;
  bugs_by_priority: Record<string, number>;
  blockers: number;
}

export interface SprintWipStatus {
  total_active: number;
  limit_default: number;
  limit?: number;
  assignees: Array<{
    assignee: string;
    active_tasks: number;
    limit: number;
    wip_exceeded: boolean;
  }>;
  error?: string;
}

export interface SprintCapacity {
  sprint_id: number;
  weeks: number;
  capacity_hours_per_person: number;
  total_planned_hours: number;
  assignees: Array<{
    assignee: string;
    planned_hours: number;
    capacity_hours: number;
    utilization_pct: number;
  }>;
  error?: string;
}

export interface Board {
  id: number;
  name: string;
  type?: string;
}

export interface BoardsResponse {
  count: number;
  boards: Board[];
}

// =============================================================================
// Sprint Listing
// =============================================================================

export const listSprints = async (
  opts?: { projectId?: number },
  config?: AxiosRequestConfig
): Promise<Sprint[]> => {
  if (!opts?.projectId) {
    console.debug('[API] No project_id provided for sprints, returning empty array');
    return [];
  }

  const cacheKey = `sprints_project_${opts.projectId}`;

  const cached = storage.get<Sprint[]>(cacheKey);
  if (cached !== null) {
    console.debug('[API] Using cached sprints');
    return cached;
  }

  return deduplicateRequest(cacheKey, async () => {
    try {
      const res = await api.get(`/v1/analytics/projects/${opts.projectId}/sprints`, {
        params: { limit: 50 },
        timeout: 10000,
        ...config,
      });
      const sprints = res.data.sprints || [];
      storage.set(cacheKey, sprints, { ttl: CACHE_TTL });
      return sprints;
    } catch (error: unknown) {
      const err = error as { message?: string };
      console.error('[API] Sprint fetch failed:', err.message);
      const stale = storage.get<Sprint[]>(cacheKey, { ignoreExpiry: true });
      if (stale) {
        console.debug('[API] Returning stale cached sprints due to error');
        return stale;
      }
      return [];
    }
  });
};

export const getProjectSprints = async (
  projectId: number,
  limit = 10,
  boardId?: number
): Promise<SprintsResponse> => {
  const params: Record<string, unknown> = { limit };
  if (boardId !== undefined) params.board_id = boardId;

  try {
    const { data } = await api.get(`/v1/analytics/projects/${projectId}/sprints`, {
      params,
      timeout: 10000,
    });
    return data as SprintsResponse;
  } catch (error: unknown) {
    const err = error as { code?: string; message?: string };
    const errorType =
      err.code === 'ECONNABORTED' || err.message?.includes('timeout')
        ? 'timeout'
        : 'error';
    console.warn(`Sprint fetch failed (${errorType}):`, err.message);
    return { total: 0, sprints: [], board_id: boardId, error: errorType };
  }
};

// =============================================================================
// Sprint Analytics
// =============================================================================

export const getSprintBurndown = async (
  sprintId: number,
  opts?: { signal?: AbortSignal }
): Promise<BurndownResponse> => {
  const { data } = await api.get(`/v1/analytics/sprints/${sprintId}/burndown`, {
    signal: opts?.signal,
  });
  return normalizeBurndownResponse(data);
};

export const getSprintQuality = async (sprintId: number): Promise<SprintQuality> => {
  const { data } = await api.get(`/v1/analytics/sprints/${sprintId}/quality`);
  return data as SprintQuality;
};

// =============================================================================
// WIP Status
// =============================================================================

export const getSprintWipStatus = async (
  sprintId: number,
  opts?: { signal?: AbortSignal }
): Promise<SprintWipStatus> => {
  const cacheKey = `wip_status_${sprintId}`;

  const cached = storage.get<SprintWipStatus>(cacheKey);
  if (cached !== null) {
    console.debug('[API] Using cached WIP status');
    return cached;
  }

  const { data } = await api.get(`/v1/analytics/sprints/${sprintId}/wip-status`, {
    timeout: 30000,
    signal: opts?.signal,
  });

  storage.set(cacheKey, data, { ttl: CACHE_TTL });
  return data as SprintWipStatus;
};

// =============================================================================
// Sprint Capacity
// =============================================================================

export const getSprintCapacity = async (sprintId: number): Promise<SprintCapacity> => {
  const cacheKey = `capacity_${sprintId}`;

  const cached = storage.get<SprintCapacity>(cacheKey);
  if (cached !== null) {
    console.debug('[API] Using cached capacity');
    return cached;
  }

  const { data } = await api.get(`/v1/analytics/sprints/${sprintId}/capacity`, {
    timeout: 30000,
  });

  storage.set(cacheKey, data, { ttl: CACHE_TTL });
  return data as SprintCapacity;
};

// =============================================================================
// Boards
// =============================================================================

export const getBoardsForProject = async (jiraKey: string): Promise<BoardsResponse> => {
  const { data } = await api.get(`/v1/jira/projects/${jiraKey}/boards`);
  return data as BoardsResponse;
};
