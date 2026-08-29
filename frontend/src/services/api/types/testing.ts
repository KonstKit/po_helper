// testing domain API types (split from types.ts, wave E5).

import type { ComponentCoverageSummary, DeltaCoverage } from './common';



export interface TestCoverageSection {
  line_coverage?: number;
  branch_coverage?: number;
  function_coverage?: number;
  coverage_target: number;
  coverage_met: boolean;
  total_tests: number;
  passed_tests: number;
  failed_tests: number;
  skipped_tests: number;
  test_pass_rate: number;
  flaky_test_count: number;
}

export type FlakyTestStatus = 'active' | 'fixed' | 'ignored' | 'quarantined';

export type FlakyTestCause = 'race_condition' | 'timing' | 'environment' | 'external_dependency' | 'data_dependency' | 'resource_leak' | 'unknown';

export interface FlakyTest {
  id: number;
  project_id: number;
  suite?: string;
  classname?: string;
  test_name: string;
  total_runs: number;
  failure_count: number;
  flakiness_rate?: number;
  status: FlakyTestStatus;
  suspected_cause?: FlakyTestCause;
  last_failure_at?: string;
  last_success_at?: string;
  first_detected_at?: string;
  failure_patterns?: string[];
  affected_commits?: string[];
  assigned_to?: string;
  fix_pr_number?: number;
  notes?: string;
  created_at?: string;
  updated_at?: string;
}

export interface FlakyTestCreate {
  project_id: number;
  suite?: string;
  classname?: string;
  test_name: string;
  total_runs?: number;
  failure_count?: number;
  status?: FlakyTestStatus;
  suspected_cause?: FlakyTestCause;
  failure_patterns?: string[];
  affected_commits?: string[];
}

export interface FlakyTestUpdate {
  status?: FlakyTestStatus;
  suspected_cause?: FlakyTestCause;
  assigned_to?: string;
  fix_pr_number?: number;
  notes?: string;
}

export interface FlakyTestSummary {
  total_flaky_tests: number;
  active_flaky_tests: number;
  fixed_this_sprint: number;
  quarantined: number;
  by_cause: Record<string, number>;
  trend_direction: 'improving' | 'degrading' | 'stable';
  trend_percent: number;
  top_flaky_tests: FlakyTest[];
}

export type CoveragePriority = 'critical' | 'high' | 'medium' | 'low';

export interface CoverageTrendPoint {
  date: string;
  line_coverage?: number;
  branch_coverage?: number;
  test_pass_rate?: number;
  flaky_test_count?: number;
}

export interface CoverageTrendData {
  project_id: number;
  period: string;
  data_points: CoverageTrendPoint[];
  coverage_change: number;
  coverage_direction: 'improving' | 'degrading' | 'stable';
  highest_coverage?: CoverageTrendPoint;
  lowest_coverage?: CoverageTrendPoint;
}

export interface TestAnalyticsDashboard {
  project_id: number;
  sprint_id?: number;
  current_line_coverage?: number;
  current_branch_coverage?: number;
  coverage_target: number;
  coverage_met: boolean;
  total_tests: number;
  passing_tests: number;
  failing_tests: number;
  skipped_tests: number;
  test_pass_rate: number;
  flaky_summary: FlakyTestSummary;
  component_summary: ComponentCoverageSummary;
  coverage_trend: CoverageTrendData;
  latest_delta?: DeltaCoverage;
}

export interface TestRun {
  id?: number;
  provider: string;
  commit_sha?: string;
  pr_number?: number;
  total: number;
  passed?: number;
  failed: number;
  error?: number;
  skipped: number;
  duration_ms?: number;
  created_at: string;
}

export interface TestResult {
  id?: number;
  classname?: string;
  name: string;
  status: 'passed' | 'failed' | 'error' | 'skipped' | string;
  duration?: number;
  message?: string;
  stack_trace?: string;
  commit_sha?: string;
  created_at?: string;
  suite?: string;
  provider?: string;
  raw?: Record<string, unknown>;
}

export interface CoverageReportListItem {
  id?: number;
  commit_sha: string;
  pr_number?: number;
  provider?: string;
  line_coverage?: number;
  branch_coverage?: number;
  function_coverage?: number;
  total_tests?: number;
  passed_tests?: number;
  failed_tests?: number;
  created_at: string;
}

export interface TestTrendPoint {
  day: string;
  total: number;
  failed: number;
}

export interface CoverageTrendItem {
  day: string;
  avg_line: number;
  avg_branch: number;
  count?: number;
}
