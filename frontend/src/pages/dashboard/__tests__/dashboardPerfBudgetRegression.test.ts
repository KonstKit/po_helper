import { beforeEach, describe, expect, it } from 'vitest';
import { DASHBOARD_PERF_BUDGETS, getP95, isAboveBudget, recordDuration, resetDashboardPerfGuards } from '../../../utils/dashboardPerfGuards';
import { makeSelectDashboardDerivedState } from '../dashboardSelectors';

const DAY_MS = 24 * 60 * 60 * 1000;
const NOW = Date.parse('2026-02-19T12:00:00.000Z');

const buildTasks = (count: number) =>
  Array.from({ length: count }, (_, index) => {
    const updated = new Date(NOW - (index % 40) * DAY_MS).toISOString();
    const resolved = index % 3 === 0 ? new Date(NOW - (index % 20) * DAY_MS).toISOString() : null;
    return {
      id: index + 1,
      key: `BENCH-${index + 1}`,
      summary: `Task ${index + 1}`,
      status:
        index % 7 === 0
          ? 'Blocked'
          : index % 3 === 0
            ? 'Done'
            : index % 2 === 0
              ? 'In Progress'
              : 'Todo',
      updated_date: updated,
      resolved_date: resolved,
      due_date: new Date(NOW + ((index % 14) - 7) * DAY_MS).toISOString(),
      estimate_hours: (index % 8) + 1,
      project_id: 1,
      is_blocker: index % 9 === 0,
    };
  });

describe('dashboard perf guard regression benchmarks', () => {
  beforeEach(() => {
    resetDashboardPerfGuards();
  });

  it('keeps filter_apply_ms p95 under budget for 1k-task selector pass', () => {
    const selectDerivedState = makeSelectDashboardDerivedState();
    const tasks = buildTasks(1000);

    for (let index = 0; index < 20; index += 1) {
      const startedAt = performance.now();
      selectDerivedState({
        projectTasks: tasks,
        dateRange: '30d',
        now: NOW,
        velocityData: {
          average_velocity: 8,
          velocity_trend: 'stable',
          sprints_analyzed: 5,
          sprint_velocities: [
            { sprint_id: 1, sprint_name: 'Sprint 1', velocity: 6 },
            { sprint_id: 2, sprint_name: 'Sprint 2', velocity: 8 },
            { sprint_id: 3, sprint_name: 'Sprint 3', velocity: 10 },
          ],
        },
        burndownTimeline: {
          sprint_id: 1,
          ideal_burndown: [
            { day: 1, ideal_remaining: 20 },
            { day: 2, ideal_remaining: 14 },
            { day: 3, ideal_remaining: 8 },
          ],
          actual_burndown: [
            { day: 1, remaining: 18 },
            { day: 2, remaining: 13 },
            { day: 3, remaining: 9 },
          ],
        },
      });
      recordDuration('filter_apply_ms', performance.now() - startedAt, 20);
    }

    expect(isAboveBudget('filter_apply_ms', DASHBOARD_PERF_BUDGETS.filter_apply_ms)).toBe(false);
    expect(getP95('filter_apply_ms')).toBeLessThanOrEqual(DASHBOARD_PERF_BUDGETS.filter_apply_ms);
  });

  it('keeps dashboard_init_ms p95 under budget for 1k-task init pass', () => {
    const selectDerivedState = makeSelectDashboardDerivedState();
    const tasks = buildTasks(1000);

    for (let index = 0; index < 20; index += 1) {
      const startedAt = performance.now();
      const derived = selectDerivedState({
        projectTasks: tasks,
        dateRange: '90d',
        now: NOW,
        velocityData: {
          average_velocity: 7,
          velocity_trend: 'increasing',
          sprints_analyzed: 8,
          sprint_velocities: [
            { sprint_id: 10, sprint_name: 'Sprint 10', velocity: 5 },
            { sprint_id: 11, sprint_name: 'Sprint 11', velocity: 7 },
            { sprint_id: 12, sprint_name: 'Sprint 12', velocity: 9 },
          ],
        },
        burndownTimeline: {
          sprint_id: 12,
          ideal_burndown: [{ day: 1, ideal_remaining: 24 }],
          actual_burndown: [{ day: 1, remaining: 22 }],
        },
      });
      // Touch computed data to avoid dead-code optimization in test runtimes.
      expect(derived.stats.totalTasks).toBe(1000);
      recordDuration('dashboard_init_ms', performance.now() - startedAt, 20);
    }

    expect(isAboveBudget('dashboard_init_ms', DASHBOARD_PERF_BUDGETS.dashboard_init_ms)).toBe(false);
    expect(getP95('dashboard_init_ms')).toBeLessThanOrEqual(DASHBOARD_PERF_BUDGETS.dashboard_init_ms);
  });
});
