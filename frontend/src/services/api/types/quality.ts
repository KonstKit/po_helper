// quality domain API types (split from types.ts, wave E5).

import type { ComponentAnalysis, EscapedDefect, RootCauseAnalysis } from './common';



export type DefectStatus = 'open' | 'investigating' | 'resolved' | 'closed';

export interface QualitySummary {
  project_id: number;
  sprint_id?: number;
  total_escaped_defects: number;
  open_defects: number;
  resolved_defects: number;
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  defect_density?: number;
  defect_removal_efficiency?: number;
  escape_rate?: number;
  mttr_hours?: number;
  mttd_hours?: number;
  trend_direction?: 'improving' | 'stable' | 'declining';
  trend_change_percent?: number;
}

export interface DefectTrend {
  date: string;
  total_defects: number;
  escaped_defects: number;
  resolved_defects: number;
  dre?: number;
}

export interface QualityTrendData {
  project_id: number;
  trends: DefectTrend[];
  period_days: number;
}

export interface QualityDashboard {
  summary: QualitySummary;
  recent_defects: EscapedDefect[];
  root_cause_breakdown: RootCauseAnalysis[];
  component_analysis: ComponentAnalysis[];
  trend_data: QualityTrendData;
}

export interface DefectMetrics {
  id: number;
  project_id: number;
  sprint_id?: number;
  period_start: string;
  period_end: string;
  total_defects: number;
  defects_found_in_dev: number;
  defects_found_in_qa: number;
  defects_found_in_prod: number;
  critical_defects: number;
  high_defects: number;
  medium_defects: number;
  low_defects: number;
  defect_density?: number;
  defect_removal_efficiency?: number;
  escape_rate?: number;
  mean_time_to_resolve_hours?: number;
  mean_time_to_detect_hours?: number;
  lines_of_code?: number;
  code_churn?: number;
  test_automation_percent?: number;
  test_pass_rate?: number;
  created_at: string;
  updated_at?: string;
}

export interface DefectMetricsCalculationResult {
  id: number;
  project_id: number;
  sprint_id?: number | null;
  period: string;
  total_defects: number;
  defect_removal_efficiency?: number | null;
  escape_rate?: number | null;
  defect_density?: number | null;
  mttr_hours?: number | null;
  mttd_hours?: number | null;
}

export type QualityGateProvider = 'github' | 'gitlab' | 'generic';

export interface QualityPullRequest {
  number: number;
  title?: string;
  provider?: QualityGateProvider;
  state?: string;
  opened_at?: string | null;
  merged_at?: string | null;
  closed_at?: string | null;
  cycle_time_hours?: number | null;
  lead_time_hours?: number | null;
  time_to_first_review_hours?: number | null;
  rework_count?: number | null;
  files_changed?: number | null;
  lines_added?: number | null;
  lines_deleted?: number | null;
}

export interface QualityGateAssessment {
  pr_number?: number;
  pass?: boolean;
  reasons?: string[];
  line_coverage?: number | null;
  branch_coverage?: number | null;
  github_check?: {
    response?: {
      html_url?: string;
    };
  };
  github_status?: {
    response?: {
      html_url?: string;
    };
  };
}

export interface QualityGateResult extends QualityGateAssessment {
  checking?: boolean;
  error?: string;
  result?: QualityGateAssessment;
}

export interface QualityHistoryItem {
  pr_number?: number;
  pass?: boolean;
  passed?: boolean;
  checked_at?: string;
  created_at?: string;
  line_coverage?: number;
  branch_coverage?: number;
  result?: QualityGateAssessment;
}
