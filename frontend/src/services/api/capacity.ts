/**
 * Capacity APIs - Team capacity settings, health checks, and CFD.
 */
import api from './client';
import type {
  CapacitySetting,
  TeamCapacitySummary,
  TeamHealthCheck,
  TeamHealthSummary,
  CFDData,
  FlowMetrics,
  PaginatedResponse,
} from './types';
import { DEFAULT_PAGE_SIZE } from './types';
import { normalizePaginatedResponse } from './pagination';

// =============================================================================
// Capacity Settings CRUD
// =============================================================================

export const listCapacitySettings = async (opts?: {
  projectId?: number;
  assigneeEmail?: string;
  includeExpired?: boolean;
  skip?: number;
  limit?: number;
}): Promise<PaginatedResponse<CapacitySetting>> => {
  const params: Record<string, unknown> = {};
  if (opts?.projectId !== undefined) params.project_id = opts.projectId;
  if (opts?.assigneeEmail) params.assignee_email = opts.assigneeEmail;
  if (opts?.includeExpired) params.include_expired = opts.includeExpired;
  const skip = opts?.skip ?? 0;
  const limit = opts?.limit ?? DEFAULT_PAGE_SIZE;
  params.skip = skip;
  params.limit = limit;

  const { data } = await api.get('/v1/capacity/settings', { params });
  return normalizePaginatedResponse<CapacitySetting>(data, { skip, limit });
};

export const getCapacitySetting = async (settingId: number): Promise<CapacitySetting> => {
  const { data } = await api.get(`/v1/capacity/settings/${settingId}`);
  return data as CapacitySetting;
};

export const createCapacitySetting = async (setting: {
  projectId?: number;
  assigneeEmail: string;
  assigneeName?: string;
  hoursPerWeek: number;
  focusFactor?: number;
  validFrom?: string;
  validTo?: string;
  notes?: string;
}): Promise<CapacitySetting> => {
  const body: Record<string, unknown> = {
    assignee_email: setting.assigneeEmail,
    hours_per_week: setting.hoursPerWeek,
  };
  if (setting.projectId !== undefined) body.project_id = setting.projectId;
  if (setting.assigneeName !== undefined) body.assignee_name = setting.assigneeName;
  if (setting.focusFactor !== undefined) body.focus_factor = setting.focusFactor;
  if (setting.validFrom !== undefined) body.valid_from = setting.validFrom;
  if (setting.validTo !== undefined) body.valid_to = setting.validTo;
  if (setting.notes !== undefined) body.notes = setting.notes;

  const { data } = await api.post('/v1/capacity/settings', body);
  return data as CapacitySetting;
};

export const updateCapacitySetting = async (
  settingId: number,
  update: Partial<{
    projectId: number;
    assigneeEmail: string;
    assigneeName: string;
    hoursPerWeek: number;
    focusFactor: number;
    validFrom: string;
    validTo: string;
    notes: string;
  }>
): Promise<CapacitySetting> => {
  const body: Record<string, unknown> = {};
  if (update.projectId !== undefined) body.project_id = update.projectId;
  if (update.assigneeEmail !== undefined) body.assignee_email = update.assigneeEmail;
  if (update.assigneeName !== undefined) body.assignee_name = update.assigneeName;
  if (update.hoursPerWeek !== undefined) body.hours_per_week = update.hoursPerWeek;
  if (update.focusFactor !== undefined) body.focus_factor = update.focusFactor;
  if (update.validFrom !== undefined) body.valid_from = update.validFrom;
  if (update.validTo !== undefined) body.valid_to = update.validTo;
  if (update.notes !== undefined) body.notes = update.notes;

  const { data } = await api.patch(`/v1/capacity/settings/${settingId}`, body);
  return data as CapacitySetting;
};

export const deleteCapacitySetting = async (settingId: number): Promise<void> => {
  await api.delete(`/v1/capacity/settings/${settingId}`);
};

// =============================================================================
// Team Capacity Summary
// =============================================================================

export const getTeamCapacitySummary = async (
  projectId: number,
  opts?: { sprintWeeks?: number; referenceDate?: string }
): Promise<TeamCapacitySummary> => {
  const params: Record<string, unknown> = { project_id: projectId };
  if (opts?.sprintWeeks !== undefined) params.sprint_weeks = opts.sprintWeeks;
  if (opts?.referenceDate) params.reference_date = opts.referenceDate;

  const { data } = await api.get('/v1/capacity/summary', { params });
  return data as TeamCapacitySummary;
};

