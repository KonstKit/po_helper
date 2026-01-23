/**
 * Traceability APIs - Matrix, flows, chains, impact analysis, sync health.
 */
import api, { withRetry } from './client';
import { AxiosRequestConfig } from 'axios';
import type {
  TraceabilityMatrixSummary,
  TraceabilityBackfillResult,
  TraceabilityRequirementFlow,
  TraceabilityTaskArtifacts,
  GitHubPullResponse,
  FullChainResponse,
  ImpactAnalysisResponse,
  OrphanedArtifactsResponse,
  OrphanedArtifact,
  ConfidenceDistribution,
  RecalculateConfidenceResult,
  SuggestedLinksResponse,
  SuggestedLink,
  SuggestedLinksStats,
  GenerateSuggestionsResult,
  SyncHealthResponse,
  DetailedSyncHealthResponse,
  ConsistencyCheckResponse,
  FixConsistencyResult,
  DetailedCyclesResponse,
  // Traceability Rules types
  TraceabilityRule,
  TraceabilityRuleCreate,
  TraceabilityRuleUpdate,
  TraceabilityRuleListResponse,
  TraceabilityRuleExecutionListResponse,
  TraceabilityRuleExecution,
  ListRulesOptions,
  ListRuleExecutionsOptions,
  RuleExecutionResult,
  DEFAULT_PAGE_SIZE,
} from './types';
import { normalizePaginatedResponse } from './pagination';

// =============================================================================
// Traceability Matrix
// =============================================================================

export const getTraceabilityMatrix = async (
  opts?: { projectId?: number; force?: boolean; timeout?: number }
): Promise<TraceabilityMatrixSummary> => {
  const params: Record<string, unknown> = {};
  if (opts?.projectId !== undefined) params.project_id = opts.projectId;
  if (opts?.force !== undefined) params.force = opts.force;

  const { data } = await withRetry(
    () => api.get(`/v1/traceability/matrix`, { params, timeout: opts?.timeout ?? 30000 }),
    { retries: 2, baseDelayMs: 500, maxDelayMs: 3000 }
  );
  return data as TraceabilityMatrixSummary;
};

export const backfillTraceability = async (
  projectId: number,
  opts?: { includeConfluence?: boolean; includeGit?: boolean; timeoutMs?: number }
): Promise<TraceabilityBackfillResult> => {
  const params: Record<string, unknown> = { project_id: projectId };
  if (opts?.includeConfluence !== undefined) {
    params.include_confluence = opts.includeConfluence;
  }
  if (opts?.includeGit !== undefined) {
    params.include_git = opts.includeGit;
  }

  const { data } = await api.post(`/v1/traceability/backfill`, undefined, {
    params,
    timeout: opts?.timeoutMs ?? 120000, // 2 minutes for backfill
  });
  return data as TraceabilityBackfillResult;
};

// =============================================================================
// Requirement Flow
// =============================================================================

export const getTraceabilityRequirementFlow = async (
  artifactId: number,
  opts?: { depth?: number; timeoutMs?: number }
): Promise<TraceabilityRequirementFlow> => {
  const params: Record<string, unknown> = {};
  if (typeof opts?.depth === "number") {
    params.depth = opts.depth;
  }

  const timeout = opts?.timeoutMs ?? 30000;

  const response = await withRetry(
    () => api.get(`/v1/traceability/requirement/${artifactId}/flow`, { params, timeout }),
    { retries: 1, baseDelayMs: 400, maxDelayMs: 2500 }
  );

  return response.data as TraceabilityRequirementFlow;
};

// =============================================================================
// Task Artifacts
// =============================================================================

export const getTraceabilityTaskArtifacts = async (
  jiraKey: string,
  config?: AxiosRequestConfig
): Promise<TraceabilityTaskArtifacts> => {
  const response = await withRetry(
    () => api.get(
      `/v1/traceability/task/${encodeURIComponent(jiraKey)}/artifacts`,
      { timeout: 20000, ...(config || {}) }
    ),
    { retries: 1, baseDelayMs: 400, maxDelayMs: 2500 }
  );

  return response.data as TraceabilityTaskArtifacts;
};

// =============================================================================
// GitHub Pull Requests
// =============================================================================

export const getGitHubProjectPulls = async (
  projectId: number,
  opts?: { state?: string; limit?: number }
): Promise<GitHubPullResponse> => {
  const params: Record<string, unknown> = {};
  if (opts?.state) params.state = opts.state;
  if (opts?.limit) params.limit = opts.limit;
  const { data } = await api.get(`/v1/git/github/projects/${projectId}/pulls`, { params });
  return data as GitHubPullResponse;
};

// =============================================================================
// Full Traceability Chain
// =============================================================================

