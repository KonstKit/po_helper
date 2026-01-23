/**
 * Integration APIs - JIRA, GitHub, GitLab, Confluence settings and testing.
 */
import api from './client';
import type { AxiosRequestConfig } from 'axios';
import type {
  IntegrationSettings,
  GithubTestResponse,
  GitlabProjectsResponse,
} from './types';

// =============================================================================
// JIRA Settings
// =============================================================================

export const getJiraSettings = async (): Promise<IntegrationSettings> => {
  const { data } = await api.get("/v1/settings/jira");
  return data;
};

export interface JiraProject {
  key: string;
  name: string;
  id?: string | number;
  projectTypeKey?: string;
}

export interface JiraProjectsResponse {
  count: number;
  projects: JiraProject[];
}

export const connectJira = async (payload: {
  baseUrl: string;
  apiToken: string;
  email?: string;
  save?: boolean;
  usePat?: boolean;
}): Promise<{ status: string; message?: string }> => {
  const params: Record<string, unknown> = {
    base_url: payload.baseUrl,
    api_token: payload.apiToken,
  };
  if (payload.email !== undefined) params.email = payload.email;
  if (payload.save !== undefined) params.save = payload.save;
  if (payload.usePat !== undefined) params.use_pat = payload.usePat;

  const { data } = await api.post("/v1/jira/connect", undefined, { params });
  return data;
};

export const listJiraProjects = async (
  opts?: { query?: string },
  config?: AxiosRequestConfig
): Promise<JiraProjectsResponse> => {
  const params: Record<string, unknown> = {};
  if (opts?.query) params.q = opts.query;

  const { data } = await api.get("/v1/jira/projects", { params, ...(config || {}) });
  return data as JiraProjectsResponse;
};

export const putJiraSettings = async (payload: {
  baseUrl?: string;
  email?: string;
  apiToken?: string;
  usePat?: boolean;
}): Promise<IntegrationSettings> => {
  const body: Record<string, unknown> = {};
  if (payload.baseUrl !== undefined) body.base_url = payload.baseUrl;
  if (payload.email !== undefined) body.email = payload.email;
  if (payload.apiToken !== undefined) body.api_token = payload.apiToken;
  if (payload.usePat !== undefined) body.use_pat = payload.usePat;

  const { data } = await api.put("/v1/settings/jira", body);
  return data;
};

export const testJiraConnection = async (payload: {
  baseUrl?: string;
  email?: string;
  apiToken?: string;
  usePat?: boolean;
}): Promise<{ status: string; message?: string }> => {
  const body: Record<string, unknown> = {};
  if (payload.baseUrl !== undefined) body.base_url = payload.baseUrl;
  if (payload.email !== undefined) body.email = payload.email;
  if (payload.apiToken !== undefined) body.api_token = payload.apiToken;
  if (payload.usePat !== undefined) body.use_pat = payload.usePat;

  const { data } = await api.post("/v1/settings/jira/test", body);
  return data;
};

// =============================================================================
// Confluence Settings
// =============================================================================

export const getConfluenceSettings = async (): Promise<IntegrationSettings> => {
  const { data } = await api.get("/v1/settings/confluence");
  return data;
};

export const putConfluenceSettings = async (payload: {
  baseUrl?: string;
  email?: string;
  apiToken?: string;
}): Promise<IntegrationSettings> => {
  const body: Record<string, unknown> = {};
  if (payload.baseUrl !== undefined) body.base_url = payload.baseUrl;
  if (payload.email !== undefined) body.email = payload.email;
  if (payload.apiToken !== undefined) body.api_token = payload.apiToken;

  const { data } = await api.put("/v1/settings/confluence", body);
  return data;
};

export const testConfluenceConnection = async (payload: {
  baseUrl?: string;
  email?: string;
  apiToken?: string;
}): Promise<{ status: string; message?: string }> => {
  const body: Record<string, unknown> = {};
  if (payload.baseUrl !== undefined) body.base_url = payload.baseUrl;
  if (payload.email !== undefined) body.email = payload.email;
  if (payload.apiToken !== undefined) body.api_token = payload.apiToken;

  const { data } = await api.post("/v1/settings/confluence/test", body);
  return data;
};

// =============================================================================
// GitHub Settings
// =============================================================================

