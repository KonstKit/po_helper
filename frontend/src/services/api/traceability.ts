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

const asStringOrNull = (value: unknown): string | null =>
  typeof value === 'string' ? value : null;

const asPercent = (value: unknown, fallback = 0): number => {
  const num = asFiniteNumber(value, fallback);
  if (num >= 0 && num <= 1) return num * 100;
  return num;
};

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
// Sync Health Normalization
// =============================================================================

const toOverallHealthStatus = (
  value: unknown
): SyncHealthResponse['health'] => {
  return value === 'healthy' || value === 'warning' || value === 'critical'
    ? value
    : 'warning';
};

const computeProjectHealthStatus = (
  base: unknown,
  lastSync: string | null,
  artifactCount: number
): DetailedSyncHealthResponse['health_status'] => {
  const baseStatus = base === 'healthy' || base === 'warning' || base === 'critical'
    ? base
    : 'unknown';

  if (lastSync) {
    const date = new Date(lastSync);
    if (Number.isFinite(date.getTime())) {
      const days = (Date.now() - date.getTime()) / 86_400_000;
      if (days > 7) {
        return 'stale';
      }
    }
  }

  if (artifactCount === 0 && baseStatus === 'healthy') {
    return 'warning';
  }

  return baseStatus;
};

const normalizeSyncHealth = (raw: unknown): SyncHealthResponse => {
  const payload = asRecord(raw);

  // Legacy/expected shape: health is a string, health_score is a number.
  if (typeof payload.health === 'string' && typeof payload.health_score === 'number') {
    const summaryRaw = asRecord(payload.summary);
    const sourcesRaw = Array.isArray(payload.sources) ? payload.sources : [];
    const projectsRaw = Array.isArray(payload.projects) ? payload.projects : [];

    return {
      health: toOverallHealthStatus(payload.health),
      health_score: asFiniteNumber(payload.health_score, 0),
      summary: {
        total_sources: asFiniteNumber(summaryRaw.total_sources, 0),
        connected_sources: asFiniteNumber(summaryRaw.connected_sources, 0),
        total_artifacts: asFiniteNumber(summaryRaw.total_artifacts, 0),
        last_sync: asStringOrNull(summaryRaw.last_sync),
      },
      sources: sourcesRaw
        .map((item) => {
          const row = asRecord(item);
          const source = typeof row.source === 'string' ? row.source : '';
          const connected = typeof row.connected === 'boolean'
            ? row.connected
            : row.status === 'connected';
          return {
            source,
            connected,
            last_sync: asStringOrNull(row.last_sync),
            artifact_count: asFiniteNumber(row.artifact_count, 0),
            error: asStringOrNull(row.error),
          };
        })
        .filter((s) => s.source.length > 0),
      projects: projectsRaw
        .map((item) => {
          const row = asRecord(item);
          const projectId = asFiniteNumber(row.project_id, asFiniteNumber(row.id, 0));
          const projectName = typeof row.project_name === 'string'
            ? row.project_name
            : typeof row.name === 'string'
              ? row.name
              : '';
          const jiraKey = typeof row.jira_key === 'string' ? row.jira_key : '';
          const lastSync = asStringOrNull(row.last_sync ?? row.last_sync_at);
          const artifactCount = asFiniteNumber(row.artifact_count, 0);
          return {
            project_id: projectId,
            project_name: projectName,
            jira_key: jiraKey,
            last_sync: lastSync,
            artifact_count: artifactCount,
            health_status: computeProjectHealthStatus(row.health_status, lastSync, artifactCount),
          };
        })
        .filter((p) => p.project_id > 0),
    };
  }

  // Current backend shape (Feb 2026): health is an object {status, score, ...}
  const healthRaw = asRecord(payload.health);
  const summaryRaw = asRecord(payload.summary);

  const sourcesRaw = Array.isArray(payload.sources) ? payload.sources : [];
  const sources = sourcesRaw
    .map((item) => {
      const row = asRecord(item);
      const source = typeof row.source === 'string' ? row.source : '';
      const status = typeof row.status === 'string' ? row.status : '';
      const connected = typeof row.connected === 'boolean' ? row.connected : status === 'connected';

      let error = asStringOrNull(row.error);
      if (!error && !connected && status) {
        error = status === 'not_configured' ? 'Not configured' : status;
      }

      return {
        source,
        connected,
        last_sync: asStringOrNull(row.last_sync),
        artifact_count: asFiniteNumber(row.artifact_count, 0),
        error,
      };
    })
    .filter((s) => s.source.length > 0);

  const health = toOverallHealthStatus(healthRaw.status ?? payload.health);
  const healthScore = asPercent(healthRaw.score ?? payload.health_score, 0);

  const totalArtifacts = asFiniteNumber(summaryRaw.total_artifacts, 0);

  const lastSyncCandidates = sources
    .map((s) => s.last_sync)
    .filter((v): v is string => typeof v === 'string' && v.length > 0);
  const lastSync = lastSyncCandidates.length > 0
    ? lastSyncCandidates
      .map((value) => ({ value, date: new Date(value) }))
      .filter((row) => Number.isFinite(row.date.getTime()))
      .sort((a, b) => a.date.getTime() - b.date.getTime())
      .at(-1)?.value ?? null
    : null;

  const connectedSources = asFiniteNumber(
    healthRaw.connected_sources,
    sources.filter((s) => s.connected).length
  );
  const totalSources = asFiniteNumber(healthRaw.total_sources, sources.length);

  const projectsRaw = Array.isArray(payload.projects) ? payload.projects : [];
  const artifactCountFallback = projectsRaw.length === 1 ? totalArtifacts : 0;

  const projects = projectsRaw
    .map((item) => {
      const row = asRecord(item);
      const projectId = asFiniteNumber(row.project_id, asFiniteNumber(row.id, 0));
      const projectName = typeof row.project_name === 'string'
        ? row.project_name
        : typeof row.name === 'string'
          ? row.name
          : '';
      const jiraKey = typeof row.jira_key === 'string' ? row.jira_key : '';
      const lastSync = asStringOrNull(row.last_sync ?? row.last_sync_at);
      const artifactCount = asFiniteNumber(row.artifact_count, artifactCountFallback);

      return {
        project_id: projectId,
        project_name: projectName,
        jira_key: jiraKey,
        last_sync: lastSync,
        artifact_count: artifactCount,
        health_status: computeProjectHealthStatus(health, lastSync, artifactCount),
      };
    })
    .filter((p) => p.project_id > 0);

  return {
    health,
    health_score: healthScore,
    summary: {
      total_sources: totalSources,
      connected_sources: connectedSources,
      total_artifacts: totalArtifacts,
      last_sync: lastSync,
    },
    sources,
    projects,
  };
};

