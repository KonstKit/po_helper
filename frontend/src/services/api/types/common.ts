// common domain API types (split from types.ts, wave E5).

import type { RepositoryProvider } from './integrations';
import type { DefectStatus } from './quality';
import type { CoveragePriority } from './testing';
import type { ArtifactSummary, ReviewItemStatus } from './traceability';



export const DEFAULT_PAGE_SIZE = 50;

export interface PaginationParams {
  /** Number of items to skip (offset) */
  skip?: number;
  /** Maximum number of items to return */
  limit?: number;
}

export interface PaginationMeta {
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
  has_next: boolean;
  has_prev: boolean;
}

export interface PaginatedResponse<T> {
  data: T[];
  meta: PaginationMeta;
}

export interface PRSampleSummary {
  id?: number;
  number?: number;
  title?: string | null;
  state?: string | null;
  cycle_time_hours?: number | null;
  lead_time_hours?: number | null;
  rework_count?: number | null;
  opened_at?: string | null;
  merged_at?: string | null;
  closed_at?: string | null;
}

export interface PRMetricsSummary {
  total: number;
  avg_cycle_time_hours: number;
  avg_lead_time_hours: number;
  avg_time_to_first_review_hours: number;
  cycle_samples: number;
  lead_samples: number;
  first_review_samples: number;
  rework_rate: number;
  by_state: Record<string, number>;
  histogram: {
    bins: string[];
    cycle_counts: number[];
    lead_counts: number[];
  };
  sample_prs?: PRSampleSummary[];
  since_days?: number | null;
  cache_hit?: boolean;
  recent_throughput: {
    days: number;
    merged: number;
  };
}

export interface GetPRMetricsOptions {
  projectId?: number;
  provider?: string;
  sinceDays?: number;
  limit?: number;
  disableCache?: boolean;
}

export interface BindRepositoryPayload {
  repositoryUrl?: string;
  provider?: RepositoryProvider;
  repoSlug?: string;
  isPrimary?: boolean;
}

export type SeverityLevel = 'critical' | 'high' | 'medium' | 'low';

export type RootCause = 'missing_test' | 'edge_case' | 'integration' | 'regression' | 'environment' | 'configuration' | 'third_party' | 'unknown';

export interface EscapedDefect {
  id: number;
  project_id: number;
  sprint_id?: number;
  external_id?: string;
  title: string;
  description?: string;
  severity: SeverityLevel;
  priority?: string;
  environment: string;
  root_cause?: RootCause;
  affected_component?: string;
  detected_at: string;
  resolved_at?: string;
  time_to_detect_hours?: number;
  time_to_resolve_hours?: number;
  fix_commit_sha?: string;
  fix_pr_number?: number;
  customers_affected?: number;
  revenue_impact?: number;
  status: DefectStatus;
  created_at: string;
  updated_at?: string;
}

export interface EscapedDefectCreate {
  project_id: number;
  sprint_id?: number;
  title: string;
  description?: string;
  external_id?: string;
  severity?: SeverityLevel;
  priority?: string;
  environment?: string;
  root_cause?: RootCause;
  affected_component?: string;
  detected_at: string;
  status?: DefectStatus;
}

export interface EscapedDefectUpdate {
  title?: string;
  description?: string;
  severity?: SeverityLevel;
  priority?: string;
  root_cause?: RootCause;
  affected_component?: string;
  resolved_at?: string;
  fix_commit_sha?: string;
  fix_pr_number?: number;
  customers_affected?: number;
  revenue_impact?: number;
  status?: DefectStatus;
}

export interface RootCauseAnalysis {
  root_cause: string;
  count: number;
  percentage: number;
  avg_time_to_resolve_hours?: number;
}

export interface ComponentAnalysis {
  component: string;
  defect_count: number;
  critical_count: number;
  avg_severity_score: number;
}

export interface PRQualitySection {
  total_prs_merged: number;
  prs_meeting_gates: number;
  gate_pass_rate: number;
  avg_review_time_hours?: number;
  avg_approvals?: number;
  prs_with_tests: number;
  prs_with_coverage: number;
}

export interface ComponentHealthItem {
  component: string;
  coverage?: number;
  defect_count: number;
  flaky_test_count: number;
  risk_score: number;
  priority: string;
}

