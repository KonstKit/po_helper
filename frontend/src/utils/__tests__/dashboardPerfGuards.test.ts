import { beforeEach, describe, expect, it } from 'vitest';
import {
  getP95,
  getPerfSamples,
  isAboveBudget,
  recordDuration,
  resetDashboardPerfGuards,
  shouldReportBudgetBreach,
} from '../dashboardPerfGuards';

describe('dashboardPerfGuards', () => {
  beforeEach(() => {
    resetDashboardPerfGuards();
  });

  it('keeps a bounded rolling window of samples', () => {
    for (let idx = 1; idx <= 25; idx += 1) {
      recordDuration('filter_apply_ms', idx * 10);
    }

    const samples = getPerfSamples('filter_apply_ms');
    expect(samples).toHaveLength(20);
    expect(samples[0]).toBe(60);
    expect(samples[samples.length - 1]).toBe(250);
  });

  it('computes p95 deterministically using nearest-rank semantics', () => {
    [40, 80, 120, 160, 200].forEach((value) => {
      recordDuration('dashboard_init_ms', value);
    });

    expect(getP95('dashboard_init_ms')).toBe(200);
  });

  it('reports budget breach only once per metric budget latch', () => {
    [100, 120, 800, 900, 950].forEach((value) => {
      recordDuration('dashboard_init_ms', value);
    });

    expect(isAboveBudget('dashboard_init_ms')).toBe(true);
    expect(shouldReportBudgetBreach('dashboard_init_ms')).toBe(true);
    expect(shouldReportBudgetBreach('dashboard_init_ms')).toBe(false);
  });

  it('treats invalid durations as zero and handles empty metrics', () => {
    recordDuration('filter_apply_ms', Number.NaN);
    recordDuration('filter_apply_ms', Number.POSITIVE_INFINITY);
    recordDuration('filter_apply_ms', -100);

    expect(getPerfSamples('filter_apply_ms')).toEqual([0, 0, 0]);
    expect(getP95('dashboard_init_ms')).toBeNull();
  });
});

