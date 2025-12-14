import axios, { AxiosRequestConfig } from "axios";

import { storage } from "../utils/storage";

const api = axios.create({
  baseURL: "/api",

  timeout: 15000, // 15 seconds default timeout - reduced from 30s to fail faster
});

export const API_BASE_URL = "/api/v1";

api.interceptors.request.use((config) => {
  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;

  if (token) {
    config.headers = config.headers || {};

    config.headers.Authorization = `Bearer ${token}`;
  }

  return config;
});

// Add response interceptor for better error handling

api.interceptors.response.use(
  (response) => response,

  (error) => {
    // Check if backend is unreachable

    if (error.code === "ECONNABORTED" || error.message?.includes("timeout")) {
      console.error("Backend timeout - server may be unresponsive");

      // Store error state for UI notification

      if (typeof window !== 'undefined') window.dispatchEvent(
        new CustomEvent("backend-error", {
          detail: {
            type: "timeout",
            message: "Backend server is not responding",
          },
        }),
      );
    } else if (!error.response) {
      console.error("Backend unreachable - network error");

      if (typeof window !== 'undefined') window.dispatchEvent(
        new CustomEvent("backend-error", {
          detail: {
            type: "network",
            message: "Cannot connect to backend server",
          },
        }),
      );
    }

    if (error.response?.status === 401) {
      if (typeof window !== 'undefined') {
        localStorage.removeItem('token');
        window.dispatchEvent(
          new CustomEvent('auth-error', {
            detail: {
              type: 'unauthorized',
              message: 'Session expired. Please sign in again.',
            },
          }),
        );
      }
    }

    return Promise.reject(error);
  },
);

export interface User {
  id: number;

  email: string;

  username: string;

  full_name?: string;

  is_active: boolean;

  is_superuser: boolean;

  created_at?: string;

  updated_at?: string | null;
}

export const getCurrentUser = async (): Promise<User> => {
  const { data } = await api.get("/v1/users/me");

  return data;
};

export const updateCurrentUser = async (
  payload: Partial<Pick<User, "username" | "full_name">>,
): Promise<User> => {
  const { data } = await api.patch("/v1/users/me", payload);

  return data;
};

export const changePassword = async (payload: {
  current_password: string;
  new_password: string;
}) => {
  const { data } = await api.post("/v1/users/me/password", payload);

  return data;
};

export default api;

// ---- Generic retry helper (exponential backoff with jitter) ----

export async function withRetry<T>(
  fn: () => Promise<T>,
  opts?: { retries?: number; baseDelayMs?: number; maxDelayMs?: number },
): Promise<T> {
  const retries = opts?.retries ?? 2;

  const base = opts?.baseDelayMs ?? 300;

  const maxDelay = opts?.maxDelayMs ?? 4000;

  let attempt = 0;

  // eslint-disable-next-line no-constant-condition

  while (true) {
    try {
      return await fn();
    } catch (err: any) {
      // Do not retry canceled/aborted

      if (err?.code === "ERR_CANCELED") throw err;

      const status = err?.response?.status as number | undefined;

      const retriable =
        err?.code === "ECONNABORTED" ||
        err?.message?.includes("timeout") ||
        [429, 502, 503, 504].includes(status || 0);

      if (!retriable || attempt >= retries) throw err;

      const delay =
        Math.min(maxDelay, base * Math.pow(2, attempt)) *
        (0.8 + Math.random() * 0.4);

      await new Promise((res) => setTimeout(res, delay));

      attempt++;
    }
  }
}

// Track active requests to prevent duplicates in React StrictMode

const activeRequests = new Map<string, Promise<any>>();

const PROJECT_LIST_CACHE_KEY = "projects_list";
const projectCacheKey = (id: number) => `project_${id}`;

const invalidateProjectCache = (projectId?: number) => {
  storage.remove(PROJECT_LIST_CACHE_KEY);
  if (typeof projectId === "number") {
    storage.remove(projectCacheKey(projectId));
  }
};

// -------- Settings (Integrations) --------

export interface IntegrationSettings {
  kind: "jira" | "confluence";

  base_url?: string | null;

  email?: string | null;

  api_token?: string | null;

  has_token?: boolean;

  has_webhook_secret?: boolean;
}

export const getJiraSettings = async (): Promise<IntegrationSettings> => {
  const { data } = await api.get("/v1/settings/jira");

  return data;
};

export const putJiraSettings = async (payload: {
  base_url?: string;
  email?: string;
  api_token?: string;
  use_pat?: boolean;
}): Promise<IntegrationSettings> => {
  const body: Record<string, unknown> = {};

  if (payload.base_url !== undefined) body.base_url = payload.base_url;
  if (payload.email !== undefined) body.email = payload.email;
  if (payload.api_token !== undefined) body.api_token = payload.api_token;
  if (payload.use_pat !== undefined) body.use_pat = payload.use_pat;

  const { data } = await api.put("/v1/settings/jira", body);

  return data;
};

export const getConfluenceSettings = async (): Promise<IntegrationSettings> => {
  const { data } = await api.get("/v1/settings/confluence");

  return data;
};

export const putConfluenceSettings = async (payload: {
  base_url?: string;
  email?: string;
  api_token?: string;
}): Promise<IntegrationSettings> => {
  const { data } = await api.put("/v1/settings/confluence", payload);

  return data;
};

