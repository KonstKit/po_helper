/**
 * API Types - All TypeScript interfaces and types for API communication.
 *
 * Organized by domain:
 * - Pagination
 * - User/Auth
 * - Integrations (JIRA, GitHub, GitLab, Confluence)
 * - Projects
 * - Tasks
 * - Quality (Defects, Reports)
 * - Traceability (Matrix, Flows, Chains, Links)
 * - Capacity (Settings, Health, CFD)
 * - Testing (Flaky Tests, Coverage)
 */

// =============================================================================
// Pagination Types
// =============================================================================

/** Default page size for list endpoints (as per PERFORMANCE_RECOMMENDATIONS.md) */
export const DEFAULT_PAGE_SIZE = 50;

/** Pagination query parameters for list endpoints */
export interface PaginationParams {
  /** Number of items to skip (offset) */
  skip?: number;
  /** Maximum number of items to return */
  limit?: number;
}

/** Pagination metadata returned by paginated endpoints */
export interface PaginationMeta {
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
  has_next: boolean;
  has_prev: boolean;
}

/** Generic paginated response wrapper */
export interface PaginatedResponse<T> {
  data: T[];
  meta: PaginationMeta;
}

// =============================================================================
// User/Auth Types
// =============================================================================

export interface User {
  id: number;
  email: string;
  username: string;
  full_name?: string;
  is_active: boolean;
  is_superuser: boolean;
  created_at?: string;
  updated_at?: string | null;
}

// =============================================================================
// Integration Types
// =============================================================================

export interface IntegrationSettings {
  kind: "jira" | "confluence";
  base_url?: string | null;
  email?: string | null;
  api_token?: string | null;
  webhook_secret?: string | null;
  use_pat?: boolean | null;
  has_token?: boolean;
  has_webhook_secret?: boolean;
}

export interface GithubTestResponse {
  status: string;
  base_url: string;
  message?: string;
  login?: string | null;
  name?: string | null;
  plan?: string | null;
  scopes?: string | null;
  rate_limit_remaining?: string | null;
  rate_limit_reset?: string | null;
}

// =============================================================================
// Project Types
// =============================================================================

