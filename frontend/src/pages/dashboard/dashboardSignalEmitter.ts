import {
  DASHBOARD_GUARDRAIL_TARGETS,
  isDashboardChartWarning,
} from './dashboardGuardrails';

type DashboardEnvelope = {
  source: 'dashboard';
  emittedAt: string;
  [key: string]: unknown;
};

type RuntimeWarningKey = keyof typeof DASHBOARD_GUARDRAIL_TARGETS.runtimeWarnings;

const emitWarning = (signal: string, payload: Record<string, unknown>): DashboardEnvelope => {
  const envelope: DashboardEnvelope = {
    source: 'dashboard',
    emittedAt: new Date().toISOString(),
    ...payload,
  };

  console.warn(signal, envelope);
  return envelope;
};

export const emitDashboardRefreshLoop = (payload: {
  eventsInWindow: number;
  threshold: number;
  windowMs: number;
}): DashboardEnvelope => {
  return emitWarning(DASHBOARD_GUARDRAIL_TARGETS.refreshLoop.signal, payload);
};

export const emitDashboardFilterBudgetExceeded = (payload: {
  duration: number;
  budget: number;
  sampleWindow: number;
}): DashboardEnvelope => {
  return emitWarning(DASHBOARD_GUARDRAIL_TARGETS.filterApplyBudget.signal, payload);
};

export const emitDashboardInitBudgetExceeded = (payload: {
  duration: number;
  budget: number;
  sampleWindow: number;
}): DashboardEnvelope => {
  return emitWarning(DASHBOARD_GUARDRAIL_TARGETS.initBudget.signal, payload);
};

export const emitDashboardRuntimeWarning = (
  key: RuntimeWarningKey,
  payload: Record<string, unknown>
): DashboardEnvelope => {
  return emitWarning(DASHBOARD_GUARDRAIL_TARGETS.runtimeWarnings[key], payload);
};

export const emitDashboardChartWarningGate = (
  args: unknown[]
): DashboardEnvelope | null => {
  if (!isDashboardChartWarning(args)) {
    return null;
  }

  return emitWarning(DASHBOARD_GUARDRAIL_TARGETS.chartWarnings.signal, {
    message: args.map((entry) => String(entry)).join(' '),
  });
};