export const testJiraConnection = async (
  payload: { base_url: string; email?: string; api_token: string; use_pat?: boolean },
  save = true,
) => {
  const usePat = typeof payload.use_pat === 'boolean' ? payload.use_pat : !payload.email;
  const q: Record<string, string> = {
    base_url: payload.base_url,
    api_token: payload.api_token,
    use_pat: String(usePat),
  };

  if (!usePat && payload.email) {
    q.email = payload.email;
  }

  if (save) q.save = "true";

  const params = new URLSearchParams(q).toString();

  const { data } = await api.post(`/v1/jira/connect?${params}`);

  return data;
};

export const testConfluenceConnection = async (
  payload: { base_url: string; email?: string; api_token: string },
  save = true,
) => {
  const q: any = { base_url: payload.base_url, api_token: payload.api_token };

  if (payload.email) q.email = payload.email;

  if (save) q.save = "true";

  const params = new URLSearchParams(q).toString();

  const { data } = await api.post(`/v1/confluence/connect?${params}`);

  return data as {
    status: string;
    configured: boolean;
    base_url?: string | null;
    auth_mode?: string;
  };
};

export interface GithubTestResponse {
  status: string;
  base_url: string;
  message?: string;
  login?: string | null;
  name?: string | null;
  plan?: string | null;
  scopes?: string | null;
  rate_limit_remaining?: string | null;
  rate_limit_reset?: string | null;
}

export const testGithubConnection = async (payload: {
  base_url?: string;
  api_token?: string;
}): Promise<GithubTestResponse> => {
  const { data } = await api.post("/v1/settings/github/test", payload);
  return data as GithubTestResponse;
};

export const testGitlabConnection = async (payload: {
  base_url?: string;
  api_token?: string;
  webhook_secret?: string;
}): Promise<any> => {
  const { data } = await api.post("/v1/settings/gitlab/test", payload);

  return data;
};

export const testTestrailConnection = async (payload: {
  base_url?: string;
  email?: string;
  api_token?: string;
}): Promise<any> => {
  const { data } = await api.post("/v1/settings/testrail/test", payload);

  return data;
};

// -------- Health / Integrations --------

// Simple cache to prevent API spam

let _integrationStatusCache: any = null;

let _integrationStatusCacheTime = 0;

const CACHE_TTL = 60000; // 1 minute for main cache

export const clearIntegrationStatusCache = () => {
  _integrationStatusCache = null;

  _integrationStatusCacheTime = 0;
};

export const getIntegrationsStatus = async () => {
  const now = Date.now();

  if (_integrationStatusCache && now - _integrationStatusCacheTime < 5000) {
    // 5 second cache for integration status

    return _integrationStatusCache;
  }

  const { data } = await api.get("/v1/health/integrations");

  _integrationStatusCache = data;

  _integrationStatusCacheTime = now;

  return data as {
    jira: {
      configured: boolean;
      base_url?: string | null;
      auth_mode?: string;
      has_token?: boolean;
    };

    confluence: {
      configured: boolean;
      base_url?: string | null;
      auth_mode?: string;
      has_token?: boolean;
    };

    github: { configured: boolean; has_token?: boolean };

    gitlab: { configured: boolean; has_token?: boolean };

    testrail: { configured: boolean; has_token?: boolean };
  };
};

// -------- New: GitHub/GitLab/TestRail settings --------

export const getGithubSettings = async (): Promise<IntegrationSettings> => {
  const { data } = await api.get("/v1/settings/github");

  return data;
};

export const putGithubSettings = async (payload: {
  base_url?: string;
  api_token?: string;
  webhook_secret?: string;
}): Promise<IntegrationSettings> => {
  const { data } = await api.put("/v1/settings/github", payload);

  return data;
};


export const listGitlabProjects = async (opts?: {
  groupId?: number;
  groupPath?: string;
  search?: string;
  includeSubgroups?: boolean;
  page?: number;
  perPage?: number;
}): Promise<GitlabProjectsResponse> => {
  const params: Record<string, any> = {};

  if (typeof opts?.groupId === 'number') params.group_id = opts.groupId;
  if (opts?.groupPath) params.group_path = opts.groupPath;
  if (opts?.search) params.search = opts.search;
  if (opts?.includeSubgroups !== undefined) params.include_subgroups = opts.includeSubgroups ? 'true' : 'false';
  if (typeof opts?.page === 'number') params.page = opts.page;
  if (typeof opts?.perPage === 'number') params.per_page = opts.perPage;

  const { data } = await api.get('/v1/gitlab/projects', { params });
  return data as GitlabProjectsResponse;
};
export const getGitlabSettings = async (): Promise<IntegrationSettings> => {
  const { data } = await api.get("/v1/settings/gitlab");

  return data;
};

export const putGitlabSettings = async (payload: {
  base_url?: string;
  api_token?: string;
  webhook_secret?: string;
}): Promise<IntegrationSettings> => {
  const { data } = await api.put("/v1/settings/gitlab", payload);

  return data;
};

export const getTestrailSettings = async (): Promise<IntegrationSettings> => {
  const { data } = await api.get("/v1/settings/testrail");

  return data;
};

export const putTestrailSettings = async (payload: {
  base_url?: string;
  email?: string;
  api_token?: string;
}): Promise<IntegrationSettings> => {
  const { data } = await api.put("/v1/settings/testrail", payload);

  return data;
};

// -------- Confluence content helpers --------

export const listConfluenceSpaces = async (q?: string, limit = 50) => {
  const params: any = { limit };

  if (q) params.q = q;

  const { data } = await api.get("/v1/confluence/spaces", { params });

  return data as {
    count: number;
    results: Array<{ id: string; key: string; name: string; url?: string }>;
  };
};

