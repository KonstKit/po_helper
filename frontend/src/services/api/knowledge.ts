/**
 * Knowledge APIs - Confluence spaces, pages, PRD requirements, ADRs, research.
 */
import api from './client';

// =============================================================================
// Confluence Spaces
// =============================================================================

export interface ConfluenceSpace {
  id: string;
  key: string;
  name: string;
  url?: string;
}

export interface ConfluenceSpacesResponse {
  count: number;
  results: ConfluenceSpace[];
}

export const listConfluenceSpaces = async (
  q?: string,
  limit = 50
): Promise<ConfluenceSpacesResponse> => {
  const params: Record<string, unknown> = { limit };
  if (q) params.q = q;

  const { data } = await api.get('/v1/confluence/spaces', { params });
  return data as ConfluenceSpacesResponse;
};

// =============================================================================
// Confluence Pages
// =============================================================================

export interface ConfluencePage {
  id: string;
  title: string;
  space?: string;
  url?: string;
  version?: number;
  last_updated?: string;
}

export interface ConfluencePagesResponse {
  count: number;
  results: ConfluencePage[];
}

export const listConfluencePages = async (opts?: {
  space?: string;
  q?: string;
  limit?: number;
  start?: number;
}): Promise<ConfluencePagesResponse> => {
  const params: Record<string, unknown> = {};
  if (opts?.space) params.space = opts.space;
  if (opts?.q) params.q = opts.q;
  params.limit = opts?.limit ?? 50;
  if (opts?.start !== undefined) params.start = opts.start;

  const { data } = await api.get('/v1/confluence/pages', { params });
  return data as ConfluencePagesResponse;
};

export const listConfluencePagesLocal = async (opts?: {
  space?: string;
  q?: string;
  limit?: number;
  offset?: number;
}): Promise<ConfluencePagesResponse> => {
  const params: Record<string, unknown> = {};
  if (opts?.space) params.space = opts.space;
  if (opts?.q) params.q = opts.q;
  params.limit = opts?.limit ?? 50;
  if (opts?.offset !== undefined) params.offset = opts.offset;

  const { data } = await api.get('/v1/confluence/local/pages', { params });
  return data as ConfluencePagesResponse;
};

// =============================================================================
// Single Page Content
// =============================================================================

export interface ConfluencePageDetail {
  id: string;
  title: string;
  url?: string;
  html?: string;
  labels?: unknown;
  version?: number;
}

export const getConfluencePage = async (pageId: string): Promise<ConfluencePageDetail> => {
  const { data } = await api.get(`/v1/confluence/pages/${pageId}`);
  return data as ConfluencePageDetail;
};

// =============================================================================
// PRD Requirements
// =============================================================================

export interface PrdRequirement {
  id: string;
  description: string;
  priority: string;
}

export interface PrdRequirementsResponse {
  count: number;
  requirements: PrdRequirement[];
}

export const getPrdRequirements = async (pageId: string): Promise<PrdRequirementsResponse> => {
  const { data } = await api.get(`/v1/confluence/prd/${pageId}/requirements`);
  return data as PrdRequirementsResponse;
};

// =============================================================================
// Confluence Sync
// =============================================================================

export interface ConfluenceSyncResult {
  synced: number;
  created: number;
  updated: number;
}

export const syncConfluence = async (opts?: {
  space?: string;
  q?: string;
  limit?: number;
  start?: number;
  full?: boolean;
}): Promise<ConfluenceSyncResult> => {
  const params: Record<string, unknown> = {};
  if (opts?.space) params.space = opts.space;
  if (opts?.q) params.q = opts.q;
  params.limit = opts?.limit ?? 50;
  if (opts?.full) params.full = 'true';
  if (opts?.start !== undefined) params.start = opts.start;

  const { data } = await api.post('/v1/confluence/sync', undefined, {
    params,
    timeout: 120000,
  });
  return data as ConfluenceSyncResult;
};

// =============================================================================
// Space Tree
// =============================================================================

export interface SpaceTreeNode {
  id: string;
  title: string;
  children?: SpaceTreeNode[];
}

export interface SpaceTreeResponse {
  count: number;
  tree: SpaceTreeNode[];
}

export const getSpaceTree = async (
  spaceKey: string,
  limit = 100,
  maxPages?: number
): Promise<SpaceTreeResponse> => {
  const params = new URLSearchParams({ limit: String(limit) });
  if (typeof maxPages === 'number') params.set('max_pages', String(maxPages));

  const { data } = await api.get(
    `/v1/confluence/spaces/${encodeURIComponent(spaceKey)}/tree?${params}`
  );
  return data as SpaceTreeResponse;
};

export const syncSubtree = async (
  pageId: string,
  limit = 50
): Promise<ConfluenceSyncResult> => {
  const params = new URLSearchParams({ limit: String(limit) });

  const { data } = await api.post(
    `/v1/confluence/subtree/${encodeURIComponent(pageId)}/sync?${params.toString()}`,
    undefined,
    { timeout: 120000 }
  );
  return data as ConfluenceSyncResult;
};

// =============================================================================
// ADR (Architecture Decision Records)
// =============================================================================

export interface ADRResponse {
  id: string;
  title: string;
  status?: string | null;
  context?: string;
  decision?: string;
  consequences?: string;
  alternatives?: string;
}

export const getADR = async (pageId: string): Promise<ADRResponse> => {
  const { data } = await api.get(`/v1/confluence/adr/${pageId}`);
  return data as ADRResponse;
};

// =============================================================================
// Research
// =============================================================================

export interface ResearchResponse {
  id: string;
  title: string;
  insights: Record<string, string[]>;
}

export const getResearch = async (pageId: string): Promise<ResearchResponse> => {
  const { data } = await api.get(`/v1/confluence/research/${pageId}`);
  return data as ResearchResponse;
};
