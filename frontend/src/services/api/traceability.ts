/**
 * Traceability APIs - Matrix, flows, chains, impact analysis, sync health.
 */
import api, { withRetry } from './client';
import { AxiosRequestConfig } from 'axios';
import { DEFAULT_PAGE_SIZE } from './types';
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
  FlowValidationResult,
  RuleScheduleResponse,
  RuleScheduleUpdate,
  RuleWebhookResponse,
  // RTM Matrix types
  RTMFilters,
  RTMPagination,
  RTMMatrixResponse,
  MatrixConfig,
  MatrixConfigCreate,
  MatrixConfigUpdate,
  ExportTaskCreate,
  ExportTaskStatus,
} from './types';
import { normalizePaginatedResponse } from './pagination';

const CONFIDENCE_RANGES = ['0.0-0.2', '0.2-0.4', '0.4-0.6', '0.6-0.8', '0.8-1.0'] as const;

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' ? (value as Record<string, unknown>) : {};

const asFiniteNumber = (value: unknown, fallback = 0): number =>
  typeof value === 'number' && Number.isFinite(value) ? value : fallback;

const rangeMidpoint = (range: string): number => {
  const [startRaw, endRaw] = range.split('-');
  const start = Number(startRaw);
  const end = Number(endRaw);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return 0;
  return (start + end) / 2;
};

const toHistogram = (rawHistogram: unknown): { range: string; count: number }[] => {
  if (Array.isArray(rawHistogram)) {
    return rawHistogram.map((item) => {
      const bucket = asRecord(item);
      return {
        range: String(bucket.range || ''),
        count: asFiniteNumber(bucket.count, 0),
      };
    });
  }

  const histogramRecord = asRecord(rawHistogram);
  return CONFIDENCE_RANGES.map((range) => ({
    range,
    count: asFiniteNumber(histogramRecord[range], 0),
  }));
};

const normalizeConfidenceDistribution = (raw: unknown): ConfidenceDistribution => {
  const payload = asRecord(raw);
  const histogram = toHistogram(payload.histogram);
  const totalFromHistogram = histogram.reduce((sum, item) => sum + item.count, 0);

  const byLinkTypeRaw = asRecord(payload.by_link_type);
  const byLinkType: Record<string, { count: number; avg_confidence: number }> = {};
  let weightedConfidenceSum = 0;
  let weightedConfidenceCount = 0;

  Object.entries(byLinkTypeRaw).forEach(([linkType, value]) => {
    const row = asRecord(value);
    const count = asFiniteNumber(row.count, 0);
    const avgFromField = row.avg_confidence;
    const avg = typeof avgFromField === 'number' && Number.isFinite(avgFromField)
      ? avgFromField
      : asFiniteNumber(row.avg, 0);

    byLinkType[linkType] = {
      count,
      avg_confidence: avg,
    };

    if (count > 0 && Number.isFinite(avg)) {
      weightedConfidenceSum += avg * count;
      weightedConfidenceCount += count;
    }
  });

  const statsRaw = asRecord(payload.stats);
  const totalLinks = asFiniteNumber(
    statsRaw.total_links,
    asFiniteNumber(payload.total, totalFromHistogram)
  );
  const avgConfidence = asFiniteNumber(
    statsRaw.avg_confidence,
    weightedConfidenceCount > 0 ? weightedConfidenceSum / weightedConfidenceCount : 0
  );

  const sortedHistogram = [...histogram].sort((a, b) => rangeMidpoint(a.range) - rangeMidpoint(b.range));
  const scoredCount = sortedHistogram.reduce((sum, item) => sum + item.count, 0);
  let medianConfidence = asFiniteNumber(statsRaw.median_confidence, 0);
  if (medianConfidence === 0 && scoredCount > 0) {
    const midpoint = scoredCount / 2;
    let cumulative = 0;
    for (const bucket of sortedHistogram) {
      cumulative += bucket.count;
      if (cumulative >= midpoint) {
        medianConfidence = rangeMidpoint(bucket.range);
        break;
      }
    }
  }

  let minConfidence = asFiniteNumber(statsRaw.min_confidence, 0);
  let maxConfidence = asFiniteNumber(statsRaw.max_confidence, 0);
  if (minConfidence === 0 && maxConfidence === 0) {
    const nonZero = sortedHistogram.filter((item) => item.count > 0);
    if (nonZero.length > 0) {
      const [minRangeStartRaw] = nonZero[0].range.split('-');
      const [, maxRangeEndRaw] = nonZero[nonZero.length - 1].range.split('-');
      minConfidence = Number(minRangeStartRaw) || 0;
      maxConfidence = Number(maxRangeEndRaw) || 0;
    }
  }

  return {
    histogram,
    stats: {
      total_links: totalLinks,
      avg_confidence: avgConfidence,
      median_confidence: medianConfidence,
      min_confidence: minConfidence,
      max_confidence: maxConfidence,
    },
    by_link_type: byLinkType,
  };
};

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
  return normalizeConfidenceDistribution(data);
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