export interface RecommendationItem {
  category: string;
  priority: string;
  recommendation: string;
  impact: string;
  effort: string;
}

export interface FullChainNode {
  id: number;
  type: string;
  source: string;
  external_id: string;
  display_key?: string | null;
  title?: string | null;
  status?: string | null;
  url?: string | null;
  level: number;
}

export interface FullChainEdge {
  from_id: number;
  to_id: number;
  link_type: string;
  confidence?: number | null;
  confidence_factors?: Record<string, unknown> | null;
}

export interface FullChainResponse {
  center_artifact_id: number;
  nodes: FullChainNode[];
  edges: FullChainEdge[];
  levels: Record<number, number[]>;
  stats: {
    total_nodes: number;
    total_edges: number;
    max_depth_upstream: number;
    max_depth_downstream: number;
  };
}

export interface ImpactedArtifact {
  id: number;
  type: string;
  title?: string | null;
  status?: string | null;
  distance: number;
  path: number[];
  impact_type: 'direct' | 'indirect';
}

export interface ImpactAnalysisResponse {
  source_artifact_id: number;
  change_type: string;
  directly_affected: ImpactedArtifact[];
  indirectly_affected: ImpactedArtifact[];
  risk_score: number;
  risk_level: 'low' | 'medium' | 'high' | 'critical';
  recommendations: string[];
  stats: {
    total_affected: number;
    direct_count: number;
    indirect_count: number;
    affected_types: Record<string, number>;
  };
}

export interface ConfidenceDistribution {
  histogram: { range: string; count: number }[];
  stats: {
    total_links: number;
    avg_confidence: number;
    median_confidence: number;
    min_confidence: number;
    max_confidence: number;
  };
  by_link_type: Record<string, { count: number; avg_confidence: number }>;
}

export interface RecalculateConfidenceResult {
  updated_count: number;
  avg_old_confidence: number;
  avg_new_confidence: number;
}

export interface SuggestedLinkArtifact {
  id: number;
  type: string;
  source: string;
  external_id: string;
  display_key?: string | null;
  title?: string | null;
}

export interface SuggestedLink {
  id: number;
  from_artifact_id: number;
  to_artifact_id: number;
  suggested_link_type: string;
  similarity_score: number;
  method: string;
  reason?: string | null;
  status: 'pending' | 'approved' | 'rejected' | 'expired';
  created_at?: string | null;
  from_artifact?: SuggestedLinkArtifact | null;
  to_artifact?: SuggestedLinkArtifact | null;
}

export type SuggestedLinksResponse = PaginatedResponse<SuggestedLink>;

export interface SuggestedLinksStats {
  total_pending: number;
  total_approved: number;
  total_rejected: number;
  avg_similarity_score: number;
  by_link_type: Record<string, number>;
  by_method: Record<string, number>;
}

export interface GenerateSuggestionsResult {
  generated: number;
  stored: number;
  indexed_artifacts: number;
}

export interface ListReviewItemsOptions {
  projectId?: number;
  status?: ReviewItemStatus;
  priority?: string;
  artifactId?: number;
  ruleId?: number;
  skip?: number;
  limit?: number;
}

export type SyncSourceStatus = 'not_configured' | 'reachable' | 'degraded';

export interface SyncSourceHealth {
  source: string;
  label: string;
  status: SyncSourceStatus;
  effective_connector_source: string;
  last_sync?: string | null;
  artifact_count: number;
  checked_at: string;
  error?: string | null;
  base_url?: string | null;
  repository_count?: number;
}

export interface SyncProjectHealth {
  project_id: number;
  project_name: string;
  jira_key: string;
  last_sync?: string | null;
  artifact_count: number;
  health_status: 'healthy' | 'warning' | 'critical' | 'stale' | 'unknown';
}

export interface SyncHealthResponse {
  health: {
    status: 'healthy' | 'warning' | 'critical';
    score: number;
  };
  summary: {
    total_sources: number;
    reachable_sources: number;
    total_artifacts: number;
    last_sync?: string | null;
    checked_at: string;
  };
  sources: SyncSourceHealth[];
  projects: SyncProjectHealth[];
}

