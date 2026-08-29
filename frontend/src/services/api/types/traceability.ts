// traceability domain API types (split from types.ts, wave E5).

import type { PaginatedResponse, RTMExportFilters, RTMFilters, RTMPagination, ReactFlowEdge, ReactFlowNode } from './common';
import type { GitImportSummary } from './integrations';



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
  warnings: string[];
  sources: {
    jira?: TraceabilityBackfillSourceResult;
    confluence?: TraceabilityBackfillSourceResult;
    git?: GitImportSummary;
  };
  git?: GitImportSummary;
}

export interface TraceabilityBackfillSourceResult {
  created: number;
  updated: number;
  warnings?: string[];
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

export type ReviewItemStatus = 'pending' | 'claimed' | 'resolved' | 'rejected';

export interface ReviewItem {
  id: number;
  tenant_id?: string | null;
  project_id?: number | null;
  artifact_id: number;
  rule_id?: number | null;
  rule_execution_id?: number | null;
  node_id: string;
  status: ReviewItemStatus;
  priority: string;
  reason?: string | null;
  assigned_to_id?: number | null;
  created_by_id?: number | null;
  resolved_by_id?: number | null;
  resolved_at?: string | null;
  meta?: Record<string, unknown> | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ReviewItemListResponse {
  total: number;
  items: ReviewItem[];
}

export interface FlowMetrics {
  avg_lead_time_days?: number;
  avg_cycle_time_hours?: number;
  avg_throughput_per_day?: number;
  wip_trend: 'increasing' | 'decreasing' | 'stable';
  bottleneck_status?: string;
}

export interface FlowJSON {
  nodes: ReactFlowNode[];
  edges: ReactFlowEdge[];
  version?: string;
  metadata?: Record<string, unknown>;
}

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
  execute_on_sync_complete?: boolean;
  next_scheduled_run?: string | null;
  total_executions: number;
  successful_executions: number;
  failed_executions: number;
  last_executed_at?: string | null;
  created_at: string;
  updated_at: string;
  success_rate?: number | null;
}

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
  execute_on_sync_complete?: boolean;
}

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
  execute_on_sync_complete?: boolean;
}

export interface TraceabilityRuleExecution {
  id: number;
  rule_id: number;
  rule_name?: string;
  status: 'success' | 'failed' | 'running' | 'pending';
  trigger_source?: string | null;
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

export type TraceabilityRuleListResponse = PaginatedResponse<TraceabilityRule>;

export type TraceabilityRuleExecutionListResponse = PaginatedResponse<TraceabilityRuleExecution>;

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

export type ExportFormat = 'xlsx' | 'csv' | 'pdf';

export type ExportStatus = 'pending' | 'processing' | 'completed' | 'failed';

export interface ExportTaskCreate {
  project_id: number;
  format: ExportFormat;
  matrix_config_id?: number;
  filters?: RTMExportFilters;
  include_details?: boolean;
}

export interface ExportTaskStatus {
  task_id: string;
  status: ExportStatus;
  progress_pct: number;
  download_url: string | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

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

export interface MatrixConfigBase {
  project_id?: number | null;
  name: string;
  description?: string | null;
  filters?: RTMFilters | null;
  pagination?: RTMPagination | null;
  display_options?: Record<string, unknown> | null;
  is_default?: boolean;
}

export type MatrixConfigCreate = MatrixConfigBase;

export interface MatrixConfigUpdate {
  name?: string;
  description?: string | null;
  filters?: RTMFilters | null;
  pagination?: RTMPagination | null;
  display_options?: Record<string, unknown> | null;
  is_default?: boolean;
}

export interface MatrixConfig extends MatrixConfigBase {
  id: number;
  created_by_id?: number | null;
  created_at: string;
  updated_at?: string | null;
}