const resolveSkip = (opts?: { skip?: number; offset?: number }): number =>
  opts?.skip ?? opts?.offset ?? 0;

/**
 * Validate a flow without saving it.
 */
export const validateRuleFlow = async (
  flowJson: TraceabilityRuleCreate['flow_json']
): Promise<FlowValidationResult> => {
  const { data } = await api.post('/v1/traceability/rules/validate', { flow_json: flowJson }, {
    timeout: 30000,
  });
  return data as FlowValidationResult;
};

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
  const skip = resolveSkip(opts);
  const limit = opts?.limit ?? DEFAULT_PAGE_SIZE;
  params.limit = limit;
  params.skip = skip;

  const { data } = await withRetry(
    () => api.get('/v1/traceability/rules', { params, timeout: 30000 }),
    { retries: 2, baseDelayMs: 500, maxDelayMs: 3000 }
  );
  return normalizePaginatedResponse<TraceabilityRule>(data, {
    skip,
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
  opts?: { limit?: number; skip?: number; offset?: number }
): Promise<TraceabilityRuleExecutionListResponse> => {
  const params: Record<string, unknown> = {};
  const skip = resolveSkip(opts);
  const limit = opts?.limit ?? DEFAULT_PAGE_SIZE;
  params.limit = limit;
  params.skip = skip;

  const { data } = await withRetry(
    () => api.get(`/v1/traceability/rules/${ruleId}/executions`, { params, timeout: 30000 }),
    { retries: 1, baseDelayMs: 400, maxDelayMs: 2500 }
  );
  return normalizePaginatedResponse<TraceabilityRuleExecution>(data, {
    skip,
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
  const skip = resolveSkip(opts);
  const limit = opts?.limit ?? DEFAULT_PAGE_SIZE;
  params.limit = limit;
  params.skip = skip;

  const { data } = await withRetry(
    () => api.get('/v1/traceability/rules/executions', { params, timeout: 30000 }),
    { retries: 2, baseDelayMs: 500, maxDelayMs: 3000 }
  );
  return normalizePaginatedResponse<TraceabilityRuleExecution>(data, {
    skip,
    limit,
    legacyKey: 'items',
  });
};

/**
 * Get schedule settings for a saved rule.
 */
export const getRuleSchedule = async (ruleId: number): Promise<RuleScheduleResponse> => {
  const { data } = await api.get(`/v1/traceability/rules/${ruleId}/schedule`, {
    timeout: 20000,
  });
  return data as RuleScheduleResponse;
};

/**
 * Update schedule settings for a saved rule.
 */
export const updateRuleSchedule = async (
  ruleId: number,
  payload: RuleScheduleUpdate
): Promise<RuleScheduleResponse> => {
  const { data } = await api.put(`/v1/traceability/rules/${ruleId}/schedule`, payload, {
    timeout: 30000,
  });
  return data as RuleScheduleResponse;
};

/**
 * Get webhook status for a saved rule.
 */
export const getRuleWebhook = async (ruleId: number): Promise<RuleWebhookResponse> => {
  const { data } = await api.get(`/v1/traceability/rules/${ruleId}/webhook`, {
    timeout: 20000,
  });
  return data as RuleWebhookResponse;
};

/**
 * Enable webhook and return one-time token.
 */
export const enableRuleWebhook = async (ruleId: number): Promise<RuleWebhookResponse> => {
  const { data } = await api.post(`/v1/traceability/rules/${ruleId}/webhook/enable`, undefined, {
    timeout: 30000,
  });
  return data as RuleWebhookResponse;
};

/**
 * Disable webhook and clear token.
 */
export const disableRuleWebhook = async (ruleId: number): Promise<RuleWebhookResponse> => {
  const { data } = await api.post(`/v1/traceability/rules/${ruleId}/webhook/disable`, undefined, {
    timeout: 30000,
  });
  return data as RuleWebhookResponse;
};

// =============================================================================
// RTM Matrix (Full Grid with Pagination/Filters)
// =============================================================================

/**
 * Map frontend direction values to backend direction values.
 * Frontend uses row_to_col/col_to_row, backend expects outgoing/incoming.
 */
const mapDirection = (
  direction?: 'both' | 'row_to_col' | 'col_to_row'
): 'both' | 'outgoing' | 'incoming' | undefined => {
  if (!direction) return undefined;
  if (direction === 'row_to_col') return 'outgoing';
  if (direction === 'col_to_row') return 'incoming';
  return direction;
};

/**
 * Get RTM matrix with server-side pagination and filters (GET method).
 * Use for simple queries with comma-separated params.
 */
export const getRTMMatrix = async (
  opts?: {
    projectId?: number;
    rowTypes?: string[];
    colTypes?: string[];
    rowStatuses?: string[];
    colStatuses?: string[];
    linkTypes?: string[];
    minConfidence?: number;
    direction?: 'both' | 'row_to_col' | 'col_to_row';
    searchQuery?: string;
    includeOrphans?: boolean;
    rowSkip?: number;
    rowLimit?: number;
    colSkip?: number;
    colLimit?: number;
  }
): Promise<RTMMatrixResponse> => {
  const params: Record<string, unknown> = {};
  if (opts?.projectId !== undefined) params.project_id = opts.projectId;
  if (opts?.rowTypes?.length) params.row_types = opts.rowTypes.join(',');
  if (opts?.colTypes?.length) params.col_types = opts.colTypes.join(',');
  if (opts?.rowStatuses?.length) params.row_statuses = opts.rowStatuses.join(',');
  if (opts?.colStatuses?.length) params.col_statuses = opts.colStatuses.join(',');
  if (opts?.linkTypes?.length) params.link_types = opts.linkTypes.join(',');
  if (opts?.minConfidence !== undefined) params.min_confidence = opts.minConfidence;
  if (opts?.direction) params.direction = mapDirection(opts.direction);
  if (opts?.searchQuery) params.search_query = opts.searchQuery;
  if (opts?.includeOrphans !== undefined) params.include_orphans = opts.includeOrphans;
  if (opts?.rowSkip !== undefined) params.row_skip = opts.rowSkip;
  if (opts?.rowLimit !== undefined) params.row_limit = opts.rowLimit;
  if (opts?.colSkip !== undefined) params.col_skip = opts.colSkip;
  if (opts?.colLimit !== undefined) params.col_limit = opts.colLimit;

  const { data } = await withRetry(
    () => api.get('/v1/traceability/rtm-matrix', { params, timeout: 60000 }),
    { retries: 2, baseDelayMs: 500, maxDelayMs: 3000 }
  );
  return data as RTMMatrixResponse;
};

/**
 * Query RTM matrix with full filter/pagination body (POST method).
 * Use for complex queries with array filters.
 */
export const queryRTMMatrix = async (
  filters: RTMFilters,
  pagination?: RTMPagination,
  projectId?: number,
  includeLinkDetails?: boolean
): Promise<RTMMatrixResponse> => {
  // Map frontend direction values to backend values
  const mappedFilters = {
    ...filters,
    direction: filters.direction ? mapDirection(filters.direction as 'both' | 'row_to_col' | 'col_to_row') : undefined,
  };

  // project_id and include_link_details go as query params
  const params: Record<string, unknown> = {};
  if (projectId !== undefined) params.project_id = projectId;
  // Only send include_link_details when explicitly true
  if (includeLinkDetails) params.include_link_details = true;

  const body: Record<string, unknown> = {
    filters: mappedFilters,
    pagination,
  };

  const { data } = await withRetry(
    () => api.post(
      '/v1/traceability/rtm-matrix/query',
      body,
      {
        params,
        timeout: 60000,
      }
    ),
    { retries: 2, baseDelayMs: 500, maxDelayMs: 3000 }
  );
  return data as RTMMatrixResponse;
};

// =============================================================================
// Matrix Configurations (Saved Projections)
// =============================================================================

/**
 * List saved matrix configurations for a project.
 */
export const listMatrixConfigs = async (
  opts?: { projectId?: number }
): Promise<MatrixConfig[]> => {
  const params: Record<string, unknown> = {};
  if (opts?.projectId !== undefined) params.project_id = opts.projectId;

  const { data } = await api.get('/v1/traceability/matrix-configs', { params, timeout: 30000 });
  return data as MatrixConfig[];
};

/**
 * Get a single matrix configuration by ID.
 */
export const getMatrixConfig = async (configId: number): Promise<MatrixConfig> => {
  const { data } = await api.get(`/v1/traceability/matrix-configs/${configId}`, { timeout: 20000 });
  return data as MatrixConfig;
};

/**
 * Create a new matrix configuration (saved projection).
 */
export const createMatrixConfig = async (payload: MatrixConfigCreate): Promise<MatrixConfig> => {
  const { data } = await api.post('/v1/traceability/matrix-configs', payload, { timeout: 30000 });
  return data as MatrixConfig;
};

/**
 * Update an existing matrix configuration.
 */
export const updateMatrixConfig = async (
  configId: number,
  payload: MatrixConfigUpdate
): Promise<MatrixConfig> => {
  const { data } = await api.patch(`/v1/traceability/matrix-configs/${configId}`, payload, {
    timeout: 30000,
  });
  return data as MatrixConfig;
};

/**
 * Delete a matrix configuration.
 */
export const deleteMatrixConfig = async (configId: number): Promise<void> => {
  await api.delete(`/v1/traceability/matrix-configs/${configId}`, { timeout: 20000 });
};

/**
 * Apply a saved matrix configuration and get the resulting matrix.
 */
export const applyMatrixConfig = async (
  configId: number,
  opts?: { includeLinkDetails?: boolean }
): Promise<RTMMatrixResponse> => {
  const params: Record<string, unknown> = {};
  if (opts?.includeLinkDetails !== undefined) params.include_link_details = opts.includeLinkDetails;

  const { data } = await api.get(`/v1/traceability/matrix-configs/${configId}/apply`, {
    params,
    timeout: 60000,
  });
  return data as RTMMatrixResponse;
};

// =============================================================================
// Matrix Export
// =============================================================================

/**
 * Create an export task for the RTM matrix.
 * Returns immediately with a task_id for tracking progress.
 */
export const createMatrixExport = async (
  payload: ExportTaskCreate
): Promise<ExportTaskStatus> => {
  const { data } = await api.post('/v1/traceability/exports', payload, {
    timeout: 30000,
  });
  return data as ExportTaskStatus;
};

/**
 * Get the status of an export task.
 */
export const getExportStatus = async (taskId: string): Promise<ExportTaskStatus> => {
  const { data } = await api.get(`/v1/traceability/exports/${taskId}`, {
    timeout: 10000,
  });
  return data as ExportTaskStatus;
};

/**
 * List export tasks for a project.
 */
export const listExports = async (
  opts?: { projectId?: number; status?: string; limit?: number }
): Promise<ExportTaskStatus[]> => {
  const params: Record<string, unknown> = {};
  if (opts?.projectId !== undefined) params.project_id = opts.projectId;
  if (opts?.status !== undefined) params.status = opts.status;
  if (opts?.limit !== undefined) params.limit = opts.limit;

  const { data } = await api.get('/v1/traceability/exports', { params, timeout: 30000 });
  return data as ExportTaskStatus[];
};

/**
 * Delete an export task.
 */
export const deleteExport = async (taskId: string): Promise<void> => {
  await api.delete(`/v1/traceability/exports/${taskId}`, { timeout: 10000 });
};

/**
 * Get download URL for a completed export.
 */
export const getExportDownloadUrl = (taskId: string): string => {
  return `/api/v1/traceability/exports/${taskId}/download`;
};