export interface DetailedSyncHealthResponse {
  project_id: number;
  project_name: string;
  jira_key: string;
  last_sync?: string | null;
  health_status: 'healthy' | 'warning' | 'critical' | 'stale' | 'unknown';
  by_type: Record<string, number>;
  by_source: Record<string, number>;
  link_coverage: {
    total_artifacts: number;
    linked_artifacts: number;
    orphaned_artifacts: number;
    coverage_pct: number;
  };
  sources: SyncSourceHealth[];
  checked_at: string;
  repositories: Array<{
    id: number;
    provider: string;
    repo_slug: string;
    default_branch?: string | null;
  }>;
}

export interface ConsistencyIssue {
  artifact_id?: number;
  link_id?: number;
  type?: string;
  title?: string;
  display_key?: string;
  from_artifact_id?: number;
  to_artifact_id?: number;
  link_type?: string;
  count?: number;
  last_updated?: string | null;
  days_since_update?: number;
  cycle_path?: number[];
  cycle_length?: number;
  involves_artifacts?: Array<{
    id: number;
    type: string;
    title?: string | null;
  }>;
}

export interface ConsistencyCheckRecommendation {
  priority: 'high' | 'medium' | 'low';
  category: string;
  action: string;
  reason: string;
  fix?: string;
}

export interface ConsistencyCheckResponse {
  health_score: number;
  status: 'healthy' | 'warning' | 'critical';
  issues: {
    orphans?: ConsistencyIssue[];
    orphan_count?: number;
    cycles?: ConsistencyIssue[];
    cycle_count?: number;
    broken_references?: ConsistencyIssue[];
    broken_ref_count?: number;
    duplicates?: ConsistencyIssue[];
    duplicate_count?: number;
    stale_artifacts?: ConsistencyIssue[];
    stale_count?: number;
  };
  recommendations: ConsistencyCheckRecommendation[];
  checked_at: string;
  project_filtered: boolean;
}

export interface FixConsistencyResult {
  dry_run: boolean;
  fixed_broken_refs: number;
  fixed_duplicates: number;
  details: {
    removed_links?: number[];
    removed_duplicate_ids?: number[];
  };
}

export interface DetailedCycle {
  cycle_index: number;
  cycle_path: number[];
  cycle_length: number;
  link_type: string;
  artifacts: Array<{
    id: number;
    type: string;
    source: string;
    external_id: string;
    display_key?: string | null;
    title?: string | null;
    status?: string | null;
    position: number;
  }>;
}

export interface DetailedCyclesResponse {
  total_cycles: number;
  cycles: DetailedCycle[];
  checked_link_types: string[];
}

export interface HealthTrend {
  check_date: string;
  happiness_index?: number;
  burnout_risk_score?: number;
}

export interface CFDSnapshot {
  id: number;
  project_id: number;
  sprint_id?: number;
  snapshot_date: string;
  backlog_count: number;
  todo_count: number;
  in_progress_count: number;
  in_review_count: number;
  testing_count: number;
  done_count: number;
  total_count: number;
  wip_count: number;
  throughput?: number;
  avg_cycle_time_hours?: number;
  created_at: string;
}

export interface CFDData {
  snapshots: CFDSnapshot[];
  date_range: { start: string; end: string };
  status_labels: string[];
}

export interface FileCoverageDelta {
  file_path: string;
  old_coverage?: number;
  new_coverage?: number;
  delta?: number;
  lines_added?: number;
  lines_removed?: number;
  is_new_file: boolean;
  is_deleted_file: boolean;
}

export interface DeltaCoverage {
  base_commit?: string;
  head_commit?: string;
  pr_number?: number;
  line_coverage_delta: number;
  branch_coverage_delta: number;
  current_line_coverage?: number;
  current_branch_coverage?: number;
  previous_line_coverage?: number;
  previous_branch_coverage?: number;
  files_with_decreased_coverage: FileCoverageDelta[];
  files_with_increased_coverage: FileCoverageDelta[];
  new_files_without_coverage: string[];
  total_files_changed: number;
  files_improved: number;
  files_degraded: number;
}

