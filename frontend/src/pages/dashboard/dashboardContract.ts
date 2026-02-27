export const DASHBOARD_STORAGE_KEYS = {
  dateRange: 'dashboard_date_range',
  chartView: 'dashboard_chart_view',
  quickFilter: 'dashboard_quick_filter',
  recentProjectIds: 'dashboard_recent_project_ids',
  lastProjectId: 'dashboard_last_project_id',
} as const;

export const DASHBOARD_STORAGE_CONTRACT = {
  versionKey: 'dashboard_contract_version',
  currentVersion: 2,
} as const;

export const DASHBOARD_STORAGE_LEGACY_KEYS = {
  dateRange: ['date_range'],
  chartView: ['chart_view'],
  quickFilter: ['quick_filter'],
  recentProjectIds: ['recent_project_ids'],
  lastProjectId: ['last_project_id'],
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

export type TaskScopeAnomalyCode =
  | 'negative_fetched'
  | 'fetched_exceeds_total'
  | 'has_next_conflict'
  | 'partial_flag_conflict';

export interface TaskScopeAnomaly {
  code: TaskScopeAnomalyCode;
  message: string;
}

export const TASK_SCOPE_DEFAULTS = {
  pageSize: 500,
  maxPages: 40,
  maxTasks: 20000,
};

export const PARTIAL_SCOPE_LABEL = 'Showing partial data';

export const DASHBOARD_TEST_IDS = {
  page: 'dashboard-page',
  header: 'dashboard-header',
  viewDetails: 'dashboard-view-details',
  filtersRoot: 'dashboard-filters',
  filterProject: 'dashboard-filter-project',
  filterDateRange: 'dashboard-filter-date-range',
  filterChartView: 'dashboard-filter-chart-view',
  sectionCharts: 'dashboard-section-charts',
  sectionInsights: 'dashboard-section-insights',
  sectionStats: 'dashboard-section-stats',
  chartVelocity: 'dashboard-chart-velocity',
  chartBurndown: 'dashboard-chart-burndown',
  chartDistribution: 'dashboard-chart-distribution',
  riskPanel: 'dashboard-risk-panel',
  riskItem: 'dashboard-risk-item',
  upcomingPanel: 'dashboard-upcoming-panel',
  upcomingItem: 'dashboard-upcoming-item',
  cardTotal: 'card-total',
  cardCompleted: 'card-completed',
  cardInProgress: 'card-in-progress',
  cardBlockers: 'card-blockers',
  cardBudget: 'card-budget',
  cardRoi: 'card-roi',
  cardWip: 'card-wip',
  partialScopeBadge: 'dashboard-partial-scope',
  taskScopeAnomalyBadge: 'dashboard-task-scope-anomaly',
  drilldownItem: 'dashboard-drilldown-item',
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

const parseLastProjectId = (value: string | null): number | null => {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
};

interface DashboardStorageLike {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
  removeItem: (key: string) => void;
}

export interface DashboardPersistedState {
  dateRange: DateRangeOption;
  chartView: ChartViewOption;
  quickFilter: QuickFilterOption;
  recentProjectIds: number[];
  lastProjectId: number | null;
  version: number;
}

const getLocalStorageSafe = (): DashboardStorageLike | null => {
  try {
    if (typeof localStorage === 'undefined') return null;
    return localStorage;
  } catch {
    return null;
  }
};

const readStoredValue = (
  storage: DashboardStorageLike,
  key: string,
  legacyKeys: readonly string[]
): string | null => {
  const direct = storage.getItem(key);
  if (direct !== null) {
    return direct;
  }

  for (const legacyKey of legacyKeys) {
    const legacyValue = storage.getItem(legacyKey);
    if (legacyValue !== null) {
      return legacyValue;
    }
  }

  return null;
};

export const migrateDashboardStorageContract = (
  storage: DashboardStorageLike | null = getLocalStorageSafe()
): DashboardPersistedState => {
  const fallback: DashboardPersistedState = {
    dateRange: DASHBOARD_DEFAULTS.dateRange,
    chartView: DASHBOARD_DEFAULTS.chartView,
    quickFilter: DASHBOARD_DEFAULTS.quickFilter,
    recentProjectIds: [],
    lastProjectId: null,
    version: DASHBOARD_STORAGE_CONTRACT.currentVersion,
  };

  if (!storage) {
    return fallback;
  }

  const dateRange = parseDateRangeOption(
    readStoredValue(storage, DASHBOARD_STORAGE_KEYS.dateRange, DASHBOARD_STORAGE_LEGACY_KEYS.dateRange)
  );
  const chartView = parseChartViewOption(
    readStoredValue(storage, DASHBOARD_STORAGE_KEYS.chartView, DASHBOARD_STORAGE_LEGACY_KEYS.chartView)
  );
  const quickFilter = parseQuickFilterOption(
    readStoredValue(storage, DASHBOARD_STORAGE_KEYS.quickFilter, DASHBOARD_STORAGE_LEGACY_KEYS.quickFilter)
  );
  const recentProjectIds = parseNumberListFromStorage(
    readStoredValue(
      storage,
      DASHBOARD_STORAGE_KEYS.recentProjectIds,
      DASHBOARD_STORAGE_LEGACY_KEYS.recentProjectIds
    )
  ).slice(0, DASHBOARD_DEFAULTS.recentProjectsLimit);
  const lastProjectId = parseLastProjectId(
    readStoredValue(storage, DASHBOARD_STORAGE_KEYS.lastProjectId, DASHBOARD_STORAGE_LEGACY_KEYS.lastProjectId)
  );

  const nextState: DashboardPersistedState = {
    dateRange,
    chartView,
    quickFilter,
    recentProjectIds,
    lastProjectId,
    version: DASHBOARD_STORAGE_CONTRACT.currentVersion,
  };

  storage.setItem(DASHBOARD_STORAGE_KEYS.dateRange, nextState.dateRange);
  storage.setItem(DASHBOARD_STORAGE_KEYS.chartView, nextState.chartView);
  storage.setItem(DASHBOARD_STORAGE_KEYS.quickFilter, nextState.quickFilter);
  storage.setItem(DASHBOARD_STORAGE_KEYS.recentProjectIds, JSON.stringify(nextState.recentProjectIds));
  if (nextState.lastProjectId !== null) {
    storage.setItem(DASHBOARD_STORAGE_KEYS.lastProjectId, String(nextState.lastProjectId));
  } else {
    storage.removeItem(DASHBOARD_STORAGE_KEYS.lastProjectId);
  }
  storage.setItem(DASHBOARD_STORAGE_CONTRACT.versionKey, String(DASHBOARD_STORAGE_CONTRACT.currentVersion));

  Object.values(DASHBOARD_STORAGE_LEGACY_KEYS)
    .flat()
    .forEach((legacyKey) => {
      storage.removeItem(legacyKey);
    });

  return nextState;
};

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

export const detectTaskScopeAnomaly = (scope: TaskScope | undefined): TaskScopeAnomaly | null => {
  if (!scope) return null;

  if (scope.fetched < 0) {
    return {
      code: 'negative_fetched',
      message: 'Task scope metadata is inconsistent (negative fetched count).',
    };
  }

  if (typeof scope.total === 'number' && scope.total >= 0 && scope.fetched > scope.total) {
    return {
      code: 'fetched_exceeds_total',
      message: 'Task scope metadata is inconsistent (fetched exceeds total).',
    };
  }

  if (
    scope.hasNext &&
    typeof scope.total === 'number' &&
    scope.total >= 0 &&
    scope.fetched >= scope.total &&
    scope.capHit !== true
  ) {
    return {
      code: 'has_next_conflict',
      message: 'Task scope metadata is inconsistent (hasNext conflicts with totals).',
    };
  }

  if (
    scope.isPartial &&
    !scope.hasNext &&
    scope.capHit !== true &&
    typeof scope.total === 'number' &&
    scope.total >= 0 &&
    scope.fetched >= scope.total
  ) {
    return {
      code: 'partial_flag_conflict',
      message: 'Task scope metadata is inconsistent (partial flag conflicts with totals).',
    };
  }

  return null;
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