export const getFullTraceabilityChain = async (
  artifactId: number,
  opts?: {
    depth?: number;
    direction?: 'upstream' | 'downstream' | 'both';
    minConfidence?: number;
    includeFactors?: boolean;
  }
): Promise<FullChainResponse> => {
  const params: Record<string, unknown> = {};
  if (opts?.depth !== undefined) params.depth = opts.depth;
  if (opts?.direction) params.direction = opts.direction;
  if (opts?.minConfidence !== undefined) params.min_confidence = opts.minConfidence;
  if (opts?.includeFactors !== undefined) params.include_factors = opts.includeFactors;

  const { data } = await api.get(`/v1/traceability/full-chain/${artifactId}`, {
    params,
    timeout: 30000,
  });
  return data as FullChainResponse;
};

// =============================================================================
// Impact Analysis
// =============================================================================

export const getImpactAnalysis = async (
  artifactId: number,
  opts?: { changeType?: 'modify' | 'delete' | 'status_change'; maxDepth?: number }
): Promise<ImpactAnalysisResponse> => {
  const params: Record<string, unknown> = {};
  if (opts?.changeType) params.change_type = opts.changeType;
  if (opts?.maxDepth !== undefined) params.max_depth = opts.maxDepth;

  const { data } = await api.get(`/v1/traceability/impact-analysis/${artifactId}`, {
    params,
    timeout: 30000,
  });
  return data as ImpactAnalysisResponse;
};

// =============================================================================
// Orphaned Artifacts
// =============================================================================

export const getOrphanedArtifacts = async (
  opts?: { projectId?: number; artifactType?: string; limit?: number; offset?: number }
): Promise<OrphanedArtifactsResponse> => {
  const params: Record<string, unknown> = {};
  if (opts?.projectId !== undefined) params.project_id = opts.projectId;
  if (opts?.artifactType) params.artifact_type = opts.artifactType;
  const offset = opts?.offset ?? 0;
  const limit = opts?.limit ?? DEFAULT_PAGE_SIZE;
  params.limit = limit;
  params.offset = offset;

  const { data } = await api.get('/v1/traceability/orphaned-artifacts', {
    params,
    timeout: 30000,
  });
  const response = normalizePaginatedResponse<OrphanedArtifact>(data, {
    skip: offset,
    limit,
    legacyKey: 'orphans',
  });
  const payload = data as Record<string, unknown>;
  return {
    ...response,
    by_type: (payload.by_type as Record<string, number>) || {},
    by_source: (payload.by_source as Record<string, number>) || {},
  };
};

// =============================================================================
// Confidence Scoring
// =============================================================================

export const getConfidenceDistribution = async (
  opts?: { projectId?: number; linkType?: string }
): Promise<ConfidenceDistribution> => {
  const params: Record<string, unknown> = {};
  if (opts?.projectId !== undefined) params.project_id = opts.projectId;
  if (opts?.linkType) params.link_type = opts.linkType;

  const { data } = await api.get('/v1/traceability/confidence-distribution', {
    params,
    timeout: 30000,
  });
  return data as ConfidenceDistribution;
};

export const recalculateLinkConfidence = async (
  opts?: { projectId?: number; linkType?: string; linkIds?: number[] }
): Promise<RecalculateConfidenceResult> => {
  const body: Record<string, unknown> = {};
  if (opts?.projectId !== undefined) body.project_id = opts.projectId;
  if (opts?.linkType) body.link_type = opts.linkType;
  if (opts?.linkIds) body.link_ids = opts.linkIds;

  const { data } = await api.post('/v1/traceability/recalculate-confidence', body, {
    timeout: 60000,
  });
  return data as RecalculateConfidenceResult;
};

// =============================================================================
// Suggested Links (Auto-linking)
// =============================================================================

export const generateSuggestedLinks = async (
  opts?: { projectId?: number; artifactTypes?: string[]; minSimilarity?: number; maxPerArtifact?: number }
): Promise<GenerateSuggestionsResult> => {
  const body: Record<string, unknown> = {};
  if (opts?.projectId !== undefined) body.project_id = opts.projectId;
  if (opts?.artifactTypes) body.artifact_types = opts.artifactTypes;
  if (opts?.minSimilarity !== undefined) body.min_similarity = opts.minSimilarity;
  if (opts?.maxPerArtifact !== undefined) body.max_per_artifact = opts.maxPerArtifact;

  const { data } = await api.post('/v1/traceability/suggested-links/generate', body, {
    timeout: 120000, // 2 minutes for TF-IDF processing
  });
  return data as GenerateSuggestionsResult;
};