export interface ComponentCoverage {
  id: number;
  project_id: number;
  coverage_report_id?: number;
  component_path: string;
  component_name?: string;
  line_coverage?: number;
  branch_coverage?: number;
  function_coverage?: number;
  total_files?: number;
  covered_files?: number;
  total_lines?: number;
  covered_lines?: number;
  average_complexity?: number;
  max_complexity?: number;
  risk_score?: number;
  priority?: CoveragePriority;
  commit_sha?: string;
  created_at?: string;
}

export interface ComponentCoverageSummary {
  total_components: number;
  components_above_threshold: number;
  components_below_threshold: number;
  average_coverage: number;
  critical_risk_components: ComponentCoverage[];
  high_risk_components: ComponentCoverage[];
  components: ComponentCoverage[];
}

export interface LocalFlakyTest {
  id: string;
  classname: string;
  name: string;
  runs: number;
  failRate: number;
  score: number;
}

export interface DoraLeadTimeStats {
  average: number | null;
  median: number | null;
  p90: number | null;
  samples: number;
}

export interface DoraRecoveryStats {
  average: number | null;
  median: number | null;
  samples: number;
}

export interface DoraTotals {
  failures: number;
  incidents: number;
  deployments_considered?: number;
}

export interface DoraTimeframe {
  start: string;
  end: string;
}

export interface DoraMetrics {
  window_days: number;
  deployments: number;
  deployment_frequency_per_day: number;
  deployment_frequency_per_week: number;
  lead_time_hours: DoraLeadTimeStats;
  change_failure_rate: number | null;
  mean_time_to_recovery_hours: DoraRecoveryStats;
  totals: DoraTotals;
  timeframe?: DoraTimeframe;
}

export interface ReactFlowPosition {
  x: number;
  y: number;
}

export interface ReactFlowNode {
  id: string;
  type: string;
  position: ReactFlowPosition;
  data: Record<string, unknown>;
}

export interface ReactFlowEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
}

export interface ListRulesOptions {
  enabled?: boolean;
  category?: string;
  projectId?: number;
  skip?: number;
  limit?: number;
  offset?: number; // legacy alias
}

export interface ListRuleExecutionsOptions {
  ruleId?: number;
  status?: string;
  skip?: number;
  limit?: number;
  offset?: number; // legacy alias
}

export interface RTMExportFilters {
  row_types?: string[];
  col_types?: string[];
  row_statuses?: string[];
  col_statuses?: string[];
  link_types?: string[];
  min_confidence?: number;
}

export interface RTMFilters {
  row_types?: string[];
  col_types?: string[];
  row_statuses?: string[];
  col_statuses?: string[];
  link_types?: string[];
  min_confidence?: number;
  direction?: 'both' | 'row_to_col' | 'col_to_row';
  search_query?: string;
  include_orphans?: boolean;
  project_id?: number;
}

export interface RTMPagination {
  row_skip?: number;
  row_limit?: number;
  col_skip?: number;
  col_limit?: number;
}

export interface RTMCellLink {
  link_type: string;
  confidence?: number | null;
  confidence_factors?: Record<string, unknown> | null;
}

export interface RTMCell {
  /** Whether cell has any links */
  has_link: boolean;
  /** Number of links in this cell */
  link_count: number;
  /** Link types present in this cell */
  link_types: string[];
  /** Average confidence across all links in cell */
  avg_confidence?: number | null;
  /** Detailed link info (only present when include_link_details=true) */
  links?: RTMCellLink[] | null;
}

export interface RTMMatrixCoverage {
  /** Number of rows with at least one link */
  rows_with_links: number;
  /** Number of columns with at least one link */
  cols_with_links: number;
  /** Percentage of rows that have at least one link */
  row_coverage_pct: number;
  /** Percentage of columns that have at least one link */
  col_coverage_pct: number;
  /** Traceability density (filled cells / possible cells * 100) */
  traceability_density_pct: number;
  /** Total number of links in the matrix */
  total_links: number;
  /** Links broken down by link type */
  links_by_type: Record<string, number>;
  /** Average confidence across all links */
  avg_confidence?: number | null;
}

export interface RTMMatrixResponse {
  rows: ArtifactSummary[];
  columns: ArtifactSummary[];
  cells: Record<string, Record<string, RTMCell>>;
  total_rows: number;
  total_columns: number;
  coverage: RTMMatrixCoverage;
  filters_applied: Record<string, unknown>;
}
