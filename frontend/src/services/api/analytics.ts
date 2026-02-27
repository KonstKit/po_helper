/**
 * Analytics APIs - Velocity, burndown, risks, forecast, DORA, trends, PR metrics, quality gates.
 */
import api, { CACHE_TTL, withRetry } from './client';
import { storage } from '../../utils/storage';
import { deduplicateRequest } from '../../utils/apiOptimization';
import {
  normalizeBurndownResponse,
  normalizeVelocityResponse,
} from './contractNormalization';
import type {
  PRMetricsSummary,
  TeamHealthMetrics,
  VelocityResponse,
  BurndownResponse,
  RisksResponse,
  ForecastResponse,
  TeamMemberActivity,
  DoraMetrics,
  QualityHistoryItem,
  PullRequestsResponse,
  QualityGateResult,
  QualityGateAssessment,
  QualityGateProvider,
  GetPRMetricsOptions,
} from './types';
import type { IntegrationStatusResponse } from './integrations';

export type { DoraMetrics, QualityGateAssessment, GetPRMetricsOptions } from './types';

// =============================================================================
// Cache Key Helper
// =============================================================================

const makeCacheKey = (prefix: string, params?: Record<string, unknown>): string => {
  if (!params || Object.keys(params).length === 0) return prefix;
  const sorted = Object.entries(params)
    .filter(([, v]) => v !== undefined)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => `${k}=${v}`)
    .join('&');
  return sorted ? `${prefix}?${sorted}` : prefix;
};

// =============================================================================
// Project Analytics (Velocity, Burndown, Risks, Forecast)
// =============================================================================

export const getVelocity = async (
  projectId: number,
  opts?: { sprintsCount?: number; signal?: AbortSignal }
): Promise<VelocityResponse> => {
  const cacheKey = makeCacheKey(`velocity_${projectId}`, { sprints_count: opts?.sprintsCount });
  const cached = storage.get<VelocityResponse>(cacheKey);
  if (cached !== null) return cached;

  if (opts?.signal) {
    const { data } = await api.get(`/v1/analytics/projects/${projectId}/velocity`, {
      params: { sprints_count: opts.sprintsCount },
      signal: opts.signal,
    });
    const normalized = normalizeVelocityResponse(data);
    storage.set(cacheKey, normalized, { ttl: CACHE_TTL * 2 });
    return normalized;
  }

  return deduplicateRequest(cacheKey, async () => {
    const { data } = await api.get(`/v1/analytics/projects/${projectId}/velocity`, {
      params: { sprints_count: opts?.sprintsCount },
    });
    const normalized = normalizeVelocityResponse(data);
    storage.set(cacheKey, normalized, { ttl: CACHE_TTL * 2 });
    return normalized;
  });
};

export const getBurndown = async (
  projectId: number,
  sprintId?: number
): Promise<BurndownResponse> => {
  const cacheKey = makeCacheKey(`burndown_${projectId}`, { sprint_id: sprintId });
  const cached = storage.get<BurndownResponse>(cacheKey);
  if (cached !== null) return cached;

  return deduplicateRequest(cacheKey, async () => {
    const { data } = await api.get(`/v1/analytics/projects/${projectId}/burndown`, {
      params: { sprint_id: sprintId },
    });
    const normalized = normalizeBurndownResponse(data);
    storage.set(cacheKey, normalized, { ttl: CACHE_TTL });
    return normalized;
  });
};

export const getRisks = async (projectId: number): Promise<RisksResponse> => {
  const cacheKey = `risks_${projectId}`;
  const cached = storage.get<RisksResponse>(cacheKey);
  if (cached !== null) return cached;

  return deduplicateRequest(cacheKey, async () => {
    const { data } = await api.get(`/v1/analytics/projects/${projectId}/risks`);
    storage.set(cacheKey, data, { ttl: CACHE_TTL * 2 });
    return data as RisksResponse;
  });
};

export const getForecast = async (projectId: number): Promise<ForecastResponse> => {
  const cacheKey = `forecast_${projectId}`;
  const cached = storage.get<ForecastResponse>(cacheKey);
  if (cached !== null) return cached;

  return deduplicateRequest(cacheKey, async () => {
    const { data } = await api.get(`/v1/analytics/projects/${projectId}/forecast`);
    storage.set(cacheKey, data, { ttl: CACHE_TTL * 2 });
    return data as ForecastResponse;
  });
};

// =============================================================================
// DORA Metrics
// =============================================================================

export const getDoraMetrics = async (
  projectId: number,
  windowDays = 30
): Promise<DoraMetrics> => {
  const cacheKey = makeCacheKey(`dora_${projectId}`, { window_days: windowDays });
  const cached = storage.get<DoraMetrics>(cacheKey);
  if (cached !== null) return cached;

  return deduplicateRequest(cacheKey, async () => {
    const { data } = await api.get(`/v1/analytics/projects/${projectId}/dora`, {
      params: { window_days: windowDays },
    });
    storage.set(cacheKey, data, { ttl: CACHE_TTL * 3 }); // 3 min cache for DORA
    return data as DoraMetrics;
  });
};

