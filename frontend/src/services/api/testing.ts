/**
 * Testing APIs - Flaky tests, coverage analysis, and test analytics.
 */
import api from './client';
import type {
  FlakyTest,
  FlakyTestCreate,
  FlakyTestUpdate,
  FlakyTestStatus,
  FlakyTestSummary,
  DeltaCoverage,
  ComponentCoverage,
  ComponentCoverageSummary,
  CoverageTrendData,
  TestAnalyticsDashboard,
  TestRun,
  TestResult,
  CoverageReportListItem,
  PaginatedResponse,
} from './types';
import { DEFAULT_PAGE_SIZE } from './types';
import { normalizePaginatedResponse } from './pagination';

// =============================================================================
// Runs, Results, Coverage Lists (paginated)
// =============================================================================

export const listTestRuns = async (opts?: {
  projectId?: number;
  provider?: string;
  skip?: number;
  limit?: number;
}): Promise<PaginatedResponse<TestRun>> => {
  const params: Record<string, unknown> = {};
  if (opts?.projectId !== undefined) params.project_id = opts.projectId;
  if (opts?.provider) params.provider = opts.provider;
  const skip = opts?.skip ?? 0;
  const limit = opts?.limit ?? DEFAULT_PAGE_SIZE;
  params.skip = skip;
  params.limit = limit;

  const { data } = await api.get('/v1/testing/runs', { params });
  return normalizePaginatedResponse<TestRun>(data, { skip, limit, legacyKey: 'runs' });
};

export const listTestResults = async (opts?: {
  projectId?: number;
  commitSha?: string;
  status?: string;
  sinceDays?: number;
  skip?: number;
  limit?: number;
}): Promise<PaginatedResponse<TestResult>> => {
  const params: Record<string, unknown> = {};
  if (opts?.projectId !== undefined) params.project_id = opts.projectId;
  if (opts?.commitSha) params.commit_sha = opts.commitSha;
  if (opts?.status) params.status = opts.status;
  if (opts?.sinceDays !== undefined) params.since_days = opts.sinceDays;
  const skip = opts?.skip ?? 0;
  const limit = opts?.limit ?? DEFAULT_PAGE_SIZE;
  params.skip = skip;
  params.limit = limit;

  const { data } = await api.get('/v1/testing/results', { params });
  return normalizePaginatedResponse<TestResult>(data, { skip, limit, legacyKey: 'results' });
};

export const listCoverageReports = async (opts?: {
  projectId?: number;
  skip?: number;
  limit?: number;
}): Promise<PaginatedResponse<CoverageReportListItem>> => {
  const params: Record<string, unknown> = {};
  if (opts?.projectId !== undefined) params.project_id = opts.projectId;
  const skip = opts?.skip ?? 0;
  const limit = opts?.limit ?? DEFAULT_PAGE_SIZE;
  params.skip = skip;
  params.limit = limit;

  const { data } = await api.get('/v1/testing/coverage/list', { params });
  return normalizePaginatedResponse<CoverageReportListItem>(data, { skip, limit, legacyKey: 'coverage' });
};

// =============================================================================
// Flaky Tests CRUD
// =============================================================================

export const listFlakyTests = async (
  projectId: number,
  opts?: { status?: FlakyTestStatus; skip?: number; limit?: number }
): Promise<PaginatedResponse<FlakyTest>> => {
  const params: Record<string, unknown> = { project_id: projectId };
  if (opts?.status) params.status = opts.status;
  const skip = opts?.skip ?? 0;
  const limit = opts?.limit ?? DEFAULT_PAGE_SIZE;
  params.skip = skip;
  params.limit = limit;

  const { data } = await api.get('/v1/testing/flaky-tests', { params });
  return normalizePaginatedResponse<FlakyTest>(data, { skip, limit });
};

export const getFlakyTest = async (flakyId: number): Promise<FlakyTest> => {
  const { data } = await api.get(`/v1/testing/flaky-tests/${flakyId}`);
  return data as FlakyTest;
};

export const createFlakyTest = async (flaky: FlakyTestCreate): Promise<FlakyTest> => {
  const { data } = await api.post('/v1/testing/flaky-tests', flaky);
  return data as FlakyTest;
};

export const updateFlakyTest = async (flakyId: number, updates: FlakyTestUpdate): Promise<FlakyTest> => {
  const { data } = await api.patch(`/v1/testing/flaky-tests/${flakyId}`, updates);
  return data as FlakyTest;
};

export const deleteFlakyTest = async (flakyId: number): Promise<void> => {
  await api.delete(`/v1/testing/flaky-tests/${flakyId}`);
};

