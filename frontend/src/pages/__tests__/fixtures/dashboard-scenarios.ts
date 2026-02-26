export const DAY_MS = 24 * 60 * 60 * 1000;
export const SCENARIO_NOW = Date.parse('2026-02-19T12:00:00.000Z');

export type DashboardScenarioId =
  | 'date_range_empty_window'
  | 'date_range_preserves_burndown_sprint_context'
  | 'no_active_sprint_wip'
  | 'partial_analytics_velocity_empty'
  | 'multi_project_quick_filter'
  | 'chart_view_velocity'
  | 'chart_view_burndown'
  | 'chart_view_both'
  | 'chart_view_distribution';

export interface DashboardScenarioDefinition {
  id: DashboardScenarioId;
  risk: string;
  expectedSignal: string;
}

export const DASHBOARD_SCENARIO_MATRIX: DashboardScenarioDefinition[] = [
  {
    id: 'date_range_empty_window',
    risk: 'blank panels when selected range has no activity',
    expectedSignal: 'explicit empty-state in upcoming panel',
  },
  {
    id: 'date_range_preserves_burndown_sprint_context',
    risk: 'date filter accidentally mutates sprint-scoped burndown source',
    expectedSignal: 'burndown requests stay pinned to active sprint id',
  },
  {
    id: 'no_active_sprint_wip',
    risk: 'WIP widget crashes when active sprint is unavailable',
    expectedSignal: 'No active sprint fallback is visible',
  },
  {
    id: 'partial_analytics_velocity_empty',
    risk: 'chart panels render misleading placeholders for sparse analytics',
    expectedSignal: 'velocity empty-state message is visible',
  },
  {
    id: 'multi_project_quick_filter',
    risk: 'quick filter picks nondeterministic project context',
    expectedSignal: 'active/recent transitions map to deterministic project ids',
  },
  {
    id: 'chart_view_velocity',
    risk: 'wrong chart visibility for velocity mode',
    expectedSignal: 'only velocity panel is rendered',
  },
  {
    id: 'chart_view_burndown',
    risk: 'wrong chart visibility for burndown mode',
    expectedSignal: 'only burndown panel is rendered',
  },
  {
    id: 'chart_view_both',
    risk: 'wrong chart visibility for combined mode',
    expectedSignal: 'velocity and burndown panels are rendered',
  },
  {
    id: 'chart_view_distribution',
    risk: 'wrong chart visibility for distribution mode',
    expectedSignal: 'only distribution panel is rendered',
  },
];

export const activeSprintScenario = {
  id: 1201,
  sprint_id: 1201,
  name: 'Sprint Active',
  state: 'active',
  start_date: new Date(SCENARIO_NOW - 5 * DAY_MS).toISOString(),
  end_date: new Date(SCENARIO_NOW + 5 * DAY_MS).toISOString(),
};

export const dateRangeScenarioTasks = [
  {
    id: 3001,
    jira_id: 'DSH-3001',
    key: 'DSH-3001',
    summary: 'Recent due item',
    status: 'In Progress',
    due_date: new Date(SCENARIO_NOW + 2 * DAY_MS).toISOString(),
    updated_date: new Date(SCENARIO_NOW - 2 * DAY_MS).toISOString(),
    project_id: 1,
    estimate_hours: 3,
  },
  {
    id: 3002,
    jira_id: 'DSH-3002',
    key: 'DSH-3002',
    summary: 'Older activity item',
    status: 'Todo',
    due_date: new Date(SCENARIO_NOW + 3 * DAY_MS).toISOString(),
    updated_date: new Date(SCENARIO_NOW - 20 * DAY_MS).toISOString(),
    project_id: 1,
    estimate_hours: 2,
  },
];

export const emptyWindowScenarioTasks = [
  {
    id: 3003,
    jira_id: 'DSH-3003',
    key: 'DSH-3003',
    summary: 'Outside range item A',
    status: 'Todo',
    due_date: new Date(SCENARIO_NOW + 20 * DAY_MS).toISOString(),
    updated_date: new Date(SCENARIO_NOW - 60 * DAY_MS).toISOString(),
    project_id: 1,
    estimate_hours: 2,
  },
  {
    id: 3004,
    jira_id: 'DSH-3004',
    key: 'DSH-3004',
    summary: 'Outside range item B',
    status: 'In Progress',
    due_date: new Date(SCENARIO_NOW + 25 * DAY_MS).toISOString(),
    updated_date: new Date(SCENARIO_NOW - 45 * DAY_MS).toISOString(),
    project_id: 1,
    estimate_hours: 5,
  },
];

export const quickFilterProjectsScenario = [
  {
    id: 1,
    jira_key: 'ACT',
    name: 'Active Platform',
    status: 'active',
    total_tasks: 12,
  },
  {
    id: 2,
    jira_key: 'REC',
    name: 'Recent Legacy',
    status: 'paused',
    total_tasks: 8,
  },
];

export const velocitySparseScenario = {
  average_velocity: 0,
  sprints_analyzed: 0,
  velocity_trend: 'insufficient_data' as const,
  sprint_velocities: [],
};