export const listConfluencePages = async (opts?: {
  space?: string;
  q?: string;
  limit?: number;
  start?: number;
}) => {
  const params: any = {};

  if (opts?.space) params.space = opts.space;

  if (opts?.q) params.q = opts.q;

  params.limit = opts?.limit ?? 50;

  if (opts?.start !== undefined) params.start = opts.start;

  const { data } = await api.get("/v1/confluence/pages", { params });

  return data as {
    count: number;
    results: Array<{
      id: string;
      title: string;
      space?: string;
      url?: string;
      version?: number;
      last_updated?: string;
    }>;
  };
};

export const listConfluencePagesLocal = async (opts?: {
  space?: string;
  q?: string;
  limit?: number;
  offset?: number;
}) => {
  const params: any = {};

  if (opts?.space) params.space = opts.space;

  if (opts?.q) params.q = opts.q;

  params.limit = opts?.limit ?? 50;

  if (opts?.offset !== undefined) params.offset = opts.offset;

  const { data } = await api.get("/v1/confluence/local/pages", { params });

  return data as {
    count: number;
    results: Array<{
      id: string;
      title: string;
      space?: string;
      url?: string;
      version?: number;
      last_updated?: string;
    }>;
  };
};

export const getConfluencePage = async (pageId: string) => {
  const { data } = await api.get(`/v1/confluence/pages/${pageId}`);

  return data as {
    id: string;
    title: string;
    url?: string;
    html?: string;
    labels?: any;
    version?: number;
  };
};

export const getPrdRequirements = async (pageId: string) => {
  const { data } = await api.get(`/v1/confluence/prd/${pageId}/requirements`);

  return data as {
    count: number;
    requirements: Array<{ id: string; description: string; priority: string }>;
  };
};

export const syncConfluence = async (opts?: {
  space?: string;
  q?: string;
  limit?: number;
  start?: number;
  full?: boolean;
}) => {
  const params: any = {};

  if (opts?.space) params.space = opts.space;

  if (opts?.q) params.q = opts.q;

  params.limit = opts?.limit ?? 50;

  if (opts?.full) params.full = "true";

  if (opts?.start !== undefined) params.start = opts.start;

  const { data } = await api.post("/v1/confluence/sync", undefined, {
    params,
    timeout: 120000,
  });

  return data as { synced: number; created: number; updated: number };
};

export const getSpaceTree = async (
  spaceKey: string,
  limit = 100,
  max_pages?: number,
) => {
  const params = new URLSearchParams({ limit: String(limit) });

  if (typeof max_pages === "number") params.set("max_pages", String(max_pages));

  const { data } = await api.get(
    `/v1/confluence/spaces/${encodeURIComponent(spaceKey)}/tree?${params}`,
  );

  return data as { count: number; tree: Array<any> };
};

export const syncSubtree = async (pageId: string, limit = 50) => {
  const params = new URLSearchParams({ limit: String(limit) });

  const { data } = await api.post(
    `/v1/confluence/subtree/${encodeURIComponent(pageId)}/sync?${params.toString()}`,
    undefined,
    { timeout: 120000 },
  );

  return data as { synced: number; created: number; updated: number };
};

export const getADR = async (pageId: string) => {
  const { data } = await api.get(`/v1/confluence/adr/${pageId}`);

  return data as {
    id: string;
    title: string;
    status?: string | null;
    context?: string;
    decision?: string;
    consequences?: string;
    alternatives?: string;
  };
};

export const getResearch = async (pageId: string) => {
  const { data } = await api.get(`/v1/confluence/research/${pageId}`);

  return data as {
    id: string;
    title: string;
    insights: Record<string, string[]>;
  };
};

// -------- Projects --------

export interface Project {
  id: number;

  jira_key: string;

  name: string;

  description?: string;

  status: string;

  budget?: number;

  start_date?: string | null;

  end_date?: string | null;

  created_at?: string;

  updated_at?: string | null;

  // stats (when returned by detail)

  total_tasks?: number;

  completed_tasks?: number;

  in_progress_tasks?: number;

  total_estimate_hours?: number;

  total_spent_hours?: number;

  completion_percentage?: number;
}

const isValidProjectDetail = (value: any): value is Project => {
  return (
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    typeof (value as any).id === "number" &&
    typeof (value as any).jira_key === "string"
  );
};

const normalizeProjectDetail = (payload: any): Project => {
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
          return normalizeProjectDetail((payload as any)[key]);
        } catch {
          // continue searching nested structures
        }
      }
    }
  }
  throw new Error("Unexpected /v1/projects/{id} response shape");
};

export interface PRSampleSummary {
  id?: number;

  number?: number;

  title?: string | null;

  state?: string | null;

  cycle_time_hours?: number | null;

  lead_time_hours?: number | null;

  rework_count?: number | null;

  opened_at?: string | null;

  merged_at?: string | null;

  closed_at?: string | null;
}

export interface PRMetricsSummary {
  total: number;

  avg_cycle_time_hours: number;

  avg_lead_time_hours: number;

  avg_time_to_first_review_hours: number;

  cycle_samples: number;

  lead_samples: number;

  first_review_samples: number;

  rework_rate: number;

  by_state: Record<string, number>;

  histogram: {
    bins: string[];

    cycle_counts: number[];

    lead_counts: number[];
  };

  sample_prs?: PRSampleSummary[];

  since_days?: number | null;

  cache_hit?: boolean;

  recent_throughput: {
    days: number;

    merged: number;
  };
}

export interface TraceabilityTypeStats {
  total: number;

  linked: number;

  unlinked: number;

  link_count: number;

