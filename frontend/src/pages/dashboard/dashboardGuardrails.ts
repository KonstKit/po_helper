import { DASHBOARD_PERF_BUDGETS } from '../../utils/dashboardPerfGuards';

export const DASHBOARD_REFRESH_LOOP_WINDOW_MS = 30_000;
export const DASHBOARD_REFRESH_LOOP_EVENT_THRESHOLD = 6;

export const DASHBOARD_CHART_WARNING_PATTERNS = [
  /filler plugin/i,
  /annotation plugin/i,
  /chart\.js.*warning/i,
  /failed to register scale/i,
] as const;

export const isDashboardChartWarning = (args: unknown[]): boolean => {
  const message = args.map((entry) => String(entry)).join(' ');
  return DASHBOARD_CHART_WARNING_PATTERNS.some((pattern) => pattern.test(message));
};

export const DASHBOARD_GUARDRAIL_TARGETS = {
  refreshLoop: {
    signal: '[DashboardGuardrails] refresh_loop_detected',
    threshold: DASHBOARD_REFRESH_LOOP_EVENT_THRESHOLD,
    windowMs: DASHBOARD_REFRESH_LOOP_WINDOW_MS,
  },
  filterApplyBudget: {
    signal: '[DashboardGuardrails] filter_apply_budget_exceeded',
    p95BudgetMs: DASHBOARD_PERF_BUDGETS.filter_apply_ms,
    sampleWindow: 20,
  },
  initBudget: {
    signal: '[DashboardGuardrails] init_budget_exceeded',
    p95BudgetMs: DASHBOARD_PERF_BUDGETS.dashboard_init_ms,
    sampleWindow: 20,
  },
  chartWarnings: {
    signal: 'dashboard_chart_warning_gate',
    patterns: DASHBOARD_CHART_WARNING_PATTERNS.map((pattern) => pattern.source),
  },
  runtimeWarnings: {
    refreshMetricsFailed: '[DashboardGuardrails] refresh_metrics_failed',
    velocityLoadFailed: '[DashboardGuardrails] velocity_load_failed',
    wipLoadFailed: '[DashboardGuardrails] wip_load_failed',
    burndownLoadFailed: '[DashboardGuardrails] burndown_load_failed',
    websocketCloseFailed: '[DashboardGuardrails] websocket_close_failed',
    websocketMessageFailed: '[DashboardGuardrails] websocket_message_processing_failed',
    websocketError: '[DashboardGuardrails] websocket_error',
    websocketCleanupCloseFailed: '[DashboardGuardrails] websocket_cleanup_close_failed',
    integrationsStatusFailed: '[DashboardGuardrails] integrations_status_check_failed',
  },
} as const;
