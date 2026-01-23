/**
 * Task APIs - Task listing and operations.
 */
import api, { CACHE_TTL, withRetry } from './client';
import { AxiosRequestConfig } from 'axios';
import { storage } from '../../utils/storage';
import { deduplicateRequest, makeCacheKey } from '../../utils/apiOptimization';
import type { TaskItem, PaginationParams, PaginatedResponse, PaginationMeta } from './types';
import { DEFAULT_PAGE_SIZE } from './types';

/**
 * Helper to extract data array from backend response.
 * Handles both paginated { data: [...], meta: {...} } and legacy array responses.
 */
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const isTaskItem = (value: unknown): value is TaskItem =>
  isRecord(value) &&
  typeof value.id === 'number' &&
  typeof value.key === 'string' &&
  typeof value.jira_id === 'string' &&
  typeof value.summary === 'string' &&
  typeof value.status === 'string';

function extractTasksArray(response: unknown): TaskItem[] {
  if (Array.isArray(response)) {
    return response.filter(isTaskItem);
  }
  if (isRecord(response) && Array.isArray(response.data)) {
    return response.data.filter(isTaskItem);
  }
  return [];
}

/**
 * Helper to extract pagination metadata from backend response.
 */
function extractPaginationMeta(response: unknown, skip: number, limit: number): PaginationMeta {
  if (isRecord(response) && isRecord(response.meta)) {
    const meta = response.meta;
    if (
      typeof meta.total === 'number' &&
      typeof meta.page === 'number' &&
      typeof meta.per_page === 'number' &&
      typeof meta.total_pages === 'number' &&
      typeof meta.has_next === 'boolean' &&
      typeof meta.has_prev === 'boolean'
    ) {
      return {
        total: meta.total,
        page: meta.page,
        per_page: meta.per_page,
        total_pages: meta.total_pages,
        has_next: meta.has_next,
        has_prev: meta.has_prev,
      };
    }
  }
  // Fallback: construct meta from available data
  const data = extractTasksArray(response);
  const total = data.length;
  const page = Math.floor(skip / limit) + 1;
  const totalPages = Math.max(1, Math.ceil(total / limit));
  return {
    total,
    page,
    per_page: limit,
    total_pages: totalPages,
    has_next: page < totalPages,
    has_prev: page > 1,
  };
}

/**
 * List tasks by project with pagination support.
 * Returns paginated response with metadata for server-side pagination.
 */
export const listTasksByProjectPaginated = async (
  projectId: number,
  pagination?: PaginationParams,
  config?: AxiosRequestConfig,
): Promise<PaginatedResponse<TaskItem>> => {
  const skip = pagination?.skip ?? 0;
  const limit = pagination?.limit ?? DEFAULT_PAGE_SIZE;

  const { data: response } = await api.get(`/v1/tasks/`, {
    params: {
      project_id: projectId,
      skip,
      limit,
    },
    ...(config || {}),
  });

  return {
    data: extractTasksArray(response),
    meta: extractPaginationMeta(response, skip, limit),
  };
};

/**
 * List tasks by project (legacy - returns array for backward compatibility).
 * @deprecated Use listTasksByProjectPaginated for server-side pagination
 */
export const listTasksByProject = async (
  projectId: number,
  pagination?: PaginationParams,
  config?: AxiosRequestConfig,
): Promise<TaskItem[]> => {
  const { data } = await listTasksByProjectPaginated(projectId, pagination, config);
  return data;
};

/**
 * List tasks with filters and pagination support.
 * Returns paginated response with metadata for server-side pagination.
 */
export const listTasksPaginated = async (
  filters?: {
    status?: string;
    assignee?: string;
    projectId?: number;
    skip?: number;
    limit?: number;
  },
  config?: AxiosRequestConfig,
): Promise<PaginatedResponse<TaskItem>> => {
  const skip = filters?.skip ?? 0;
  const limit = filters?.limit ?? DEFAULT_PAGE_SIZE;
  const cacheKey = makeCacheKey('tasks_paginated', filters);

  // Check cache
  const cached = storage.get<PaginatedResponse<TaskItem>>(cacheKey);
  if (cached !== null) {
    console.debug("[API] Using cached paginated tasks");
    return cached;
  }

  return deduplicateRequest(cacheKey, async () => {
    const params: Record<string, unknown> = {};
    if (filters?.status) params.status = filters.status;
    if (filters?.assignee) params.assignee = filters.assignee;
    if (filters?.projectId) params.project_id = filters.projectId;
    params.skip = skip;
    params.limit = limit;

    const res = await withRetry(
      () => api.get("/v1/tasks/", { params, timeout: 60000, ...(config || {}) }),
      { retries: 2, baseDelayMs: 700, maxDelayMs: 6000 },
    );

    const result: PaginatedResponse<TaskItem> = {
      data: extractTasksArray(res.data),
      meta: extractPaginationMeta(res.data, skip, limit),
    };

    // Cache only if reasonable size
    if (result.data.length < 2000) {
      storage.set(cacheKey, result, { ttl: CACHE_TTL });
    }

    return result;
  });
};

/**
 * List tasks with filters (legacy - returns array for backward compatibility).
 * @deprecated Use listTasksPaginated for server-side pagination
 */
export const listTasks = async (
  filters?: {
    status?: string;
    assignee?: string;
    projectId?: number;
    skip?: number;
    limit?: number;
  },
  config?: AxiosRequestConfig,
): Promise<TaskItem[]> => {
  const { data } = await listTasksPaginated(filters, config);
  return data;
};

export const getTask = async (taskId: number): Promise<TaskItem> => {
  const { data } = await api.get(`/v1/tasks/${taskId}`);
  return data;
};

export const clearTasksCache = () => {
  // Clear all task-related cache entries
  storage.clearAll();
};

// =============================================================================
// Task Business Value
// =============================================================================

export const setTaskBusinessValue = async (
  taskId: number,
  opts: { businessValue?: number; valueDelivered?: boolean }
): Promise<TaskItem> => {
  const params: Record<string, unknown> = {};
  if (opts.businessValue !== undefined) params.business_value = opts.businessValue;
  if (opts.valueDelivered !== undefined) params.value_delivered = String(opts.valueDelivered);

  const { data } = await api.post(`/v1/tasks/${taskId}/business-value`, undefined, { params });
  return data as TaskItem;
};
