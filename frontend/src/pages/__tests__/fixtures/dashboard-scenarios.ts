export const DAY_MS = 24 * 60 * 60 * 1000;
export const SCENARIO_NOW = Date.parse('2026-02-19T12:00:00.000Z');

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

