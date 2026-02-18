export const DASHBOARD_STORAGE_KEYS = {
  dateRange: 'dashboard_date_range',
  chartView: 'dashboard_chart_view',
  quickFilter: 'dashboard_quick_filter',
  recentProjectIds: 'dashboard_recent_project_ids',
  lastProjectId: 'dashboard_last_project_id',
} as const;

export const DATE_RANGE_OPTIONS = ['7d', '14d', '30d', '90d', '180d', '365d', 'all'] as const;
export type DateRangeOption = (typeof DATE_RANGE_OPTIONS)[number];

export const CHART_VIEW_OPTIONS = ['velocity', 'burndown', 'both', 'distribution'] as const;
export type ChartViewOption = (typeof CHART_VIEW_OPTIONS)[number];

export const QUICK_FILTER_OPTIONS = ['all', 'active', 'recent'] as const;
export type QuickFilterOption = (typeof QUICK_FILTER_OPTIONS)[number];

export const DASHBOARD_DEFAULTS = {
  dateRange: '30d' as DateRangeOption,
  chartView: 'both' as ChartViewOption,
  quickFilter: 'recent' as QuickFilterOption,
  recentProjectsLimit: 5,
};

export const VELOCITY_SPRINTS_COUNT_MAP: Record<DateRangeOption, number> = {
  '7d': 2,
  '14d': 3,
  '30d': 5,
  '90d': 8,
  '180d': 12,
  '365d': 16,
  all: 20,
};

export const DATE_RANGE_DAYS_MAP: Record<Exclude<DateRangeOption, 'all'>, number> = {
  '7d': 7,
  '14d': 14,
  '30d': 30,
  '90d': 90,
  '180d': 180,
  '365d': 365,
};

export interface TaskScope {
  total?: number;
  fetched: number;
  hasNext: boolean;
  isPartial: boolean;
  capHit?: boolean;
}

export const TASK_SCOPE_DEFAULTS = {
  pageSize: 500,
  maxPages: 40,
  maxTasks: 20000,
};

export const PARTIAL_SCOPE_LABEL = 'Showing partial data';

export const DASHBOARD_TEST_IDS = {
  partialScopeBadge: 'dashboard-partial-scope',
} as const;

export const isDateRangeOption = (value: unknown): value is DateRangeOption =>
  typeof value === 'string' && (DATE_RANGE_OPTIONS as readonly string[]).includes(value);

export const isChartViewOption = (value: unknown): value is ChartViewOption =>
  typeof value === 'string' && (CHART_VIEW_OPTIONS as readonly string[]).includes(value);

export const isQuickFilterOption = (value: unknown): value is QuickFilterOption =>
  typeof value === 'string' && (QUICK_FILTER_OPTIONS as readonly string[]).includes(value);

export const parseDateRangeOption = (value: unknown): DateRangeOption =>
  isDateRangeOption(value) ? value : DASHBOARD_DEFAULTS.dateRange;

export const parseChartViewOption = (value: unknown): ChartViewOption =>
  isChartViewOption(value) ? value : DASHBOARD_DEFAULTS.chartView;

export const parseQuickFilterOption = (value: unknown): QuickFilterOption =>
  isQuickFilterOption(value) ? value : DASHBOARD_DEFAULTS.quickFilter;

export const getDateRangeDays = (dateRange: DateRangeOption): number | null => {
  if (dateRange === 'all') return null;
  return DATE_RANGE_DAYS_MAP[dateRange];
};

export const getUpcomingHorizonDays = (dateRange: DateRangeOption): number => {
  const days = getDateRangeDays(dateRange);
  return days ?? 365;
};

export const formatTaskScopeLabel = (scope: TaskScope): string => {
  if (!scope.isPartial) {
    if (typeof scope.total === 'number') {
      return `Loaded ${scope.fetched} of ${scope.total} tasks`;
    }
    return `Loaded ${scope.fetched} tasks`;
  }

  const suffix = scope.capHit ? ' (cap reached)' : '';
  if (typeof scope.total === 'number') {
    return `${PARTIAL_SCOPE_LABEL}: ${scope.fetched}/${scope.total} tasks${suffix}`;
  }
  return `${PARTIAL_SCOPE_LABEL}: ${scope.fetched} tasks${suffix}`;
};

export const parseNumberListFromStorage = (value: string | null): number[] => {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map((item) => Number(item))
      .filter((item) => Number.isInteger(item) && item > 0);
  } catch {
    return [];
  }
};
