// sprint domain API types (split from types.ts, wave E5).

import type { ComponentHealthItem, EscapedDefect, HealthTrend, PRQualitySection, RecommendationItem } from './common';
import type { DefectTrend, QualitySummary } from './quality';
import type { CoverageTrendItem, TestCoverageSection } from './testing';



export interface TeamHealthMetrics {
  total: number;
  done: number;
  in_progress: number;
  backlog: number;
  blockers: number;
  overdue: number;
  completion_rate: number;
  estimate_hours: number;
  spent_hours: number;
  avg_cycle_time_hours: number | null;
  median_cycle_time_hours: number | null;
  cycle_samples: number;
  error?: string;
}

export interface SprintQualityReport {
  report_id?: string;
  project_id: number;
  project_name?: string;
  sprint_id?: number;
  sprint_name?: string;
  report_date: string;
  period_start?: string;
  period_end?: string;
  overall_quality_score: number;
  quality_grade: string;
  key_highlights: string[];
  key_concerns: string[];
  quality_summary?: QualitySummary;
  test_coverage?: TestCoverageSection;
  pr_quality?: PRQualitySection;
  escaped_defects_summary?: {
    total: number;
    open: number;
    resolved: number;
  };
  recent_escaped_defects: EscapedDefect[];
  component_health: ComponentHealthItem[];
  coverage_trend: CoverageTrendItem[];
  defect_trend: DefectTrend[];
  recommendations: RecommendationItem[];
}

export interface CapacitySetting {
  id: number;
  project_id?: number;
  assignee_email: string;
  assignee_name?: string;
  hours_per_week: number;
  focus_factor: number;
  valid_from?: string;
  valid_to?: string;
  notes?: string;
  effective_capacity?: number;
  created_at: string;
  updated_at?: string;
}

export interface TeamCapacitySummary {
  total_theoretical_hours: number;
  total_effective_hours: number;
  average_focus_factor: number;
  team_members: number;
  capacity_by_member: Array<{
    assignee_email: string;
    assignee_name?: string;
    hours_per_week: number;
    focus_factor: number;
    theoretical_hours: number;
    effective_hours: number;
    notes?: string;
  }>;
}

export interface TeamHealthCheck {
  id: number;
  project_id: number;
  sprint_id?: number;
  satisfaction?: number;
  workload_balance?: number;
  technical_debt_pressure?: number;
  collaboration_quality?: number;
  happiness_index?: number;
  burnout_risk_score?: number;
  burnout_risk_factors?: string;
  check_date: string;
  respondent_count?: number;
  notes?: string;
  created_at: string;
}

export interface TeamHealthSummary {
  latest_happiness_index?: number;
  latest_burnout_risk?: number;
  trend_direction: 'improving' | 'declining' | 'stable';
  checks_count: number;
  trend_data: HealthTrend[];
}

export interface VelocitySprintSummary {
  sprint_id?: number;
  sprint_name?: string;
  velocity: number;
  end_date?: string | null;
}

export type VelocityTrendDirection = 'increasing' | 'decreasing' | 'stable' | 'insufficient_data';

export interface VelocityResponse {
  average_velocity: number;
  sprints_analyzed?: number;
  velocity_trend?: VelocityTrendDirection;
  sprint_velocities?: VelocitySprintSummary[];
}

export interface BurndownPoint {
  day: number;
  ideal_remaining?: number;
  remaining?: number;
}

export interface BurndownResponse {
  sprint_id?: number;
  ideal_burndown?: BurndownPoint[];
  actual_burndown?: BurndownPoint[];
}

export interface RiskItem {
  id?: number;
  severity: 'low' | 'medium' | 'high' | 'critical' | string;
  description?: string;
  type?: string;
  message?: string;
  task_key?: string;
  probability?: number;
  impact?: number;
}

export interface RisksResponse {
  risks: RiskItem[];
  total?: number;
}

export interface TeamMemberActivity {
  assignee?: string;
  name?: string | null;
  count?: number;
  estimate_hours?: number;
  spent_hours?: number;
  active_tasks?: number;
  last_activity?: string | null;
  days_since_activity?: number | null;
  email?: string | null;
}

export interface ForecastResponse {
  estimated_completion_date?: string;
  confidence_level?: 'low' | 'medium' | 'high';
  forecast_available: boolean;
  remaining_work?: number;
  velocity_used?: number;
}
