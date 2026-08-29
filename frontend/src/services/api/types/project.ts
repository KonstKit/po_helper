// project domain API types (split from types.ts, wave E5).

import type { RepositoryInfo } from './integrations';



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

export interface ProjectRepositoryLink {
  id: number;
  project_id: number;
  repository_id: number;
  is_primary: boolean;
  created_at: string;
  updated_at?: string | null;
  repository: RepositoryInfo;
}
