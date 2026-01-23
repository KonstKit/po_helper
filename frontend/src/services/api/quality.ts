/**
 * Quality APIs - Defects, quality metrics, and reports.
 */
import api from './client';
import type {
  EscapedDefect,
  EscapedDefectCreate,
  EscapedDefectUpdate,
  SeverityLevel,
  DefectStatus,
  QualitySummary,
  QualityDashboard,
  DefectMetrics,
  SprintQualityReport,
  ReportFormat,
  ReportSection,
  ReportGenerationRequest,
  ReportGenerationResponse,
  DefectMetricsCalculationResult,
  RootCauseAnalysis,
  ComponentAnalysis,
  QualityTrendData,
  PaginatedResponse,
} from './types';
import { DEFAULT_PAGE_SIZE } from './types';
import { normalizePaginatedResponse } from './pagination';

// =============================================================================
// Escaped Defects CRUD
// =============================================================================

export const createEscapedDefect = async (defect: EscapedDefectCreate): Promise<EscapedDefect> => {
  const { data } = await api.post('/v1/quality/defects', defect);
  return data;
};

export const listEscapedDefects = async (opts: {
  projectId: number;
  sprintId?: number;
  severity?: SeverityLevel;
  status?: DefectStatus;
  limit?: number;
  offset?: number;
}): Promise<PaginatedResponse<EscapedDefect>> => {
  const offset = opts.offset ?? 0;
  const limit = opts.limit ?? DEFAULT_PAGE_SIZE;
  const params: Record<string, unknown> = {
    project_id: opts.projectId,
    limit,
    offset,
  };
  if (opts.sprintId !== undefined) params.sprint_id = opts.sprintId;
  if (opts.severity) params.severity = opts.severity;
  if (opts.status) params.status = opts.status;
  const { data } = await api.get('/v1/quality/defects', { params });
  return normalizePaginatedResponse<EscapedDefect>(data, { skip: offset, limit });
};

export const getEscapedDefect = async (defectId: number): Promise<EscapedDefect> => {
  const { data } = await api.get(`/v1/quality/defects/${defectId}`);
  return data;
};

export const updateEscapedDefect = async (
  defectId: number,
  update: EscapedDefectUpdate
): Promise<EscapedDefect> => {
  const { data } = await api.patch(`/v1/quality/defects/${defectId}`, update);
  return data;
};

export const deleteEscapedDefect = async (defectId: number): Promise<void> => {
  await api.delete(`/v1/quality/defects/${defectId}`);
};

// =============================================================================
// Quality Summary & Dashboard
// =============================================================================

export const getQualitySummary = async (
  projectId: number,
  sprintId?: number
): Promise<QualitySummary> => {
  const params: Record<string, unknown> = { project_id: projectId };
  if (sprintId) params.sprint_id = sprintId;
  const { data } = await api.get('/v1/quality/summary', { params });
  return data;
};

export const getQualityDashboard = async (
  projectId: number,
  sprintId?: number
): Promise<QualityDashboard> => {
  const params: Record<string, unknown> = { project_id: projectId };
  if (sprintId) params.sprint_id = sprintId;
  const { data } = await api.get('/v1/quality/dashboard', { params });
  return data;
};

// =============================================================================
// Defect Metrics
// =============================================================================

export const getQualityMetrics = async (
  projectId: number,
  opts?: { sprintId?: number; periodDays?: number }
): Promise<DefectMetrics> => {
  const params: Record<string, unknown> = { project_id: projectId };
  if (opts?.sprintId) params.sprint_id = opts.sprintId;
  if (opts?.periodDays) params.period_days = opts.periodDays;
  const { data } = await api.get('/v1/quality/metrics', { params });
  return data;
};

export const listDefectMetrics = async (
  projectId: number,
  sprintId?: number,
  limit?: number,
  skip?: number
): Promise<PaginatedResponse<DefectMetrics>> => {
  const offset = skip ?? 0;
  const resolvedLimit = limit ?? DEFAULT_PAGE_SIZE;
  const params: Record<string, unknown> = { project_id: projectId };
  if (sprintId) params.sprint_id = sprintId;
  params.skip = offset;
  params.limit = resolvedLimit;
  const { data } = await api.get('/v1/quality/metrics', { params });
  return normalizePaginatedResponse<DefectMetrics>(data, { skip: offset, limit: resolvedLimit });
};