// =============================================================================
// Team Health
// =============================================================================

export const getTeamMembersActivity = async (
  projectId: number
): Promise<TeamMemberActivity[]> => {
  const { data } = await api.get(`/v1/analytics/projects/${projectId}/team-members`);
  return data as TeamMemberActivity[];
};

export const getProjectTeamHealth = async (projectId: number): Promise<TeamHealthMetrics> => {
  const cacheKey = `team_health_${projectId}`;

  const cached = storage.get<TeamHealthMetrics>(cacheKey);
  if (cached !== null) {
    console.debug('[API] Using cached team health');
    return cached;
  }

  return deduplicateRequest(cacheKey, async () => {
    const res = await withRetry(
      () => api.get(`/v1/analytics/projects/${projectId}/team-health`, { timeout: 30000 }),
      { retries: 1, baseDelayMs: 400, maxDelayMs: 2500 }
    );
    const payload = res.data as TeamHealthMetrics;
    storage.set(cacheKey, payload, { ttl: CACHE_TTL });
    return payload;
  });
};

// =============================================================================
// Budget & Value Metrics
// =============================================================================

export interface BudgetHoursResponse {
  total_estimate_hours: number;
  total_spent_hours: number;
  remaining_hours: number;
  overrun: boolean;
  overrun_hours: number;
  top_overruns: Array<{ key: string; overrun_hours: number }>;
}

export const getProjectBudgetHours = async (
  projectId: number,
  opts?: { signal?: AbortSignal }
): Promise<BudgetHoursResponse> => {
  const cacheKey = `budget_hours_${projectId}`;

  const cached = storage.get<BudgetHoursResponse>(cacheKey);
  if (cached !== null) {
    console.debug('[API] Using cached budget hours');
    return cached;
  }

  if (opts?.signal) {
    const { data } = await api.get(`/v1/analytics/projects/${projectId}/budget-hours`, {
      timeout: 30000,
      signal: opts.signal,
    });
    storage.set(cacheKey, data, { ttl: CACHE_TTL * 2 });
    return data as BudgetHoursResponse;
  }

  return deduplicateRequest(cacheKey, async () => {
    const { data } = await api.get(`/v1/analytics/projects/${projectId}/budget-hours`, {
      timeout: 30000,
    });
    storage.set(cacheKey, data, { ttl: CACHE_TTL * 2 });
    return data as BudgetHoursResponse;
  });
};

export interface ValueMetricsResponse {
  value_delivered: number;
  total_spent_hours: number;
  roi: number;
}

export const getProjectValueMetrics = async (
  projectId: number,
  opts?: { signal?: AbortSignal }
): Promise<ValueMetricsResponse> => {
  const cacheKey = `value_metrics_${projectId}`;

  const cached = storage.get<ValueMetricsResponse>(cacheKey);
  if (cached !== null) {
    console.debug('[API] Using cached value metrics');
    return cached;
  }

  if (opts?.signal) {
    const { data } = await api.get(`/v1/analytics/projects/${projectId}/value-metrics`, {
      timeout: 30000,
      signal: opts.signal,
    });
    storage.set(cacheKey, data, { ttl: CACHE_TTL * 2 });
    return data as ValueMetricsResponse;
  }

  return deduplicateRequest(cacheKey, async () => {
    const { data } = await api.get(`/v1/analytics/projects/${projectId}/value-metrics`, {
      timeout: 30000,
    });
    storage.set(cacheKey, data, { ttl: CACHE_TTL * 2 });
    return data as ValueMetricsResponse;
  });
};

// =============================================================================
// Test & Coverage Trends
// =============================================================================

export interface TestTrendResponse {
  days: number;
  project_id?: number;
  trend: Array<{ day: string; total: number; failed: number }>;
}

export const getTestTrend = async (
  opts?: { projectId?: number; days?: number }
): Promise<TestTrendResponse> => {
  const params: Record<string, unknown> = { days: opts?.days ?? 30 };
  if (opts?.projectId !== undefined) params.project_id = opts.projectId;

  const { data } = await api.get('/v1/analytics/test-trend', { params });
  return data as TestTrendResponse;
};

export interface CoverageTrendResponse {
  days: number;
  project_id?: number;
  trend: Array<{
    day: string;
    avg_line: number;
    avg_branch: number;
    count: number;
  }>;
}