export const getGithubSettings = async (): Promise<{
  base_url?: string;
  has_token?: boolean;
  has_webhook_secret?: boolean;
}> => {
  const { data } = await api.get("/v1/settings/github");
  return data;
};

export const putGithubSettings = async (payload: {
  baseUrl?: string;
  apiToken?: string;
  webhookSecret?: string;
}): Promise<{ base_url?: string; has_token?: boolean; has_webhook_secret?: boolean }> => {
  const body: Record<string, unknown> = {};
  if (payload.baseUrl !== undefined) body.base_url = payload.baseUrl;
  if (payload.apiToken !== undefined) body.api_token = payload.apiToken;
  if (payload.webhookSecret !== undefined) body.webhook_secret = payload.webhookSecret;

  const { data } = await api.put("/v1/settings/github", body);
  return data;
};

export const testGithubConnection = async (payload: {
  baseUrl?: string;
  apiToken?: string;
}): Promise<GithubTestResponse> => {
  const body: Record<string, unknown> = {};
  if (payload.baseUrl !== undefined) body.base_url = payload.baseUrl;
  if (payload.apiToken !== undefined) body.api_token = payload.apiToken;

  const { data } = await api.post("/v1/settings/github/test", body);
  return data as GithubTestResponse;
};

// =============================================================================
// GitLab Settings
// =============================================================================

export const getGitlabSettings = async (): Promise<{
  base_url?: string;
  has_token?: boolean;
  has_webhook_secret?: boolean;
}> => {
  const { data } = await api.get("/v1/settings/gitlab");
  return data;
};

export const putGitlabSettings = async (payload: {
  baseUrl?: string;
  apiToken?: string;
  webhookSecret?: string;
}): Promise<{ base_url?: string; has_token?: boolean; has_webhook_secret?: boolean }> => {
  const body: Record<string, unknown> = {};
  if (payload.baseUrl !== undefined) body.base_url = payload.baseUrl;
  if (payload.apiToken !== undefined) body.api_token = payload.apiToken;
  if (payload.webhookSecret !== undefined) body.webhook_secret = payload.webhookSecret;

  const { data } = await api.put("/v1/settings/gitlab", body);
  return data;
};

export const testGitlabConnection = async (payload: {
  baseUrl?: string;
  apiToken?: string;
  webhookSecret?: string;
}): Promise<{
  status: string;
  message?: string;
  base_url?: string;
  api_base?: string;
  username?: string;
  name?: string;
  email?: string;
  webhook_secret_configured?: boolean;
}> => {
  const body: Record<string, unknown> = {};
  if (payload.baseUrl !== undefined) body.base_url = payload.baseUrl;
  if (payload.apiToken !== undefined) body.api_token = payload.apiToken;
  if (payload.webhookSecret !== undefined) body.webhook_secret = payload.webhookSecret;

  const { data } = await api.post("/v1/settings/gitlab/test", body);
  return data;
};

export const listGitlabProjects = async (
  opts?: {
    search?: string;
    page?: number;
    perPage?: number;
    groupId?: number;
    groupPath?: string;
    includeSubgroups?: boolean;
  }
): Promise<GitlabProjectsResponse> => {
  const params: Record<string, unknown> = {};
  if (opts?.search) params.search = opts.search;
  if (opts?.page) params.page = opts.page;
  if (opts?.perPage) params.per_page = opts.perPage;
  if (opts?.groupId !== undefined) params.group_id = opts.groupId;
  if (opts?.groupPath) params.group_path = opts.groupPath;
  if (opts?.includeSubgroups !== undefined) params.include_subgroups = opts.includeSubgroups;

  const { data } = await api.get("/v1/git/gitlab/projects", { params });
  return data as GitlabProjectsResponse;
};

// =============================================================================
// Bitbucket Settings
// =============================================================================

export interface BitbucketSettings {
  base_url?: string;
  email?: string;  // username for Cloud
  has_token?: boolean;
  has_webhook_secret?: boolean;
  instance_type?: 'cloud' | 'server';
}

export interface BitbucketTestResponse {
  status: string;
  message?: string;
  instance_type?: string;
  username?: string;
  display_name?: string;
}

export const getBitbucketSettings = async (): Promise<BitbucketSettings> => {
  const { data } = await api.get("/v1/settings/bitbucket");
  return data;
};