  coverage_pct: number;

  avg_links_per_artifact: number;

  link_type_counts?: Record<string, number>;

  link_type_artifact_counts?: Record<string, number>;
}

export interface TraceabilityMatrixSummary {
  total: number;

  by_type: Record<string, number>;

  per_type?: Record<string, TraceabilityTypeStats>;

  coverage: {
    linked_artifacts: number;

    coverage_pct: number;
  };
}

export interface GitImportRepoStats {
  repository_id: number;
  provider: RepositoryProvider;
  repo_slug: string;
  default_branch?: string | null;
  commits?: {
    created?: number;
    updated?: number;
    links_created?: number;
    suggestions?: Array<Record<string, any>>;
    error?: string;
  };
  pull_requests?: {
    processed?: number;
    links_created?: number;
    suggestions?: Array<Record<string, any>>;
    error?: string;
  };
  error?: string;
}


export interface GitlabProjectSummary {
  id: number;
  name: string;
  path: string;
  path_with_namespace: string;
  description?: string | null;
  default_branch?: string | null;
  visibility?: string | null;
  ssh_url_to_repo?: string | null;
  http_url_to_repo?: string | null;
  web_url?: string | null;
  last_activity_at?: string | null;
  namespace?: string | null;
}

export interface GitlabProjectsResponse {
  count: number;
  projects: GitlabProjectSummary[];
  pagination: {
    next_page?: string | null;
    prev_page?: string | null;
    total_pages?: string | null;
    total_items?: string | null;
  };
  source: string;
}
export interface GitImportSummary {
  project_id?: number;
  repositories?: GitImportRepoStats[];
  error?: string;
}

export interface TraceabilityBackfillResult {
  status: string;

  created: number;

  updated: number;

  git?: GitImportSummary;
}

export interface TeamHealthMetrics {
  total: number;

  done: number;

  in_progress: number;

  backlog: number;

  blockers: number;

  overdue: number;

  completion_rate: number;

  estimate_hours: number;

  spent_hours: number;

  avg_cycle_time_hours: number | null;

  median_cycle_time_hours: number | null;

  cycle_samples: number;

  error?: string;
}

export const getTeamMembersActivity = async (projectId: number) => {
  const { data } = await api.get(`/v1/analytics/projects/${projectId}/team-members`);
  return data;
};

export const getProjectTeamHealth = async (
  projectId: number,
): Promise<TeamHealthMetrics> => {
  const cacheKey = `team_health_${projectId}`;

  const requestKey = `GET:/v1/analytics/projects/${projectId}/team-health`;

  const cached = storage.get<TeamHealthMetrics>(cacheKey);

  if (cached !== null) {
    console.log("[API] Using cached team health");

    return cached;
  }

  if (activeRequests.has(requestKey)) {
    return activeRequests.get(requestKey)!;
  }

  const promise: Promise<TeamHealthMetrics> = withRetry(
    () =>
      api.get(`/v1/analytics/projects/${projectId}/team-health`, {
        timeout: 30000,
      }),

    { retries: 1, baseDelayMs: 400, maxDelayMs: 2500 },
  )
    .then((res) => {
      const payload = res.data as TeamHealthMetrics;

      storage.set(cacheKey, payload, { ttl: CACHE_TTL });

      return payload;
    })

    .finally(() => {
      activeRequests.delete(requestKey);
    });

  activeRequests.set(requestKey, promise);

  return promise;
};

// -------- Analytics: Budget Hours / Value Metrics / WIP --------

export const getProjectBudgetHours = async (projectId: number) => {
  const cacheKey = `budget_hours_${projectId}`;

  const cached = storage.get(cacheKey);

  if (cached !== null) {
    console.log("[API] Using cached budget hours");

    return cached;
  }

  const { data } = await api.get(
    `/v1/analytics/projects/${projectId}/budget-hours`,
    { timeout: 30000 },
  );

  storage.set(cacheKey, data, { ttl: CACHE_TTL * 2 }); // Cache for 2 minutes

  return data as {
    total_estimate_hours: number;

    total_spent_hours: number;

    remaining_hours: number;

    overrun: boolean;

    overrun_hours: number;

    top_overruns: { key: string; overrun_hours: number }[];
  };
};

export const getProjectValueMetrics = async (projectId: number) => {
  const cacheKey = `value_metrics_${projectId}`;

  const cached = storage.get(cacheKey);

  if (cached !== null) {
    console.log("[API] Using cached value metrics");

    return cached;
  }

  const { data } = await api.get(
    `/v1/analytics/projects/${projectId}/value-metrics`,
    { timeout: 30000 },
  );

  storage.set(cacheKey, data, { ttl: CACHE_TTL * 2 }); // Cache for 2 minutes

  return data as {
    value_delivered: number;
    total_spent_hours: number;
    roi: number;
  };
};

export const getSprintWipStatus = async (sprintId: number) => {
  const cacheKey = `wip_status_${sprintId}`;

  const cached = storage.get(cacheKey);

  if (cached !== null) {
    console.log("[API] Using cached WIP status");

    return cached;
  }

  const { data } = await api.get(
    `/v1/analytics/sprints/${sprintId}/wip-status`,
    { timeout: 30000 },
  );

  storage.set(cacheKey, data, { ttl: CACHE_TTL });

  return data as {
    total_active: number;
    limit_default: number;
    assignees: Array<{
      assignee: string;
      active_tasks: number;
      limit: number;
      wip_exceeded: boolean;
    }>;
    error?: string;
  };
};