export const getCoverageTrend = async (
  opts?: { projectId?: number; days?: number }
): Promise<CoverageTrendResponse> => {
  const params: Record<string, unknown> = { days: opts?.days ?? 30 };
  if (opts?.projectId !== undefined) params.project_id = opts.projectId;

  const { data } = await api.get('/v1/analytics/coverage-trend', { params });
  return data as CoverageTrendResponse;
};

// =============================================================================
// PR Metrics
// =============================================================================

export const getPRMetrics = async (opts?: GetPRMetricsOptions): Promise<PRMetricsSummary> => {
  const params: Record<string, unknown> = {};
  if (opts?.projectId !== undefined) params.project_id = opts.projectId;
  if (opts?.provider) params.provider = opts.provider;
  if (opts?.sinceDays !== undefined) params.since_days = opts.sinceDays;
  if (opts?.limit !== undefined) params.limit = opts.limit;
  if (opts?.disableCache) params.disable_cache = 'true';

  const { data } = await api.get('/v1/git/pr-metrics', { params });
  return data as PRMetricsSummary;
};

export const listPullRequests = async (opts?: {
  projectId?: number;
  provider?: string;
  limit?: number;
}): Promise<PullRequestsResponse> => {
  const params: Record<string, unknown> = {};
  if (opts?.projectId !== undefined) params.project_id = opts.projectId;
  if (opts?.provider) params.provider = opts.provider;
  if (opts?.limit !== undefined) params.limit = opts.limit;

  const { data } = await api.get('/v1/git/pull-requests', { params });
  return data as PullRequestsResponse;
};

// =============================================================================
// Quality Gates
// =============================================================================

export const getQualityGateStatus = async (
  prNumber: number,
  opts?: { projectId?: number; minLine?: number; minBranch?: number }
): Promise<QualityGateResult> => {
  const params: Record<string, unknown> = {};
  if (opts?.projectId !== undefined) params.project_id = opts.projectId;
  if (opts?.minLine !== undefined) params.min_line = opts.minLine;
  if (opts?.minBranch !== undefined) params.min_branch = opts.minBranch;

  const { data } = await api.get(`/v1/quality/gates/${prNumber}`, { params });
  return data as QualityGateResult;
};

export interface QualityGateEvaluatePayload {
  prNumber?: number;
  commitSha?: string;
  projectId?: number;
  minLine?: number;
  minBranch?: number;
  provider?: QualityGateProvider;
}

export const evaluateQualityGate = async (
  payload: QualityGateEvaluatePayload
): Promise<QualityGateAssessment> => {
  const body: Record<string, unknown> = {};
  if (payload.prNumber !== undefined) body.pr_number = payload.prNumber;
  if (payload.commitSha !== undefined) body.commit_sha = payload.commitSha;
  if (payload.projectId !== undefined) body.project_id = payload.projectId;
  if (payload.minLine !== undefined) body.min_line = payload.minLine;
  if (payload.minBranch !== undefined) body.min_branch = payload.minBranch;
  if (payload.provider) body.provider = payload.provider;

  const { data } = await api.post('/v1/quality/gates/evaluate', body);
  return data as QualityGateAssessment;
};

export const evaluateQualityGateAndCheck = async (
  payload: QualityGateEvaluatePayload
): Promise<QualityGateAssessment> => {
  const body: Record<string, unknown> = {};
  if (payload.prNumber !== undefined) body.pr_number = payload.prNumber;
  if (payload.commitSha !== undefined) body.commit_sha = payload.commitSha;
  if (payload.projectId !== undefined) body.project_id = payload.projectId;
  if (payload.minLine !== undefined) body.min_line = payload.minLine;
  if (payload.minBranch !== undefined) body.min_branch = payload.minBranch;
  if (payload.provider) body.provider = payload.provider;

  const { data } = await api.post('/v1/quality/gates/evaluate-and-check', body);
  return data as QualityGateAssessment;
};

// =============================================================================
// Quality History
// =============================================================================

export interface QualityHistoryResponse {
  total: number;
  history: QualityHistoryItem[];
}

export const getQualityHistory = async (opts?: {
  projectId?: number;
  prNumber?: number;
  limit?: number;
}): Promise<QualityHistoryResponse> => {
  const params: Record<string, unknown> = {};
  if (opts?.projectId) params.project_id = opts.projectId;
  if (opts?.prNumber) params.pr_number = opts.prNumber;
  if (opts?.limit) params.limit = opts.limit;

  const { data } = await api.get('/v1/quality/history', { params });
  return data as QualityHistoryResponse;
};

// =============================================================================
// Health / Metrics
// =============================================================================

export const getIntegrationsHealth = async (): Promise<IntegrationStatusResponse> => {
  const { data } = await api.get('/v1/health/integrations');
  return data as IntegrationStatusResponse;
};

export const getMetricsText = async (): Promise<string> => {
  const res = await api.get('/v1/health/metrics', {
    responseType: 'text',
  });
  return res.data as string;
};