export const putBitbucketSettings = async (payload: {
  baseUrl?: string;
  email?: string;  // username for Cloud
  apiToken?: string;  // app_password for Cloud, PAT for Server
  webhookSecret?: string;
}): Promise<BitbucketSettings> => {
  const body: Record<string, unknown> = {};
  if (payload.baseUrl !== undefined) body.base_url = payload.baseUrl;
  if (payload.email !== undefined) body.email = payload.email;
  if (payload.apiToken !== undefined) body.api_token = payload.apiToken;
  if (payload.webhookSecret !== undefined) body.webhook_secret = payload.webhookSecret;

  const { data } = await api.put("/v1/settings/bitbucket", body);
  return data;
};

export const testBitbucketConnection = async (payload: {
  baseUrl?: string;
  email?: string;
  apiToken?: string;
}): Promise<BitbucketTestResponse> => {
  const body: Record<string, unknown> = {};
  if (payload.baseUrl !== undefined) body.base_url = payload.baseUrl;
  if (payload.email !== undefined) body.email = payload.email;
  if (payload.apiToken !== undefined) body.api_token = payload.apiToken;

  const { data } = await api.post("/v1/settings/bitbucket/test", body);
  return data;
};

// =============================================================================
// TestRail Settings
// =============================================================================

export const getTestrailSettings = async (): Promise<{
  base_url?: string;
  email?: string;
  has_token?: boolean;
}> => {
  const { data } = await api.get("/v1/settings/testrail");
  return data;
};

export const putTestrailSettings = async (payload: {
  baseUrl?: string;
  email?: string;
  apiToken?: string;
}): Promise<{ base_url?: string; email?: string; has_token?: boolean }> => {
  const body: Record<string, unknown> = {};
  if (payload.baseUrl !== undefined) body.base_url = payload.baseUrl;
  if (payload.email !== undefined) body.email = payload.email;
  if (payload.apiToken !== undefined) body.api_token = payload.apiToken;

  const { data } = await api.put("/v1/settings/testrail", body);
  return data;
};

export const testTestrailConnection = async (payload: {
  baseUrl?: string;
  email?: string;
  apiToken?: string;
}): Promise<{ status: string; message?: string; status_count?: number; user?: string }> => {
  const body: Record<string, unknown> = {};
  if (payload.baseUrl !== undefined) body.base_url = payload.baseUrl;
  if (payload.email !== undefined) body.email = payload.email;
  if (payload.apiToken !== undefined) body.api_token = payload.apiToken;

  const { data } = await api.post("/v1/settings/testrail/test", body);
  return data;
};

// =============================================================================
// Integration Status (Health)
// =============================================================================

// Simple cache to prevent API spam
let _integrationStatusCache: unknown = null;
let _integrationStatusCacheTime = 0;

export const clearIntegrationStatusCache = () => {
  _integrationStatusCache = null;
  _integrationStatusCacheTime = 0;
};

export interface IntegrationStatusResponse {
  jira: {
    configured: boolean;
    base_url?: string | null;
    has_token?: boolean;
    auth_mode?: string;
    status?: string;
  };
  confluence: {
    configured: boolean;
    base_url?: string | null;
    has_token?: boolean;
    auth_mode?: string;
    instance_type?: string;
    status?: string;
  };
  github: {
    configured: boolean;
    base_url?: string | null;
    auth_mode?: string;
    has_token?: boolean;
  };
  gitlab: {
    configured: boolean;
    base_url?: string | null;
    auth_mode?: string;
    has_token?: boolean;
  };
  bitbucket?: {
    configured: boolean;
    base_url?: string | null;
    instance_type?: 'cloud' | 'server';
    auth_mode?: string;
    has_token?: boolean;
  };
  testrail?: {
    configured: boolean;
    base_url?: string | null;
    has_token?: boolean;
  };
}

export const getIntegrationsStatus = async (): Promise<IntegrationStatusResponse> => {
  const now = Date.now();

  if (_integrationStatusCache && now - _integrationStatusCacheTime < 5000) {
    return _integrationStatusCache as IntegrationStatusResponse;
  }

  const { data } = await api.get("/v1/health/integrations");

  _integrationStatusCache = data;
  _integrationStatusCacheTime = now;

  return data as IntegrationStatusResponse;
};