export const getSprintCapacity = async (sprintId: number) => {
  const cacheKey = `capacity_${sprintId}`;

  const cached = storage.get(cacheKey);

  if (cached !== null) {
    console.log("[API] Using cached capacity");

    return cached;
  }

  const { data } = await api.get(`/v1/analytics/sprints/${sprintId}/capacity`, {
    timeout: 30000,
  });

  storage.set(cacheKey, data, { ttl: CACHE_TTL });

  return data as {
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
  };
};

export const listProjects = async (
  config?: AxiosRequestConfig,
): Promise<Project[]> => {
  const cacheKey = PROJECT_LIST_CACHE_KEY;

  const requestKey = "GET:/v1/projects";

  // Check for active request to prevent duplicate calls in StrictMode

  if (activeRequests.has(requestKey)) {
    console.log("[API] Reusing active request for projects");

    return activeRequests.get(requestKey)!;
  }

  // Check cache first

  const cached = storage.get<Project[]>(cacheKey);

  if (cached !== null) {
    console.log("[API] Using cached projects");

    return cached;
  }

  const promise = withRetry(
    () => api.get("/v1/projects/", { timeout: 45000, ...(config || {}) }),

    { retries: 2, baseDelayMs: 500, maxDelayMs: 4000 },
  ).then((res) => {
    let data: any = res.data;

    // Normalize shape if backend returns an object wrapper

    if (!Array.isArray(data) && Array.isArray(data?.projects)) {
      data = data.projects;
    }

    if (!Array.isArray(data)) {
      throw new Error("Unexpected /projects response shape");
    }

    storage.set(cacheKey, data, { ttl: CACHE_TTL });

    return data as Project[];
  });

  activeRequests.set(requestKey, promise);

  try {
    return await promise;
  } finally {
    activeRequests.delete(requestKey);
  }
};

export const getProjectById = async (
  id: number,
  config?: AxiosRequestConfig,
  options?: { skipCache?: boolean },
): Promise<Project> => {
  const cacheKey = projectCacheKey(id);
  const skipCache = Boolean(options?.skipCache);

  const requestKey = `GET:/v1/projects/${id}?force=${skipCache ? '1' : '0'}`;

  if (activeRequests.has(requestKey)) {
    console.log(`[API] Reusing active request for project ${id} skipCache=${skipCache}`);
    return activeRequests.get(requestKey)!;
  }

  if (skipCache) {
    storage.remove(cacheKey);
  } else {
    const cached = storage.get<Project | any>(cacheKey);
    if (cached && isValidProjectDetail(cached)) {
      console.log(`[API] Using cached project ${id}`);
      return cached;
    }
    if (cached !== null) {
      console.log(`[API] Discarding invalid cached project ${id}`);
      storage.remove(projectCacheKey(id));
    }
  }

  const promise = api.get(`/v1/projects/${id}`, config).then((res) => {
    const normalized = normalizeProjectDetail(res.data);
    storage.set(cacheKey, normalized, { ttl: CACHE_TTL });
    return normalized;
  });

  activeRequests.set(requestKey, promise);

  try {
    return await promise;
  } finally {
    activeRequests.delete(requestKey);
  }
};

export const createProject = async (payload: {
  name: string;
  jira_key: string;
  description?: string;
  owner_id: number;
}): Promise<Project> => {
  const { data } = await api.post("/v1/projects/", payload);

  invalidateProjectCache();
  return data;
};

export const updateProject = async (
  id: number,
  payload: Partial<
    Pick<
      Project,
      | "jira_key"
      | "name"
      | "description"
      | "status"
      | "budget"
      | "start_date"
      | "end_date"
    >
  >,
): Promise<Project> => {
  const { data } = await api.patch(`/v1/projects/${id}`, payload);

  invalidateProjectCache(id);
  return data;
};

// -------- Project Repository Management --------

export type RepositoryProvider = 'github' | 'gitlab';

export interface RepositoryInfo {
  id: number;
  provider: RepositoryProvider;
  repo_slug: string;
  default_branch?: string | null;
}

export interface ProjectRepositoryLink {
  id: number;
  project_id: number;
  repository_id: number;
  is_primary: boolean;
  created_at: string;
  updated_at?: string | null;
  repository: RepositoryInfo;
}

export interface BindRepositoryPayload {
  repositoryUrl?: string;
  provider?: RepositoryProvider;
  repoSlug?: string;
  isPrimary?: boolean;
}

export const getProjectRepositories = async (projectId: number): Promise<ProjectRepositoryLink[]> => {
  const { data } = await api.get(`/v1/projects/${projectId}/repositories`);

  return data as ProjectRepositoryLink[];
};

