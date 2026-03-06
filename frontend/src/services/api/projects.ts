/**
 * Project APIs - Project CRUD, PR metrics, team analytics.
 */
import api, { CACHE_TTL } from './client';
import type { AxiosRequestConfig } from 'axios';
import { storage } from '../../utils/storage';
import { deduplicateRequest } from '../../utils/apiOptimization';
import type {
  Project,
  ProjectRepositoryLink,
  BindRepositoryPayload,
  PaginationParams,
  PaginatedResponse,
} from './types';
import { DEFAULT_PAGE_SIZE } from './types';
import { normalizePaginatedResponse } from './pagination';

// =============================================================================
// Cache Helpers
// =============================================================================

const PROJECT_LIST_CACHE_KEY = "projects_list";
const projectCacheKey = (id: number) => `project_${id}`;

const invalidateProjectCache = (projectId?: number) => {
  storage.remove(PROJECT_LIST_CACHE_KEY);
  if (typeof projectId === "number") {
    storage.remove(projectCacheKey(projectId));
  }
};

// =============================================================================
// Project CRUD
// =============================================================================

export const listProjects = async (pagination?: PaginationParams): Promise<PaginatedResponse<Project>> => {
  // Use cache key that includes pagination params
  const cacheKey = pagination?.skip || pagination?.limit
    ? `${PROJECT_LIST_CACHE_KEY}_${pagination.skip ?? 0}_${pagination.limit ?? DEFAULT_PAGE_SIZE}`
    : PROJECT_LIST_CACHE_KEY;

  const cached = storage.get<PaginatedResponse<Project>>(cacheKey);
  if (cached !== null) {
    return cached;
  }

  return deduplicateRequest(cacheKey, async () => {
    const skip = pagination?.skip ?? 0;
    const limit = pagination?.limit ?? DEFAULT_PAGE_SIZE;
    const params: Record<string, unknown> = { skip, limit };
    const { data } = await api.get("/v1/projects/", { params });
    const response = normalizePaginatedResponse<Project>(data, { skip, limit });
    storage.set(cacheKey, response, { ttl: CACHE_TTL * 2 });
    return response;
  });
};

const isValidProjectDetail = (value: unknown): value is Project => {
  return (
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    typeof (value as Project).id === "number" &&
    typeof (value as Project).jira_key === "string"
  );
};

const normalizeProjectDetail = (payload: unknown): Project => {
  if (isValidProjectDetail(payload)) {
    return payload;
  }
  if (Array.isArray(payload)) {
    const candidate = payload.find((item) => isValidProjectDetail(item));
    if (candidate) {
      return candidate;
    }
  }
  if (payload && typeof payload === "object") {
    for (const key of ["data", "project", "result"]) {
      if (Object.prototype.hasOwnProperty.call(payload, key)) {
        try {
          return normalizeProjectDetail((payload as Record<string, unknown>)[key]);
        } catch {
          // continue searching nested structures
        }
      }
    }
  }
  throw new Error("Unexpected /v1/projects/{id} response shape");
};

export const getProject = async (
  id: number,
  config?: AxiosRequestConfig,
  opts?: { skipCache?: boolean }
): Promise<Project> => {
  const cacheKey = projectCacheKey(id);
  if (!opts?.skipCache) {
    const cached = storage.get<Project>(cacheKey);
    if (cached !== null) {
      return cached;
    }
  }

  return deduplicateRequest(cacheKey, async () => {
    const { data } = await api.get(`/v1/projects/${id}`, config);
    const project = normalizeProjectDetail(data);
    storage.set(cacheKey, project, { ttl: CACHE_TTL });
    return project;
  });
};

export const createProject = async (payload: {
  jira_key: string;
  name: string;
  description?: string;
  status?: string;
  start_date?: string;
  end_date?: string;
  owner_id?: number;
}): Promise<Project> => {
  const { data } = await api.post("/v1/projects/", payload);
  invalidateProjectCache();
  return data;
};

export const updateProject = async (
  id: number,
  payload: Partial<Omit<Project, 'id' | 'created_at' | 'updated_at'>>
): Promise<Project> => {
  const { data } = await api.patch(`/v1/projects/${id}`, payload);
  invalidateProjectCache(id);
  return data;
};

export const deleteProject = async (id: number): Promise<{ message: string }> => {
  const { data } = await api.delete(`/v1/projects/${id}`);
  invalidateProjectCache(id);
  return data;
};

export const purgeProject = async (id: number): Promise<{ message: string }> => {
  const { data } = await api.delete(`/v1/projects/${id}/purge`);
  invalidateProjectCache(id);
  return data;
};

// =============================================================================
// Project Repositories
// =============================================================================

export const getProjectRepositories = async (projectId: number): Promise<ProjectRepositoryLink[]> => {
  const { data } = await api.get(`/v1/projects/${projectId}/repositories`);
  return data as ProjectRepositoryLink[];
};

export const bindRepositoryToProject = async (
  projectId: number,
  payload: BindRepositoryPayload,
): Promise<ProjectRepositoryLink> => {
  const body: Record<string, unknown> = {
    project_id: projectId,
    is_primary: payload.isPrimary ?? true,
  };

  const url = payload.repositoryUrl?.trim();
  const slug = payload.repoSlug?.trim();

  if (url) {
    body.repository_url = url;
  }

  if (!url && slug) {
    body.repo_slug = slug;
  }

  if (!url && payload.provider) {
    body.provider = payload.provider;
  }

  if (!body.repository_url && !(body.repo_slug && body.provider)) {
    throw new Error('Provide a repository URL or select provider and repository slug.');
  }

  const { data } = await api.post(`/v1/projects/${projectId}/repositories`, body);
  return data as ProjectRepositoryLink;
};

export const unbindRepositoryFromProject = async (projectId: number, repositoryId: number): Promise<void> => {
  await api.delete(`/v1/projects/${projectId}/repositories/${repositoryId}`);
};

export const setPrimaryRepository = async (projectId: number, repositoryId: number): Promise<void> => {
  await api.put(`/v1/projects/${projectId}/repositories/${repositoryId}/primary`);
};

// =============================================================================
// JIRA Sync
// =============================================================================

export interface JiraProjectSyncResponse {
  message: string;
  status?: string;
  project_id?: number;
  task_id?: string | number;
  sync_task_id?: number;
  method?: string;
  sync_task_started_at?: string | null;
  tasks_synced?: number;
  sprints_synced?: number;
}

export const syncJiraProject = async (
  projectKey: string,
  config?: AxiosRequestConfig
): Promise<JiraProjectSyncResponse> => {
  // Clear cache when syncing
  storage.clearAll();
  const { data } = await api.post(`/v1/jira/projects/${projectKey}/sync`, undefined, config);
  return data as JiraProjectSyncResponse;
};