const normalizeDetailedSyncHealth = (raw: unknown): DetailedSyncHealthResponse => {
  const payload = asRecord(raw);

  // Legacy/expected shape
  if (typeof payload.project_id === 'number' && payload.link_coverage && payload.by_type && payload.by_source) {
    return payload as DetailedSyncHealthResponse;
  }

  const projectRaw = asRecord(payload.project);
  const artifactsRaw = asRecord(payload.artifacts);
  const coverageRaw = asRecord(payload.coverage);

  const projectId = asFiniteNumber(projectRaw.id ?? payload.project_id, 0);
  const projectName = typeof projectRaw.name === 'string'
    ? projectRaw.name
    : typeof payload.project_name === 'string'
      ? payload.project_name
      : '';
  const jiraKey = typeof projectRaw.jira_key === 'string'
    ? projectRaw.jira_key
    : typeof payload.jira_key === 'string'
      ? payload.jira_key
      : '';
  const lastSync = asStringOrNull(projectRaw.last_sync_at ?? payload.last_sync);

  const byTypeRaw = asRecord(artifactsRaw.by_type ?? payload.by_type);
  const byType: Record<string, number> = {};
  Object.entries(byTypeRaw).forEach(([type, value]) => {
    const row = asRecord(value);
    byType[type] = asFiniteNumber(row.total, asFiniteNumber(value, 0));
  });

  const bySourceRaw = asRecord(artifactsRaw.by_source ?? payload.by_source);
  const bySource: Record<string, number> = {};
  Object.entries(bySourceRaw).forEach(([source, value]) => {
    const row = asRecord(value);
    bySource[source] = asFiniteNumber(row.total, asFiniteNumber(value, 0));
  });

  let totalArtifacts = asFiniteNumber(artifactsRaw.total, 0);
  if (totalArtifacts === 0) {
    totalArtifacts = Object.values(bySource).reduce((sum, value) => sum + value, 0);
  }

  const orphanedCount = asFiniteNumber(coverageRaw.orphaned_artifacts, asFiniteNumber(payload.orphaned_count, 0));
  const linkedArtifacts = asFiniteNumber(coverageRaw.linked_artifacts, 0);
  const coveragePct = totalArtifacts > 0 ? (linkedArtifacts / totalArtifacts) * 100 : 0;

  const repositoriesRaw = Array.isArray(payload.repositories) ? payload.repositories : [];
  const repositories = repositoriesRaw
    .map((item) => {
      const row = asRecord(item);
      const id = asFiniteNumber(row.id, 0);
      const provider = typeof row.provider === 'string' ? row.provider : '';
      const repoSlug = typeof row.repo_slug === 'string'
        ? row.repo_slug
        : typeof row.name === 'string'
          ? row.name
          : '';
      const defaultBranch = asStringOrNull(row.default_branch);
      return {
        id,
        provider,
        repo_slug: repoSlug,
        default_branch: defaultBranch ?? undefined,
      };
    })
    .filter((repo) => repo.id > 0 && repo.repo_slug.length > 0);

  const healthStatus = computeProjectHealthStatus('healthy', lastSync, totalArtifacts);

  return {
    project_id: projectId,
    project_name: projectName,
    jira_key: jiraKey,
    last_sync: lastSync,
    health_status: healthStatus,
    by_type: byType,
    by_source: bySource,
    link_coverage: {
      total_artifacts: totalArtifacts,
      linked_artifacts: linkedArtifacts,
      coverage_pct: coveragePct,
    },
    orphaned_count: orphanedCount,
    repositories,
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
  return normalizeSyncHealth(data);
};

export const getDetailedSyncHealth = async (
  projectId: number
): Promise<DetailedSyncHealthResponse> => {
  const { data } = await api.get('/v1/traceability/sync-health/detailed', {
    params: { project_id: projectId },
    timeout: 30000,
  });
  return normalizeDetailedSyncHealth(data);
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
