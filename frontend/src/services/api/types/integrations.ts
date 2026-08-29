// integrations domain API types (split from types.ts, wave E5).

import type { QualityPullRequest } from './quality';



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

export type RepositoryProvider = 'github' | 'gitlab';

export interface RepositoryInfo {
  id: number;
  provider: RepositoryProvider;
  repo_slug: string;
  default_branch?: string | null;
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

export interface PullRequestsResponse {
  total: number;
  pull_requests: QualityPullRequest[];
}