export const getSuggestedLinks = async (
  opts?: { projectId?: number; status?: string; minScore?: number; limit?: number; offset?: number }
): Promise<SuggestedLinksResponse> => {
  const params: Record<string, unknown> = {};
  if (opts?.projectId !== undefined) params.project_id = opts.projectId;
  if (opts?.status) params.status = opts.status;
  if (opts?.minScore !== undefined) params.min_score = opts.minScore;
  const offset = opts?.offset ?? 0;
  const limit = opts?.limit ?? DEFAULT_PAGE_SIZE;
  params.limit = limit;
  params.offset = offset;

  const { data } = await api.get('/v1/traceability/suggested-links', {
    params,
    timeout: 30000,
  });
  return normalizePaginatedResponse<SuggestedLink>(data, {
    skip: offset,
    limit,
    legacyKey: 'suggestions',
  });
};

export const getSuggestedLinksStats = async (
  opts?: { projectId?: number }
): Promise<SuggestedLinksStats> => {
  const params: Record<string, unknown> = {};
  if (opts?.projectId !== undefined) params.project_id = opts.projectId;

  const { data } = await api.get('/v1/traceability/suggested-links/stats', { params });
  return data as SuggestedLinksStats;
};

export const approveSuggestedLink = async (
  suggestionId: number,
  note?: string
): Promise<void> => {
  const params: Record<string, unknown> = {};
  if (note) params.note = note;
  await api.post(`/v1/traceability/suggested-links/${suggestionId}/approve`, undefined, {
    params,
  });
};

export const rejectSuggestedLink = async (
  suggestionId: number,
  note?: string
): Promise<void> => {
  const params: Record<string, unknown> = {};
  if (note) params.note = note;
  await api.post(`/v1/traceability/suggested-links/${suggestionId}/reject`, undefined, {
    params,
  });
};

export const bulkApproveSuggestedLinks = async (
  suggestionIds: number[]
): Promise<{ approved: number; created_links: number }> => {
  const { data } = await api.post('/v1/traceability/suggested-links/bulk-approve', {
    suggestion_ids: suggestionIds,
  });
  return data;
};

// =============================================================================
// Sync Health
// =============================================================================

export const getSyncHealth = async (
  opts?: { projectId?: number }
): Promise<SyncHealthResponse> => {
  const params: Record<string, unknown> = {};
  if (opts?.projectId !== undefined) params.project_id = opts.projectId;

  const { data } = await api.get('/v1/traceability/sync-health', {
    params,
    timeout: 30000,
  });
  return data as SyncHealthResponse;
};

export const getDetailedSyncHealth = async (
  projectId: number
): Promise<DetailedSyncHealthResponse> => {
  const { data } = await api.get('/v1/traceability/sync-health/detailed', {
    params: { project_id: projectId },
    timeout: 30000,
  });
  return data as DetailedSyncHealthResponse;
};

// =============================================================================
// Consistency Checks
// =============================================================================

export const runConsistencyCheck = async (
  opts?: {
    projectId?: number;
    checkOrphans?: boolean;
    checkCycles?: boolean;
    checkDuplicates?: boolean;
    checkBrokenRefs?: boolean;
    checkStale?: boolean;
    staleDays?: number;
  }
): Promise<ConsistencyCheckResponse> => {
  const params: Record<string, unknown> = {};
  if (opts?.projectId !== undefined) params.project_id = opts.projectId;
  if (opts?.checkOrphans !== undefined) params.check_orphans = opts.checkOrphans;
  if (opts?.checkCycles !== undefined) params.check_cycles = opts.checkCycles;
  if (opts?.checkDuplicates !== undefined) params.check_duplicates = opts.checkDuplicates;
  if (opts?.checkBrokenRefs !== undefined) params.check_broken_refs = opts.checkBrokenRefs;
  if (opts?.checkStale !== undefined) params.check_stale = opts.checkStale;
  if (opts?.staleDays !== undefined) params.stale_days = opts.staleDays;

  const { data } = await api.get('/v1/traceability/consistency-check', {
    params,
    timeout: 60000, // 1 minute for comprehensive check
  });
  return data as ConsistencyCheckResponse;
};

export const fixConsistencyIssues = async (
  opts?: {
    projectId?: number;
    fixBrokenRefs?: boolean;
    fixDuplicates?: boolean;
    dryRun?: boolean;
  }
): Promise<FixConsistencyResult> => {
  const params: Record<string, unknown> = {};
  if (opts?.projectId !== undefined) params.project_id = opts.projectId;
  if (opts?.fixBrokenRefs !== undefined) params.fix_broken_refs = opts.fixBrokenRefs;
  if (opts?.fixDuplicates !== undefined) params.fix_duplicates = opts.fixDuplicates;
  if (opts?.dryRun !== undefined) params.dry_run = opts.dryRun;

  const { data } = await api.post('/v1/traceability/consistency-check/fix', undefined, {
    params,
    timeout: 60000,
  });
  return data as FixConsistencyResult;
};

