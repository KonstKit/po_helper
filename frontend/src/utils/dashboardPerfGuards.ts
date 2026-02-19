const DEFAULT_SAMPLE_WINDOW = 20;

export const DASHBOARD_PERF_BUDGETS = {
  filter_apply_ms: 300,
  dashboard_init_ms: 700,
} as const;

export type DashboardPerfMetric = keyof typeof DASHBOARD_PERF_BUDGETS;

const perfSamplesByMetric = new Map<DashboardPerfMetric, number[]>();
const budgetWarningLatches = new Set<string>();

const sanitizeDuration = (value: number): number => {
  if (!Number.isFinite(value) || value < 0) {
    return 0;
  }
  return value;
};

const calcP95 = (samples: number[]): number | null => {
  if (samples.length === 0) {
    return null;
  }
  const sorted = [...samples].sort((left, right) => left - right);
  const rank = Math.max(1, Math.ceil(0.95 * sorted.length));
  return sorted[rank - 1] ?? null;
};

export const getPerfSamples = (metric: DashboardPerfMetric): number[] => {
  return [...(perfSamplesByMetric.get(metric) ?? [])];
};

export const recordDuration = (
  metric: DashboardPerfMetric,
  durationMs: number,
  windowSize = DEFAULT_SAMPLE_WINDOW
): { count: number; p95: number | null } => {
  const safeWindowSize = Math.max(1, Math.floor(windowSize));
  const samples = perfSamplesByMetric.get(metric) ?? [];
  samples.push(sanitizeDuration(durationMs));

  if (samples.length > safeWindowSize) {
    samples.splice(0, samples.length - safeWindowSize);
  }

  perfSamplesByMetric.set(metric, samples);
  return {
    count: samples.length,
    p95: calcP95(samples),
  };
};

export const getP95 = (metric: DashboardPerfMetric): number | null => {
  const samples = perfSamplesByMetric.get(metric) ?? [];
  return calcP95(samples);
};

export const isAboveBudget = (
  metric: DashboardPerfMetric,
  budgetMs = DASHBOARD_PERF_BUDGETS[metric]
): boolean => {
  const p95 = getP95(metric);
  return p95 !== null && p95 > budgetMs;
};

export const shouldReportBudgetBreach = (
  metric: DashboardPerfMetric,
  budgetMs = DASHBOARD_PERF_BUDGETS[metric]
): boolean => {
  if (!isAboveBudget(metric, budgetMs)) {
    return false;
  }
  const latchKey = `${metric}:${budgetMs}`;
  if (budgetWarningLatches.has(latchKey)) {
    return false;
  }
  budgetWarningLatches.add(latchKey);
  return true;
};

export const resetDashboardPerfGuards = (): void => {
  perfSamplesByMetric.clear();
  budgetWarningLatches.clear();
};