// =============================================================================
// Team Health Checks
// =============================================================================

export const listTeamHealthChecks = async (
  projectId: number,
  opts?: { sprintId?: number; skip?: number; limit?: number }
): Promise<PaginatedResponse<TeamHealthCheck>> => {
  const params: Record<string, unknown> = { project_id: projectId };
  if (opts?.sprintId) params.sprint_id = opts.sprintId;
  const skip = opts?.skip ?? 0;
  const limit = opts?.limit ?? DEFAULT_PAGE_SIZE;
  params.skip = skip;
  params.limit = limit;

  const { data } = await api.get('/v1/capacity/health-checks', { params });
  return normalizePaginatedResponse<TeamHealthCheck>(data, { skip, limit });
};

export const createTeamHealthCheck = async (check: {
  projectId: number;
  sprintId?: number;
  satisfaction?: number;
  workloadBalance?: number;
  technicalDebtPressure?: number;
  collaborationQuality?: number;
  happinessIndex?: number;
  burnoutRiskScore?: number;
  burnoutRiskFactors?: string;
  checkDate: string;
  respondentCount?: number;
  notes?: string;
}): Promise<TeamHealthCheck> => {
  const body: Record<string, unknown> = {
    project_id: check.projectId,
    check_date: check.checkDate,
  };
  if (check.sprintId !== undefined) body.sprint_id = check.sprintId;
  if (check.satisfaction !== undefined) body.satisfaction = check.satisfaction;
  if (check.workloadBalance !== undefined) body.workload_balance = check.workloadBalance;
  if (check.technicalDebtPressure !== undefined) body.technical_debt_pressure = check.technicalDebtPressure;
  if (check.collaborationQuality !== undefined) body.collaboration_quality = check.collaborationQuality;
  if (check.happinessIndex !== undefined) body.happiness_index = check.happinessIndex;
  if (check.burnoutRiskScore !== undefined) body.burnout_risk_score = check.burnoutRiskScore;
  if (check.burnoutRiskFactors !== undefined) body.burnout_risk_factors = check.burnoutRiskFactors;
  if (check.respondentCount !== undefined) body.respondent_count = check.respondentCount;
  if (check.notes !== undefined) body.notes = check.notes;

  const { data } = await api.post('/v1/capacity/health-checks', body);
  return data as TeamHealthCheck;
};

export const getTeamHealthSummary = async (
  projectId: number,
  opts?: { periodDays?: number }
): Promise<TeamHealthSummary> => {
  const params: Record<string, unknown> = { project_id: projectId };
  if (opts?.periodDays) params.period_days = opts.periodDays;

  const { data } = await api.get('/v1/capacity/health-summary', { params });
  return data as TeamHealthSummary;
};

// =============================================================================
// CFD (Cumulative Flow Diagram)
// =============================================================================

export const getCFDData = async (
  projectId: number,
  opts?: { sprintId?: number; startDate?: string; endDate?: string; limit?: number }
): Promise<CFDData> => {
  const params: Record<string, unknown> = { project_id: projectId };
  if (opts?.sprintId) params.sprint_id = opts.sprintId;
  if (opts?.startDate) params.start_date = opts.startDate;
  if (opts?.endDate) params.end_date = opts.endDate;
  if (opts?.limit !== undefined) params.limit = opts.limit;

  const { data } = await api.get('/v1/capacity/cfd', { params });
  return data as CFDData;
};

export const getFlowMetrics = async (
  projectId: number,
  opts?: { sprintId?: number; days?: number }
): Promise<FlowMetrics> => {
  const params: Record<string, unknown> = { project_id: projectId };
  if (opts?.sprintId) params.sprint_id = opts.sprintId;
  if (opts?.days) params.days = opts.days;

  const { data } = await api.get('/v1/capacity/flow-metrics', { params });
  return data as FlowMetrics;
};

export const takeCFDSnapshot = async (
  projectId: number,
  opts?: { sprintId?: number }
): Promise<{ message: string; snapshot_id: number }> => {
  const params: Record<string, unknown> = { project_id: projectId };
  if (opts?.sprintId) params.sprint_id = opts.sprintId;

  const { data } = await api.post('/v1/capacity/cfd/snapshot', undefined, { params });
  return data;
};