export const bindRepositoryToProject = async (
  projectId: number,
  payload: BindRepositoryPayload,
): Promise<ProjectRepositoryLink> => {
  const body: Record<string, any> = {
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

// -------- New Analytics & Quality APIs --------

export const getTestTrend = async (project_id?: number, days = 30) => {
  const params: any = { days };

  if (typeof project_id === "number") params.project_id = project_id;

  const { data } = await api.get("/v1/analytics/test-trend", { params });

  return data as {
    days: number;
    project_id?: number;
    trend: Array<{ day: string; total: number; failed: number }>;
  };
};

export const getCoverageTrend = async (project_id?: number, days = 30) => {
  const params: any = { days };

  if (typeof project_id === "number") params.project_id = project_id;

  const { data } = await api.get("/v1/analytics/coverage-trend", { params });

  return data as {
    days: number;
    project_id?: number;
    trend: Array<{
      day: string;
      avg_line: number;
      avg_branch: number;
      count: number;
    }>;
  };
};

export interface GetPRMetricsOptions {
  project_id?: number;

  provider?: string;

  since_days?: number;

  limit?: number;

  disable_cache?: boolean;
}

export const getPRMetrics = async (opts?: GetPRMetricsOptions) => {
  const params: any = {};

  if (opts?.project_id !== undefined) params.project_id = opts.project_id;

  if (opts?.provider) params.provider = opts.provider;

  if (opts?.since_days !== undefined) params.since_days = opts.since_days;

  if (opts?.limit !== undefined) params.limit = opts.limit;

  if (opts?.disable_cache) params.disable_cache = "true";

  const { data } = await api.get("/v1/git/pr-metrics", { params });

  return data as PRMetricsSummary;
};

export const listPullRequests = async (opts?: {
  project_id?: number;
  provider?: string;
  limit?: number;
}) => {
  const params: any = {};

  if (opts?.project_id !== undefined) params.project_id = opts.project_id;

  if (opts?.provider) params.provider = opts.provider;

  if (opts?.limit !== undefined) params.limit = opts.limit;

  const { data } = await api.get("/v1/git/pull-requests", { params });

  return data as { total: number; pull_requests: Array<any> };
};

export const getQualityGateStatus = async (
  pr_number: number,
  opts?: { project_id?: number; min_line?: number; min_branch?: number },
) => {
  const params: any = {};

  if (opts?.project_id !== undefined) params.project_id = opts.project_id;

  if (opts?.min_line !== undefined) params.min_line = opts.min_line;

  if (opts?.min_branch !== undefined) params.min_branch = opts.min_branch;

  const { data } = await api.get(`/v1/quality/gates/${pr_number}`, { params });

  return data as any;
};

export const evaluateQualityGate = async (payload: {
  pr_number?: number;
  commit_sha?: string;
  project_id?: number;
  min_line?: number;
  min_branch?: number;
  provider?: "github" | "gitlab" | "generic";
}) => {
  const { data } = await api.post("/v1/quality/gates/evaluate", payload);

  return data as any;
};

export const evaluateQualityGateAndCheck = async (payload: {
  pr_number?: number;
  commit_sha?: string;
  project_id?: number;
  min_line?: number;
  min_branch?: number;
  provider?: "github" | "gitlab" | "generic";
}) => {
  const { data } = await api.post(
    "/v1/quality/gates/evaluate-and-check",
    payload,
  );

  return data as any;
};

export const getIntegrationsHealth = async () => {
  const { data } = await api.get("/v1/health/integrations");

  return data as any;
};

export const getMetricsText = async (): Promise<string> => {
  const res = await api.get("/v1/health/metrics", {
    responseType: "text" as any,
  });

  return res.data as string;
};

export const getQualityHistory = async (opts?: {
  project_id?: number;
  pr_number?: number;
  limit?: number;
}) => {
  const params: any = {};

  if (opts?.project_id) params.project_id = opts.project_id;

  if (opts?.pr_number) params.pr_number = opts.pr_number;

  if (opts?.limit) params.limit = opts.limit;

  const { data } = await api.get("/v1/quality/history", { params });

  return data as { total: number; history: Array<any> };
};

export const getCoverageFiles = async (commit_sha: string) => {
  const { data } = await api.get(`/v1/testing/coverage/${commit_sha}/files`);

  return data as {
    total: number;
    files: Array<{
      file_path: string;
      line_coverage?: number;
      branch_coverage?: number;
      lines_covered?: number;
      lines_total?: number;
    }>;
  };
};

export const deleteProject = async (
  id: number,
): Promise<{ message: string }> => {
  const { data } = await api.delete(`/v1/projects/${id}`);

  invalidateProjectCache(id);
  return data;
};

export const purgeProject = async (
  id: number,
): Promise<{ message: string }> => {
  const { data } = await api.delete(`/v1/projects/${id}/purge`);

  invalidateProjectCache(id);
  return data;
};

// -------- Tasks --------

export interface TaskItem {
  id: number;

  jira_id: string;

  key: string;

  summary: string;

  status: string;

  priority?: string;

  assignee_name?: string;

  estimate_hours?: number;

  spent_hours?: number;
}

export const listTasksByProject = async (
  projectId: number,
  config?: AxiosRequestConfig,
): Promise<TaskItem[]> => {
  const { data } = await api.get(`/v1/tasks/`, {
    params: { project_id: projectId, limit: 1000 },
    ...(config || {}),
  });

  return data;
};

export const syncJiraProject = async (
  projectKey: string,
  config?: AxiosRequestConfig,
) => {
  // Clear cache when syncing

  storage.clearAll();

  const { data } = await api.post(
    `/v1/jira/projects/${projectKey}/sync`,
    undefined,
    config,
  );

  return data;
};

export const listTasks = async (
  filters?: {
    status?: string;
    assignee?: string;
    project_id?: number;
    limit?: number;
  },

  config?: AxiosRequestConfig,
) => {
  const cacheKey = `tasks_${JSON.stringify(filters || {})}`;

  const requestKey = `GET:/v1/tasks:${JSON.stringify(filters || {})}`;

  // Check for active request

  if (activeRequests.has(requestKey)) {
    console.log("[API] Reusing active request for tasks");

    return activeRequests.get(requestKey)!;
  }

  // Check cache - with special handling for large task sets

  const cached = storage.get<TaskItem[]>(cacheKey);

  if (cached !== null) {
    console.log("[API] Using cached tasks");

    return cached;
  }

  const params: any = {};

  if (filters?.status) params.status = filters.status;

  if (filters?.assignee) params.assignee = filters.assignee;

  if (filters?.project_id) params.project_id = filters.project_id;

  params.limit = filters?.limit ?? 500; // Reduced default limit to avoid localStorage issues

  const promise = withRetry(
    () => api.get("/v1/tasks/", { params, timeout: 60000, ...(config || {}) }),

    { retries: 2, baseDelayMs: 700, maxDelayMs: 6000 },
  ).then((res) => {
    const data = res.data as TaskItem[];

    // Only cache if not too large (less than 500 tasks)

    if (data.length < 500) {
      storage.set(cacheKey, data, { ttl: CACHE_TTL });
    } else {
      console.log(`[API] Not caching ${data.length} tasks (too large)`);
    }

    return data;
  });

  activeRequests.set(requestKey, promise);

  try {
    return await promise;
  } finally {
    activeRequests.delete(requestKey);
  }
};

// -------- Analytics --------

export const getVelocity = async (projectId: number) => {
  const { data } = await api.get(
    `/v1/analytics/projects/${projectId}/velocity`,
  );

  return data;
};

export const getBurndown = async (projectId: number, sprintId?: number) => {
  const { data } = await api.get(
    `/v1/analytics/projects/${projectId}/burndown`,
    { params: { sprint_id: sprintId } },
  );

  return data;
};

export const getRisks = async (projectId: number) => {
  const { data } = await api.get(`/v1/analytics/projects/${projectId}/risks`);

  return data;
};

export const getForecast = async (projectId: number) => {
  const { data } = await api.get(
    `/v1/analytics/projects/${projectId}/forecast`,
  );

  return data;
};

export const getDoraMetrics = async (projectId: number, windowDays = 30) => {
  const params = { window_days: windowDays };

  const { data } = await api.get(`/v1/analytics/projects/${projectId}/dora`, {
    params,
  });

  return data;
};

// -------- Sprint Analytics --------

// Use the correct analytics endpoint for sprints

export const listSprints = async (
  filters?: { project_id?: number },
  config?: AxiosRequestConfig,
) => {
  if (!filters?.project_id) {
    console.log(
      "[API] No project_id provided for sprints, returning empty array",
    );

    return [];
  }

  const cacheKey = `sprints_project_${filters.project_id}`;

  const requestKey = `GET:/v1/analytics/projects/${filters.project_id}/sprints`;

  // Check for active request

  if (activeRequests.has(requestKey)) {
    console.log("[API] Reusing active request for sprints");

    return activeRequests.get(requestKey)!;
  }

  // Check cache

  const cached = storage.get(cacheKey);

  if (cached !== null) {
    console.log("[API] Using cached sprints");

    return cached;
  }

  const promise = api
    .get(`/v1/analytics/projects/${filters.project_id}/sprints`, {
      params: { limit: 50 },

      timeout: 10000, // Specific 10s timeout for sprint fetch

      ...config,
    })
    .then((res) => {
      // The endpoint returns { total, board_id, sprints } structure

      const sprints = res.data.sprints || [];

      storage.set(cacheKey, sprints, { ttl: CACHE_TTL });

      return sprints;
    })
    .catch((error) => {
      console.error("[API] Sprint fetch failed:", error.message);

      // Return cached data if available on error

      const stale = storage.get(cacheKey, { ignoreExpiry: true });

      if (stale) {
        console.log("[API] Returning stale cached sprints due to error");

        return stale;
      }

      // Return empty array to prevent UI from hanging

      return [];
    });

  activeRequests.set(requestKey, promise);

  try {
    return await promise;
  } finally {
    activeRequests.delete(requestKey);
  }
};

export const getProjectSprints = async (
  projectId: number,
  limit = 10,
  board_id?: number,
) => {
  const params: any = { limit };

  if (board_id !== undefined) params.board_id = board_id;

  try {
    const { data } = await api.get(
      `/v1/analytics/projects/${projectId}/sprints`,
      {
        params,

        timeout: 10000, // Reduced timeout to 10 seconds for faster failure
      },
    );

    return data as {
      total: number;
      sprints: any[];
      board_id?: number;
      error?: string;
    };
  } catch (error: any) {
    // Always return empty result on any error to prevent UI freeze

    const errorType =
      error.code === "ECONNABORTED" || error.message?.includes("timeout")
        ? "timeout"
        : "error";

    console.warn(`Sprint fetch failed (${errorType}):`, error.message);

    return { total: 0, sprints: [], board_id, error: errorType };
  }
};

export const getSprintBurndown = async (sprintId: number) => {
  const { data } = await api.get(`/v1/analytics/sprints/${sprintId}/burndown`);

  return data;
};

export const getSprintQuality = async (sprintId: number) => {
  const { data } = await api.get(`/v1/analytics/sprints/${sprintId}/quality`);

  return data as {
    total_tasks: number;
    dod_pct: number;
    bugs_by_priority: Record<string, number>;
    blockers: number;
  };
};

export const getBoardsForProject = async (jiraKey: string) => {
  const { data } = await api.get(`/v1/jira/projects/${jiraKey}/boards`);

  return data as { count: number; boards: any[] };
};

export const setTaskBusinessValue = async (
  taskId: number,
  opts: { business_value?: number; value_delivered?: boolean },
) => {
  const params: any = {};

  if (opts.business_value !== undefined)
    params.business_value = opts.business_value;

  if (opts.value_delivered !== undefined)
    params.value_delivered = String(opts.value_delivered);

  const { data } = await api.post(
    `/v1/tasks/${taskId}/business-value`,
    undefined,
    { params },
  );

  return data as TaskItem;
};

// -------- Traceability --------

export const getTraceabilityMatrix = async (opts?: {
  projectId?: number;
  force?: boolean;
}): Promise<TraceabilityMatrixSummary> => {
  const projectId =
    typeof opts?.projectId === "number" ? opts.projectId : undefined;

  const cacheKey = `traceability_matrix_${projectId ?? "all"}`;

  const requestKey = `GET:/v1/traceability/matrix:${projectId ?? "all"}`;

  if (opts?.force) {
    storage.remove(cacheKey);
  }

  if (activeRequests.has(requestKey)) {
    console.log("[API] Reusing active request for traceability matrix");

    return activeRequests.get(requestKey)!;
  }

  if (!opts?.force) {
    const cached = storage.get<TraceabilityMatrixSummary>(cacheKey);

    if (cached !== null) {
      console.log("[API] Using cached traceability matrix");

      return cached;
    }
  }

  const params: Record<string, any> = {};

  if (projectId !== undefined) {
    params.project_id = projectId;
  }

  const promise = withRetry(
    () => api.get("/v1/traceability/matrix", { params, timeout: 25000 }),

    { retries: 2, baseDelayMs: 400, maxDelayMs: 4000 },
  ).then((res) => {
    const payload = res.data as TraceabilityMatrixSummary;

    storage.set(cacheKey, payload, { ttl: 45000 });

    return payload;
  });

  activeRequests.set(requestKey, promise);

  try {
    return await promise;
  } finally {
    activeRequests.delete(requestKey);
  }
};

export const runTraceabilityBackfill = async (
  projectId: number,
  opts?: { includeConfluence?: boolean; includeGit?: boolean; timeoutMs?: number },
): Promise<TraceabilityBackfillResult> => {
  const params: Record<string, any> = { project_id: projectId };

  if (opts?.includeConfluence === true) {
    params.include_confluence = "true";
  } else if (opts?.includeConfluence === false) {
    params.include_confluence = "false";
  }

  if (opts?.includeGit === true) {
    params.include_git = "true";
  } else if (opts?.includeGit === false) {
    params.include_git = "false";
  }

  const timeout = opts?.timeoutMs ?? 60000;

  const { data } = await api.post("/v1/traceability/backfill", undefined, {
    params,
    timeout,
  });

  storage.remove(`traceability_matrix_${projectId}`);

  storage.remove("traceability_matrix_all");

  return data as TraceabilityBackfillResult;
};

export interface TraceabilityFlowNode {
  id: number;

  type?: string | null;

  title?: string | null;

  status?: string | null;
}

export interface TraceabilityFlowEdge {
  from: number;

  to: number;

  type: string;

  confidence?: number | null;
}

export interface TraceabilityRequirementFlow {
  nodes: TraceabilityFlowNode[];

  edges: TraceabilityFlowEdge[];
}

export interface TraceabilityNeighborArtifact {
  id: number;

  type: string;

  source: string;

  external_id: string;

  title?: string | null;

  status?: string | null;
}

export interface TraceabilityNeighborLink {
  link_type: string;

  confidence?: number | null;

  artifact: TraceabilityNeighborArtifact;
}

export interface TraceabilityTaskArtifacts {
  task_artifact: { id: number; key: string };

  outgoing: TraceabilityNeighborLink[];

  incoming: TraceabilityNeighborLink[];
}

export const getTraceabilityRequirementFlow = async (
  artifactId: number,
  opts?: { depth?: number; timeoutMs?: number },
): Promise<TraceabilityRequirementFlow> => {
  const params: Record<string, any> = {};

  if (typeof opts?.depth === "number") {
    params.depth = opts.depth;
  }

  const timeout = opts?.timeoutMs ?? 30000;

  const response = await withRetry(
    () =>
      api.get(`/v1/traceability/requirement/${artifactId}/flow`, {
        params,
        timeout,
      }),

    { retries: 1, baseDelayMs: 400, maxDelayMs: 2500 },
  );

  return response.data as TraceabilityRequirementFlow;
};

export const getTraceabilityTaskArtifacts = async (
  jiraKey: string,
  config?: AxiosRequestConfig,
): Promise<TraceabilityTaskArtifacts> => {
  const response = await withRetry(
    () =>
      api.get(
        `/v1/traceability/task/${encodeURIComponent(jiraKey)}/artifacts`,
        { timeout: 20000, ...(config || {}) },
      ),

    { retries: 1, baseDelayMs: 400, maxDelayMs: 2500 },
  );

  return response.data as TraceabilityTaskArtifacts;
};

export interface GitHubPullRequest {
  number: number;
  title?: string;
  state?: string;
  draft?: boolean;
  html_url?: string;
  user?: {
    login?: string;
    avatar_url?: string;
  } | null;
  created_at?: string;
  updated_at?: string;
  merged_at?: string | null;
  additions?: number | null;
  deletions?: number | null;
  changed_files?: number | null;
  labels?: string[] | null;
}

export interface GitHubPullResponse {
  repository: string;
  state: string;
  count: number;
  pulls: GitHubPullRequest[];
}

export const getGitHubProjectPulls = async (
  projectId: number,
  opts?: { state?: string; limit?: number }
): Promise<GitHubPullResponse> => {
  const params: Record<string, any> = {};
  if (opts?.state) params.state = opts.state;
  if (opts?.limit) params.limit = opts.limit;
  const { data } = await api.get(`/v1/git/github/projects/${projectId}/pulls`, { params });
  return data as GitHubPullResponse;
};