export const getDetailedCycles = async (
  opts?: { projectId?: number; linkType?: string }
): Promise<DetailedCyclesResponse> => {
  const params: Record<string, unknown> = {};
  if (opts?.projectId !== undefined) params.project_id = opts.projectId;
  if (opts?.linkType) params.link_type = opts.linkType;

  const { data } = await api.get('/v1/traceability/consistency-check/cycles', {
    params,
    timeout: 60000,
  });
  return data as DetailedCyclesResponse;
};

// =============================================================================
// Traceability Rules CRUD
// =============================================================================

/**
 * List traceability rules with optional filtering
 */
export const getRules = async (
  opts?: ListRulesOptions
): Promise<TraceabilityRuleListResponse> => {
  const params: Record<string, unknown> = {};
  if (opts?.enabled !== undefined) params.enabled = opts.enabled;
  if (opts?.category) params.category = opts.category;
  if (opts?.projectId !== undefined) params.project_id = opts.projectId;
  const offset = opts?.offset ?? 0;
  const limit = opts?.limit ?? DEFAULT_PAGE_SIZE;
  params.limit = limit;
  params.offset = offset;

  const { data } = await withRetry(
    () => api.get('/v1/traceability/rules', { params, timeout: 30000 }),
    { retries: 2, baseDelayMs: 500, maxDelayMs: 3000 }
  );
  return normalizePaginatedResponse<TraceabilityRule>(data, {
    skip: offset,
    limit,
    legacyKey: 'items',
  });
};

/**
 * Get a single traceability rule by ID
 */
export const getRule = async (ruleId: number): Promise<TraceabilityRule> => {
  const { data } = await withRetry(
    () => api.get(`/v1/traceability/rules/${ruleId}`, { timeout: 20000 }),
    { retries: 1, baseDelayMs: 400, maxDelayMs: 2500 }
  );
  return data as TraceabilityRule;
};

/**
 * Create a new traceability rule
 */
export const createRule = async (
  ruleData: TraceabilityRuleCreate
): Promise<TraceabilityRule> => {
  const { data } = await api.post('/v1/traceability/rules', ruleData, {
    timeout: 30000,
  });
  return data as TraceabilityRule;
};

/**
 * Update an existing traceability rule
 */
export const updateRule = async (
  ruleId: number,
  ruleData: TraceabilityRuleUpdate
): Promise<TraceabilityRule> => {
  const { data } = await api.put(`/v1/traceability/rules/${ruleId}`, ruleData, {
    timeout: 30000,
  });
  return data as TraceabilityRule;
};

/**
 * Delete a traceability rule
 */
export const deleteRule = async (ruleId: number): Promise<void> => {
  await api.delete(`/v1/traceability/rules/${ruleId}`, { timeout: 20000 });
};

/**
 * Execute a traceability rule
 */
export const executeRule = async (
  ruleId: number,
  opts?: { executionContext?: Record<string, unknown> }
): Promise<RuleExecutionResult> => {
  const body = opts?.executionContext ? { execution_context: opts.executionContext } : undefined;
  const { data } = await api.post(`/v1/traceability/rules/${ruleId}/execute`, body, {
    timeout: 120000, // 2 minutes for rule execution
  });
  return data as RuleExecutionResult;
};

/**
 * Get execution history for a specific rule
 */
export const getRuleExecutions = async (
  ruleId: number,
  opts?: { limit?: number; offset?: number }
): Promise<TraceabilityRuleExecutionListResponse> => {
  const params: Record<string, unknown> = {};
  const offset = opts?.offset ?? 0;
  const limit = opts?.limit ?? DEFAULT_PAGE_SIZE;
  params.limit = limit;
  params.offset = offset;

  const { data } = await withRetry(
    () => api.get(`/v1/traceability/rules/${ruleId}/executions`, { params, timeout: 30000 }),
    { retries: 1, baseDelayMs: 400, maxDelayMs: 2500 }
  );
  return normalizePaginatedResponse<TraceabilityRuleExecution>(data, {
    skip: offset,
    limit,
    legacyKey: 'items',
  });
};

/**
 * Get all rule executions across all rules
 */
export const getAllRuleExecutions = async (
  opts?: ListRuleExecutionsOptions
): Promise<TraceabilityRuleExecutionListResponse> => {
  const params: Record<string, unknown> = {};
  if (opts?.ruleId !== undefined) params.rule_id = opts.ruleId;
  if (opts?.status) params.status = opts.status;
  const offset = opts?.offset ?? 0;
  const limit = opts?.limit ?? DEFAULT_PAGE_SIZE;
  params.limit = limit;
  params.offset = offset;

  const { data } = await withRetry(
    () => api.get('/v1/traceability/rules/executions', { params, timeout: 30000 }),
    { retries: 2, baseDelayMs: 500, maxDelayMs: 3000 }
  );
  return normalizePaginatedResponse<TraceabilityRuleExecution>(data, {
    skip: offset,
    limit,
    legacyKey: 'items',
  });
};