export const detectFlakyTests = async (
  projectId: number,
  opts?: { days?: number; minRuns?: number; flakinessThreshold?: number }
): Promise<{
  detected_count: number;
  analyzed_tests: number;
  flaky_tests: Array<{
    id: number;
    test_name: string;
    classname?: string;
    flakiness_rate: number;
    total_runs: number;
    failures: number;
  }>;
}> => {
  const params: Record<string, unknown> = { project_id: projectId };
  if (opts?.days) params.days = opts.days;
  if (opts?.minRuns) params.min_runs = opts.minRuns;
  if (opts?.flakinessThreshold) params.flakiness_threshold = opts.flakinessThreshold;

  const { data } = await api.post('/v1/testing/flaky-tests/detect', undefined, { params });
  return data;
};

export const getFlakyTestsSummary = async (projectId: number): Promise<FlakyTestSummary> => {
  const { data } = await api.get('/v1/testing/flaky-tests/summary', { params: { project_id: projectId } });
  return data as FlakyTestSummary;
};

// =============================================================================
// Coverage Files
// =============================================================================

export const getCoverageFiles = async (
  commitSha: string,
  opts?: { skip?: number; limit?: number }
): Promise<PaginatedResponse<{
  file_path: string;
  line_coverage?: number;
  branch_coverage?: number;
  lines_covered?: number;
  lines_total?: number;
}>> => {
  const params: Record<string, unknown> = {};
  const skip = opts?.skip ?? 0;
  const limit = opts?.limit ?? DEFAULT_PAGE_SIZE;
  params.skip = skip;
  params.limit = limit;

  const { data } = await api.get(`/v1/testing/coverage/${commitSha}/files`, { params });
  return normalizePaginatedResponse(data, { skip, limit, legacyKey: 'files' });
};

// =============================================================================
// Delta Coverage
// =============================================================================

export const getDeltaCoverage = async (
  projectId: number,
  opts?: { baseCommit?: string; headCommit?: string }
): Promise<DeltaCoverage> => {
  const params: Record<string, unknown> = { project_id: projectId };
  if (opts?.baseCommit) params.base_commit = opts.baseCommit;
  if (opts?.headCommit) params.head_commit = opts.headCommit;

  const { data } = await api.get('/v1/testing/coverage/delta', { params });
  return data as DeltaCoverage;
};

export const getPRDeltaCoverage = async (
  projectId: number,
  prNumber: number
): Promise<DeltaCoverage> => {
  const params = { project_id: projectId };
  const { data } = await api.get(`/v1/testing/coverage/delta/pr/${prNumber}`, { params });
  return data as DeltaCoverage;
};

// =============================================================================
// Component Coverage
// =============================================================================

export const calculateComponentCoverage = async (
  projectId: number,
  opts?: { commitSha?: string; depth?: number }
): Promise<{
  commit_sha: string;
  total_components: number;
  components: Array<{
    component_path: string;
    line_coverage: number;
    total_files: number;
    total_lines: number;
    risk_score: number;
    priority: string;
  }>;
}> => {
  const params: Record<string, unknown> = { project_id: projectId };
  if (opts?.commitSha) params.commit_sha = opts.commitSha;
  if (opts?.depth) params.depth = opts.depth;

  const { data } = await api.post('/v1/testing/coverage/components/calculate', undefined, { params });
  return data;
};

export const listComponentCoverage = async (
  projectId: number,
  opts?: { commitSha?: string; skip?: number; limit?: number }
): Promise<PaginatedResponse<ComponentCoverage>> => {
  const params: Record<string, unknown> = { project_id: projectId };
  if (opts?.commitSha) params.commit_sha = opts.commitSha;
  const skip = opts?.skip ?? 0;
  const limit = opts?.limit ?? DEFAULT_PAGE_SIZE;
  params.skip = skip;
  params.limit = limit;

  const { data } = await api.get('/v1/testing/coverage/components', { params });
  return normalizePaginatedResponse<ComponentCoverage>(data, { skip, limit });
};

export const getComponentCoverageSummary = async (
  projectId: number,
  threshold?: number
): Promise<ComponentCoverageSummary> => {
  const params: Record<string, unknown> = { project_id: projectId };
  if (threshold) params.threshold = threshold;

  const { data } = await api.get('/v1/testing/coverage/components/summary', { params });
  return data as ComponentCoverageSummary;
};

// =============================================================================
// Coverage Trends
// =============================================================================

export const getCoverageTrendAnalytics = async (
  projectId: number,
  period?: string
): Promise<CoverageTrendData> => {
  const params: Record<string, unknown> = { project_id: projectId };
  if (period) params.period = period;

  const { data } = await api.get('/v1/testing/coverage/trend', { params });
  return data as CoverageTrendData;
};

// =============================================================================
// Test Analytics Dashboard
// =============================================================================

export const getTestAnalyticsDashboard = async (
  projectId: number,
  opts?: { sprintId?: number; coverageTarget?: number }
): Promise<TestAnalyticsDashboard> => {
  const params: Record<string, unknown> = { project_id: projectId };
  if (opts?.sprintId) params.sprint_id = opts.sprintId;
  if (opts?.coverageTarget) params.coverage_target = opts.coverageTarget;

  const { data } = await api.get('/v1/testing/analytics/dashboard', { params });
  return data as TestAnalyticsDashboard;
};
