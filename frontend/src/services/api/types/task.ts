// task domain API types (split from types.ts, wave E5).



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
