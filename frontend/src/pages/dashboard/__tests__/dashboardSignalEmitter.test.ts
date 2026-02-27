import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  DASHBOARD_GUARDRAIL_TARGETS,
  isDashboardChartWarning,
} from '../dashboardGuardrails';
import {
  emitDashboardChartWarningGate,
  emitDashboardFilterBudgetExceeded,
  emitDashboardInitBudgetExceeded,
  emitDashboardRefreshLoop,
} from '../dashboardSignalEmitter';

describe('dashboardSignalEmitter', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('emits refresh-loop signal with normalized envelope payload', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

    emitDashboardRefreshLoop({
      eventsInWindow: 7,
      threshold: 6,
      windowMs: 30000,
    });

    expect(warnSpy).toHaveBeenCalledWith(
      DASHBOARD_GUARDRAIL_TARGETS.refreshLoop.signal,
      expect.objectContaining({
        source: 'dashboard',
        eventsInWindow: 7,
        threshold: 6,
        windowMs: 30000,
        emittedAt: expect.any(String),
      })
    );
  });

  it('emits filter-apply budget signal with guardrail payload fields', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

    emitDashboardFilterBudgetExceeded({
      duration: 410,
      budget: DASHBOARD_GUARDRAIL_TARGETS.filterApplyBudget.p95BudgetMs,
      sampleWindow: DASHBOARD_GUARDRAIL_TARGETS.filterApplyBudget.sampleWindow,
    });

    expect(warnSpy).toHaveBeenCalledWith(
      DASHBOARD_GUARDRAIL_TARGETS.filterApplyBudget.signal,
      expect.objectContaining({
        source: 'dashboard',
        duration: 410,
        budget: DASHBOARD_GUARDRAIL_TARGETS.filterApplyBudget.p95BudgetMs,
        sampleWindow: DASHBOARD_GUARDRAIL_TARGETS.filterApplyBudget.sampleWindow,
        emittedAt: expect.any(String),
      })
    );
  });

  it('emits init-budget signal with guardrail payload fields', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

    emitDashboardInitBudgetExceeded({
      duration: 760,
      budget: DASHBOARD_GUARDRAIL_TARGETS.initBudget.p95BudgetMs,
      sampleWindow: DASHBOARD_GUARDRAIL_TARGETS.initBudget.sampleWindow,
    });

    expect(warnSpy).toHaveBeenCalledWith(
      DASHBOARD_GUARDRAIL_TARGETS.initBudget.signal,
      expect.objectContaining({
        source: 'dashboard',
        duration: 760,
        budget: DASHBOARD_GUARDRAIL_TARGETS.initBudget.p95BudgetMs,
        sampleWindow: DASHBOARD_GUARDRAIL_TARGETS.initBudget.sampleWindow,
        emittedAt: expect.any(String),
      })
    );
  });

  it('emits chart-warning gate only when warning matches scoped dashboard patterns', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const positive = ['Chart.js warning: filler plugin is not registered'];
    const negative = ['network error while refreshing metrics'];

    expect(isDashboardChartWarning(positive)).toBe(true);
    expect(isDashboardChartWarning(negative)).toBe(false);

    expect(emitDashboardChartWarningGate(positive)).not.toBeNull();
    expect(emitDashboardChartWarningGate(negative)).toBeNull();

    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy).toHaveBeenCalledWith(
      DASHBOARD_GUARDRAIL_TARGETS.chartWarnings.signal,
      expect.objectContaining({
        source: 'dashboard',
        message: expect.stringContaining('filler plugin'),
        emittedAt: expect.any(String),
      })
    );
  });
});