export const calculateDefectMetrics = async (opts: {
  projectId: number;
  sprintId?: number;
  periodStart?: string;
  periodEnd?: string;
  linesOfCode?: number;
  defectsFoundInDev?: number;
  defectsFoundInQa?: number;
}): Promise<DefectMetricsCalculationResult> => {
  const params: Record<string, unknown> = {
    project_id: opts.projectId,
  };
  if (opts.sprintId !== undefined) params.sprint_id = opts.sprintId;
  if (opts.periodStart !== undefined) params.period_start = opts.periodStart;
  if (opts.periodEnd !== undefined) params.period_end = opts.periodEnd;
  if (opts.linesOfCode !== undefined) params.lines_of_code = opts.linesOfCode;
  if (opts.defectsFoundInDev !== undefined) params.defects_found_in_dev = opts.defectsFoundInDev;
  if (opts.defectsFoundInQa !== undefined) params.defects_found_in_qa = opts.defectsFoundInQa;

  const { data } = await api.post('/v1/quality/metrics/calculate', null, { params });
  return data as DefectMetricsCalculationResult;
};

// =============================================================================
// Quality Analysis
// =============================================================================

export const getRootCauseAnalysis = async (
  projectId: number,
  sprintId?: number
): Promise<RootCauseAnalysis[]> => {
  const params: Record<string, unknown> = { project_id: projectId };
  if (sprintId) params.sprint_id = sprintId;
  const { data } = await api.get('/v1/quality/root-cause-analysis', { params });
  return data as RootCauseAnalysis[];
};

export const getComponentAnalysis = async (
  projectId: number,
  sprintId?: number
): Promise<ComponentAnalysis[]> => {
  const params: Record<string, unknown> = { project_id: projectId };
  if (sprintId) params.sprint_id = sprintId;
  const { data } = await api.get('/v1/quality/component-analysis', { params });
  return data as ComponentAnalysis[];
};

export const getQualityTrend = async (
  projectId: number,
  days?: number
): Promise<QualityTrendData> => {
  const params: Record<string, unknown> = { project_id: projectId };
  if (days) params.days = days;
  const { data } = await api.get('/v1/quality/trend', { params });
  return data as QualityTrendData;
};

// =============================================================================
// Quality Reports
// =============================================================================

export const getQualityReportData = async (
  projectId: number,
  sprintId?: number
): Promise<SprintQualityReport> => {
  const params: Record<string, unknown> = { project_id: projectId };
  if (sprintId) params.sprint_id = sprintId;
  const { data } = await api.get('/v1/quality/reports/data', { params });
  return data;
};

export const generateQualityReport = async (
  request: ReportGenerationRequest
): Promise<ReportGenerationResponse> => {
  const body: Record<string, unknown> = {
    project_id: request.projectId,
    format: request.format,
    sections: request.sections,
  };
  if (request.sprintId !== undefined) body.sprint_id = request.sprintId;
  if (request.includeCharts !== undefined) body.include_charts = request.includeCharts;
  if (request.includeDetails !== undefined) body.include_details = request.includeDetails;

  const { data } = await api.post('/v1/quality/reports/generate', body);
  return data;
};

export const getQualityReportPreviewUrl = (
  projectId: number,
  format: ReportFormat = 'pdf',
  sprintId?: number
): string => {
  let url = `/api/v1/quality/reports/preview?project_id=${projectId}&format=${format}`;
  if (sprintId) url += `&sprint_id=${sprintId}`;
  return url;
};

export const downloadQualityReport = async (
  projectId: number,
  format: ReportFormat = 'pdf',
  sprintId?: number,
  sections?: ReportSection[]
): Promise<{ url: string; filename: string }> => {
  const response = await generateQualityReport({
    projectId,
    sprintId,
    format,
    sections: sections || [
      'executive_summary',
      'quality_metrics',
      'test_coverage',
      'escaped_defects',
      'recommendations',
    ],
  });

  if (!response.success || !response.download_url) {
    throw new Error(response.error || 'Failed to generate report');
  }

  return {
    url: `/api${response.download_url}`,
    filename: response.file_name || `quality_report.${format === 'excel' ? 'xlsx' : format}`,
  };
};