export interface Project {
  id: number;
  jira_key: string;
  name: string;
  description?: string;
  status: string;
  budget?: number;
  spent_budget?: number;
  start_date?: string | null;
  end_date?: string | null;
  owner_id?: number | null;
  meta?: {
    last_sync_at?: string;
    issues_count?: number;
    [key: string]: unknown;
  };
  created_at?: string;
  updated_at?: string | null;
  // Stats (when returned by detail endpoint)
  total_tasks?: number;
  completed_tasks?: number;
  in_progress_tasks?: number;
  total_estimate_hours?: number;
  total_spent_hours?: number;
  completion_percentage?: number;
  velocity?: number | null;
  // Quality thresholds for PR gates
  quality_thresholds?: {
    min_line?: number;
    min_branch?: number;
  };
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

// =============================================================================
// Repository Types
// =============================================================================

export type RepositoryProvider = 'github' | 'gitlab';

export interface RepositoryInfo {
  id: number;
  provider: RepositoryProvider;
  repo_slug: string;
  default_branch?: string | null;
}

export interface ProjectRepositoryLink {
  id: number;
  project_id: number;
  repository_id: number;
  is_primary: boolean;
  created_at: string;
  updated_at?: string | null;
  repository: RepositoryInfo;
}

export interface BindRepositoryPayload {
  repositoryUrl?: string;
  provider?: RepositoryProvider;
  repoSlug?: string;
  isPrimary?: boolean;
}

export interface GitlabProjectSummary {
  id: number;
  name: string;
  path: string;
  path_with_namespace: string;
  description?: string | null;
  default_branch?: string | null;
  visibility?: string | null;
  ssh_url_to_repo?: string | null;
  http_url_to_repo?: string | null;
  web_url?: string | null;
  last_activity_at?: string | null;
  namespace?: string | null;
}

export interface GitlabProjectsResponse {
  count: number;
  projects: GitlabProjectSummary[];
  pagination: {
    next_page?: string | null;
    prev_page?: string | null;
    total_pages?: string | null;
    total_items?: string | null;
  };
  source: string;
}

export interface GitImportRepoStats {
  repository_id: number;
  provider: RepositoryProvider;
  repo_slug: string;
  default_branch?: string | null;
  commits?: {
    created?: number;
    updated?: number;
    links_created?: number;
    suggestions?: Array<Record<string, unknown>>;
    error?: string;
  };
  pull_requests?: {
    processed?: number;
    links_created?: number;
    suggestions?: Array<Record<string, unknown>>;
    error?: string;
  };
  error?: string;
}

export interface GitImportSummary {
  project_id?: number;
  repositories?: GitImportRepoStats[];
  error?: string;
}

// =============================================================================
// Task Types
// =============================================================================

export interface TaskItem {
  id: number;
  project_id?: number | null;
  sprint_id?: number | null;
  jira_id: string;
  key: string;
  summary: string;
  description?: string;
  task_type?: string;
  status: string;
  priority?: string;
  assignee_name?: string;
  assignee_email?: string;
  reporter_email?: string;
  reporter_name?: string;
  estimate_hours?: number;
  spent_hours?: number;
  remaining_hours?: number;
  is_blocker?: boolean;
  created_date?: string | null;
  updated_date?: string | null;
  resolved_date?: string | null;
  due_date?: string | null;
  business_value?: number | null;
  value_delivered?: boolean | null;
  roi?: number | null;
}

// =============================================================================
// Quality Types (Defects & Reports)
// =============================================================================

export type SeverityLevel = 'critical' | 'high' | 'medium' | 'low';
export type DefectStatus = 'open' | 'investigating' | 'resolved' | 'closed';
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

// =============================================================================
// Report Types
// =============================================================================

export type ReportFormat = 'pdf' | 'excel' | 'json' | 'csv';

export type ReportSection =
  | 'executive_summary'
  | 'quality_metrics'
  | 'test_coverage'
  | 'flaky_tests'
  | 'escaped_defects'
  | 'pr_quality'
  | 'component_health'
  | 'trends'
  | 'recommendations';

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

export interface ReportGenerationRequest {
  projectId: number;
  sprintId?: number;
  format: ReportFormat;
  sections: ReportSection[];
  includeCharts?: boolean;
  includeDetails?: boolean;
}

export interface ReportGenerationResponse {
  success: boolean;
  report_id?: string;
  download_url?: string;
  file_name?: string;
  format: ReportFormat;
  generated_at: string;
  file_size_bytes?: number;
  error?: string;
}

// =============================================================================
// Traceability Types
// =============================================================================

export interface TraceabilityTypeStats {
  total: number;
  linked: number;
  unlinked: number;
  link_count: number;
  coverage_pct: number;
  avg_links_per_artifact: number;
  link_type_counts?: Record<string, number>;
  link_type_artifact_counts?: Record<string, number>;
}

export interface TraceabilityMatrixSummary {
  total: number;
  by_type: Record<string, number>;
  per_type?: Record<string, TraceabilityTypeStats>;
  coverage: {
    linked_artifacts: number;
    coverage_pct: number;
  };
}

export interface TraceabilityBackfillResult {
  status: string;
  created: number;
  updated: number;
  git?: GitImportSummary;
}

export interface TraceabilityFlowNode {
  id: number;
  type?: string | null;
  title?: string | null;
  status?: string | null;
}

export interface TraceabilityFlowEdge {
  from: number;
  to: number;
  type: string;
  confidence?: number | null;
}

export interface TraceabilityRequirementFlow {
  nodes: TraceabilityFlowNode[];
  edges: TraceabilityFlowEdge[];
}

export interface TraceabilityNeighborArtifact {
  id: number;
  type: string;
  source: string;
  external_id: string;
  title?: string | null;
  status?: string | null;
}

export interface TraceabilityNeighborLink {
  link_type: string;
  confidence?: number | null;
  artifact: TraceabilityNeighborArtifact;
}

export interface TraceabilityTaskArtifacts {
  task_artifact: { id: number; key: string };
  outgoing: TraceabilityNeighborLink[];
  incoming: TraceabilityNeighborLink[];
}

export interface GitHubPullRequest {
  number: number;
  title?: string;
  state?: string;
  draft?: boolean;
  html_url?: string;
  user?: {
    login?: string;
    avatar_url?: string;
  } | null;
  created_at?: string;
  updated_at?: string;
  merged_at?: string | null;
  additions?: number | null;
  deletions?: number | null;
  changed_files?: number | null;
  labels?: string[] | null;
}

export interface GitHubPullResponse {
  repository: string;
  state: string;
  count: number;
  pulls: GitHubPullRequest[];
}

/** PR item from listPullRequests for quality gates evaluation */
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

export interface PullRequestsResponse {
  total: number;
  pull_requests: QualityPullRequest[];
}

/** Raw quality gate assessment result from backend */
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

/** Gate status result from quality gate check */
export interface QualityGateResult extends QualityGateAssessment {
  checking?: boolean;
  error?: string;
  result?: QualityGateAssessment;
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

export interface OrphanedArtifact {
  id: number;
  type: string;
  source: string;
  external_id: string;
  display_key?: string | null;
  title?: string | null;
  status?: string | null;
  created_at?: string | null;
  suggestion?: string | null;
}

export type OrphanedArtifactsResponse = PaginatedResponse<OrphanedArtifact> & {
  by_type: Record<string, number>;
  by_source: Record<string, number>;
};

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

// =============================================================================
// Sync Health Types
// =============================================================================

export interface SyncSourceHealth {
  source: string;
  connected: boolean;
  last_sync?: string | null;
  artifact_count: number;
  error?: string | null;
}

export interface SyncProjectHealth {
  project_id: number;
  project_name: string;
  jira_key: string;
  last_sync?: string | null;
  artifact_count: number;
  health_status: 'healthy' | 'warning' | 'stale' | 'unknown';
}

export interface SyncHealthResponse {
  health: 'healthy' | 'warning' | 'critical';
  health_score: number;
  summary: {
    total_sources: number;
    connected_sources: number;
    total_artifacts: number;
    last_sync?: string | null;
  };
  sources: SyncSourceHealth[];
  projects: SyncProjectHealth[];
}

export interface DetailedSyncHealthResponse {
  project_id: number;
  project_name: string;
  jira_key: string;
  last_sync?: string | null;
  health_status: 'healthy' | 'warning' | 'stale' | 'unknown';
  by_type: Record<string, number>;
  by_source: Record<string, number>;
  link_coverage: {
    total_artifacts: number;
    linked_artifacts: number;
    coverage_pct: number;
  };
  orphaned_count: number;
  repositories: Array<{
    id: number;
    provider: string;
    repo_slug: string;
    default_branch?: string | null;
  }>;
}

// =============================================================================
// Consistency Check Types
// =============================================================================

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

// =============================================================================
// Capacity Types
// =============================================================================

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

export interface HealthTrend {
  check_date: string;
  happiness_index?: number;
  burnout_risk_score?: number;
}

export interface TeamHealthSummary {
  latest_happiness_index?: number;
  latest_burnout_risk?: number;
  trend_direction: 'improving' | 'declining' | 'stable';
  checks_count: number;
  trend_data: HealthTrend[];
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

export interface FlowMetrics {
  avg_lead_time_days?: number;
  avg_cycle_time_hours?: number;
  avg_throughput_per_day?: number;
  wip_trend: 'increasing' | 'decreasing' | 'stable';
  bottleneck_status?: string;
}

// =============================================================================
// Testing Types (Flaky Tests & Coverage)
// =============================================================================

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

// =============================================================================
// Coverage Types
// =============================================================================

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

export type CoveragePriority = 'critical' | 'high' | 'medium' | 'low';

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

// =============================================================================
// Test Run & Result Types (for Testing.tsx)
// =============================================================================

/** Single test run from CI/CD pipeline */
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

/** Individual test case result */
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

/** Coverage report list item for history display */
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

/** Test trend data point (day aggregation) */
export interface TestTrendPoint {
  day: string;
  total: number;
  failed: number;
}

/** Coverage trend data point (day aggregation) */
export interface CoverageTrendItem {
  day: string;
  avg_line: number;
  avg_branch: number;
  count?: number;
}

/** Flaky test detection item (computed locally) */
export interface LocalFlakyTest {
  id: string;
  classname: string;
  name: string;
  runs: number;
  failRate: number;
  score: number;
}

// =============================================================================
// Analytics API Response Types
// =============================================================================

/** Velocity API response from getVelocity() */
export interface VelocityResponse {
  average_velocity: number;
  velocity_trend?: { week: string; velocity: number }[];
}

/** Single point in burndown chart */
export interface BurndownPoint {
  day: number;
  ideal_remaining?: number;
  remaining?: number;
}

/** Burndown API response from getBurndown() */
export interface BurndownResponse {
  sprint_id?: number;
  ideal_burndown?: BurndownPoint[];
  actual_burndown?: BurndownPoint[];
}

/** Risk item from getRisks() */
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

/** Risks API response from getRisks() */
export interface RisksResponse {
  risks: RiskItem[];
  total?: number;
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

/** Team member activity summary */
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

/** Quality history item from /v1/quality/history */
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

/** Forecast API response from getForecast() */
export interface ForecastResponse {
  estimated_completion_date?: string;
  confidence_level?: 'low' | 'medium' | 'high';
  forecast_available: boolean;
  remaining_work?: number;
  velocity_used?: number;
}

// =============================================================================
// Traceability Rules Types
// =============================================================================

/** React Flow node position */
export interface ReactFlowPosition {
  x: number;
  y: number;
}

/** React Flow node in a traceability rule flow */
export interface ReactFlowNode {
  id: string;
  type: string;
  position: ReactFlowPosition;
  data: Record<string, unknown>;
}

/** React Flow edge connecting nodes */
export interface ReactFlowEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
}

/** Flow JSON structure stored in traceability rules */
export interface FlowJSON {
  nodes: ReactFlowNode[];
  edges: ReactFlowEdge[];
  version?: string;
  metadata?: Record<string, unknown>;
}

/** Traceability rule response from API */
export interface TraceabilityRule {
  id: number;
  name: string;
  description?: string | null;
  flow_json: FlowJSON;
  enabled: boolean;
  category: 'basic' | 'advanced' | 'custom';
  tags: string[];
  project_id?: number | null;
  created_by_id?: number | null;
  schedule_cron?: string | null;
  schedule_enabled?: boolean;
  trigger_on_webhook?: boolean;
  next_scheduled_run?: string | null;
  total_executions: number;
  successful_executions: number;
  failed_executions: number;
  last_executed_at?: string | null;
  created_at: string;
  updated_at: string;
  success_rate?: number | null;
}

/** Data for creating a new traceability rule */
export interface TraceabilityRuleCreate {
  name: string;
  description?: string;
  flow_json: FlowJSON;
  enabled?: boolean;
  category?: 'basic' | 'advanced' | 'custom';
  tags?: string[];
  project_id?: number;
  schedule_cron?: string;
  schedule_enabled?: boolean;
  trigger_on_webhook?: boolean;
}

/** Data for updating a traceability rule */
export interface TraceabilityRuleUpdate {
  name?: string;
  description?: string;
  flow_json?: FlowJSON;
  enabled?: boolean;
  category?: 'basic' | 'advanced' | 'custom';
  tags?: string[];
  project_id?: number;
  schedule_cron?: string;
  schedule_enabled?: boolean;
  trigger_on_webhook?: boolean;
}

/** Traceability rule execution record */
export interface TraceabilityRuleExecution {
  id: number;
  rule_id: number;
  rule_name?: string;
  status: 'success' | 'failed' | 'running' | 'pending';
  started_at?: string;
  completed_at?: string | null;
  executed_at?: string;
  links_created: number;
  links_updated?: number;
  artifacts_processed?: number;
  rolled_back?: boolean;
  error_message?: string | null;
  error_details?: Record<string, unknown> | null;
  execution_log?: {
    errors: string[];
    warnings: string[];
    links_created: number;
    links_updated?: number;
    artifacts_processed?: number;
    rolled_back?: boolean;
  };
}

export interface FlowValidationIssue {
  type: 'error' | 'warning';
  message: string;
  node_id?: string | null;
  edge_id?: string | null;
}

export interface FlowValidationResult {
  valid: boolean;
  errors: FlowValidationIssue[];
  warnings: FlowValidationIssue[];
}

/** Response for listing traceability rules */
export type TraceabilityRuleListResponse = PaginatedResponse<TraceabilityRule>;

/** Response for listing rule executions */
export type TraceabilityRuleExecutionListResponse = PaginatedResponse<TraceabilityRuleExecution>;

/** Options for listing rules */
export interface ListRulesOptions {
  enabled?: boolean;
  category?: string;
  projectId?: number;
  skip?: number;
  limit?: number;
  offset?: number; // legacy alias
}

/** Options for listing rule executions */
export interface ListRuleExecutionsOptions {
  ruleId?: number;
  status?: string;
  skip?: number;
  limit?: number;
  offset?: number; // legacy alias
}

/** Result from executing a rule */
export interface RuleExecutionResult {
  execution_id: number;
  status: 'success' | 'failed';
  links_created: number;
  links_updated: number;
  artifacts_processed: number;
  errors: string[];
  warnings: string[];
  rolled_back: boolean;
}

export interface RuleScheduleUpdate {
  schedule_cron?: string | null;
  schedule_enabled?: boolean;
}

export interface RuleScheduleResponse {
  rule_id: number;
  schedule_cron?: string | null;
  schedule_enabled: boolean;
  next_scheduled_run?: string | null;
}

export interface RuleWebhookResponse {
  rule_id: number;
  trigger_on_webhook: boolean;
  webhook_token?: string | null;
  webhook_url?: string | null;
}

// =============================================================================
// Export Types
// =============================================================================

export type ExportFormat = 'xlsx' | 'csv' | 'pdf';
export type ExportStatus = 'pending' | 'processing' | 'completed' | 'failed';

/** RTM filters for export */
export interface RTMExportFilters {
  row_types?: string[];
  col_types?: string[];
  row_statuses?: string[];
  col_statuses?: string[];
  link_types?: string[];
  min_confidence?: number;
}

/** Request to create an export task */
export interface ExportTaskCreate {
  project_id: number;
  format: ExportFormat;
  matrix_config_id?: number;
  filters?: RTMExportFilters;
  include_details?: boolean;
}

/** Status of an export task */
export interface ExportTaskStatus {
  task_id: string;
  status: ExportStatus;
  progress_pct: number;
  download_url: string | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

// =============================================================================
// RTM Matrix Types
// =============================================================================

/** Filtering options for RTM matrix query */
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

/** Pagination parameters for RTM matrix */
export interface RTMPagination {
  row_skip?: number;
  row_limit?: number;
  col_skip?: number;
  col_limit?: number;
}

/** Lightweight artifact representation for matrix cells */
export interface ArtifactSummary {
  id: number;
  type: string;
  source: string;
  external_id: string;
  display_key?: string | null;
  title?: string | null;
  status?: string | null;
  url?: string | null;
}

/** Link information in a matrix cell */
export interface RTMCellLink {
  link_type: string;
  confidence?: number | null;
  confidence_factors?: Record<string, unknown> | null;
}

/** Single cell in the RTM matrix (matches backend response) */
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

/** Coverage/statistics in RTM matrix response */
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

/** Full RTM matrix response with rows, columns, and cells */
export interface RTMMatrixResponse {
  rows: ArtifactSummary[];
  columns: ArtifactSummary[];
  cells: Record<string, Record<string, RTMCell>>;
  total_rows: number;
  total_columns: number;
  coverage: RTMMatrixCoverage;
  filters_applied: Record<string, unknown>;
}

/** Base schema for saved matrix configurations */
export interface MatrixConfigBase {
  project_id?: number | null;
  name: string;
  description?: string | null;
  filters?: RTMFilters | null;
  pagination?: RTMPagination | null;
  display_options?: Record<string, unknown> | null;
  is_default?: boolean;
}

/** Request to create a matrix configuration */
export interface MatrixConfigCreate extends MatrixConfigBase {}

/** Request to update a matrix configuration */
export interface MatrixConfigUpdate {
  name?: string;
  description?: string | null;
  filters?: RTMFilters | null;
  pagination?: RTMPagination | null;
  display_options?: Record<string, unknown> | null;
  is_default?: boolean;
}

/** Matrix configuration response */
export interface MatrixConfig extends MatrixConfigBase {
  id: number;
  created_by_id?: number | null;
  created_at: string;
  updated_at?: string | null;
}
