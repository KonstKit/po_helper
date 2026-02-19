import type { ChartData } from 'chart.js';
import type { KPIMetric } from '../../components/KPIBar';
import type { VelocityDataPoint } from '../../components/VelocityChart';
import type { BurndownResponse, VelocityResponse } from '../../services/api';
import { categorizeStatus, isDoneStatus } from '../../hooks/useTaskStatuses';
import type { Task } from '../../store/taskSlice';
import type { DateRangeOption } from './dashboardContract';
import { getDateRangeDays } from './dashboardContract';

const DAY_IN_MS = 24 * 60 * 60 * 1000;
const STALE_TASK_DAYS = 5;
const UPCOMING_DAYS = 14;
const WEEKS_TO_RENDER = 5;

export type VelocityTrend = 'up' | 'down' | 'flat';

export interface BurndownChartModel {
  data: ChartData<'line', number[], string>;
  hasData: boolean;
}

export interface DashboardStats {
  totalTasks: number;
  completedTasks: number;
  inProgress: number;
  blockers: number;
  velocity: number;
}

export interface RiskItem {
  level: 'High' | 'Medium' | 'Low';
  message: string;
  color: 'error.main' | 'warning.main' | 'success.main';
  onClick?: () => void;
}

export interface UpcomingTaskItem {
  row: Task;
  sortKey: number;
  daysRemaining: number | null;
}

type DrilldownOpener = (title: string, filter: (row: Task) => boolean) => void;

const EMPTY_LINE_CHART_DATA: ChartData<'line', number[], string> = {
  labels: [],
  datasets: [],
};

const toFiniteNumber = (value: unknown): number | null => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const getBurndownSortedDays = (burndown: BurndownResponse): number[] => {
  const days = new Set<number>();
  (burndown.ideal_burndown ?? []).forEach((point) => {
    const day = toFiniteNumber(point.day);
    if (day !== null) {
      days.add(day);
    }
  });
  (burndown.actual_burndown ?? []).forEach((point) => {
    const day = toFiniteNumber(point.day);
    if (day !== null) {
      days.add(day);
    }
  });

  return Array.from(days).sort((left, right) => left - right);
};

const buildBurndownSeries = (
  days: number[],
  points: Array<{ day: number; ideal_remaining?: number; remaining?: number }>,
  mode: 'ideal' | 'actual'
): number[] => {
  const byDay = new Map<number, number>();

  points.forEach((point) => {
    const rawValue = mode === 'ideal' ? point.ideal_remaining : point.remaining;
    const value = toFiniteNumber(rawValue);
    const day = toFiniteNumber(point.day);
    if (value === null || day === null) {
      return;
    }
    byDay.set(day, Math.max(0, value));
  });

  let carryForward: number | null = null;
  return days.map((day) => {
    const direct = byDay.get(day);
    if (direct !== undefined) {
      carryForward = direct;
      return Math.round(direct);
    }
    if (carryForward !== null) {
      return Math.round(carryForward);
    }
    return 0;
  });
};

const VELOCITY_TREND_MAP: Record<string, VelocityTrend> = {
  increasing: 'up',
  decreasing: 'down',
  stable: 'flat',
  insufficient_data: 'flat',
};

const toVelocityTrend = (value: unknown): VelocityTrend | null => {
  if (typeof value !== 'string') {
    return null;
  }
  return VELOCITY_TREND_MAP[value.toLowerCase()] ?? null;
};

const getWeekLabel = (date: Date): string => {
  const startOfYear = new Date(date.getFullYear(), 0, 1);
  const days = Math.floor((date.getTime() - startOfYear.getTime()) / DAY_IN_MS);
  const week = Math.ceil((days + startOfYear.getDay() + 1) / 7);
  return `${date.getFullYear()}-W${week}`;
};

const toEstimateHours = (task: Task): number => {
  if (typeof task.estimate_hours === 'number') return task.estimate_hours;
  const parsed = Number(task.estimate_hours);
  return Number.isFinite(parsed) ? parsed : 0;
};

const sameTaskIdentity = (source: Task, candidate: Task): boolean => {
  if (source.id && candidate.id) return source.id === candidate.id;
  if (source.key && candidate.key) return source.key === candidate.key;
  return false;
};

const getTaskActivityTime = (task: Task): number | null => {
  const resolved = task.resolved_date ? new Date(task.resolved_date).getTime() : NaN;
  if (Number.isFinite(resolved)) return resolved;
  const updated = task.updated_date ? new Date(task.updated_date).getTime() : NaN;
  return Number.isFinite(updated) ? updated : null;
};

export const filterTasksByDateRange = (
  tasks: Task[],
  dateRange: DateRangeOption,
  now: number
): Task[] => {
  const days = getDateRangeDays(dateRange);
  if (days === null) return tasks;

  const windowStart = now - days * DAY_IN_MS;
  return tasks.filter((task) => {
    const activityTime = getTaskActivityTime(task);
    return activityTime !== null && activityTime >= windowStart && activityTime <= now;
  });
};

export const buildDashboardStats = (tasks: Task[], now: number): DashboardStats => {
  const twoWeeksAgo = new Date(now - 14 * DAY_IN_MS);
  let totalTasks = 0;
  let completedTasks = 0;
  let inProgress = 0;
  let velocityHours = 0;
  const blockerIds = new Set<number>();

  tasks.forEach((task: Task, index) => {
    totalTasks += 1;
    const bucket = categorizeStatus(task.status);
    if (bucket === 'done') completedTasks += 1;
    if (bucket === 'in_progress') inProgress += 1;
    if (bucket === 'blocked' || task?.is_blocker) {
      blockerIds.add(task.id ?? index);
    }

    if (!isDoneStatus(task.status) || !task.updated_date) return;
    const updated = new Date(task.updated_date);
    if (Number.isNaN(updated.getTime()) || updated < twoWeeksAgo) return;
    velocityHours += toEstimateHours(task);
  });

  return {
    totalTasks,
    completedTasks,
    inProgress,
    blockers: blockerIds.size,
    velocity: Math.round(velocityHours),
  };
};

export const buildVelocityData = (tasks: Task[], now: number): ChartData<'line', number[], string> => {
  const weeks: string[] = [];
  const buckets: Record<string, number> = {};

  for (let i = WEEKS_TO_RENDER - 1; i >= 0; i -= 1) {
    const weekDate = new Date(now - i * 7 * DAY_IN_MS);
    const label = getWeekLabel(weekDate);
    weeks.push(label);
    buckets[label] = 0;
  }

  tasks.forEach((task) => {
    if (!isDoneStatus(task.status) || !task.updated_date) return;
    const updated = new Date(task.updated_date);
    if (Number.isNaN(updated.getTime())) return;
    const label = getWeekLabel(updated);
    if (!(label in buckets)) return;
    buckets[label] += toEstimateHours(task);
  });

  return {
    labels: weeks,
    datasets: [
      {
        label: 'Velocity (h)',
        data: weeks.map((week) => Math.round(buckets[week] || 0)),
        borderColor: 'rgb(75,192,192)',
        backgroundColor: 'rgba(75,192,192,0.2)',
      },
    ],
  };
};

export const buildVelocityDataFromApi = (
  velocityResponse: VelocityResponse | null
): ChartData<'line', number[], string> => {
  const sprintVelocities = Array.isArray(velocityResponse?.sprint_velocities)
    ? [...velocityResponse.sprint_velocities].sort((left, right) => {
        const leftDate = left.end_date ? new Date(left.end_date).getTime() : Number.NaN;
        const rightDate = right.end_date ? new Date(right.end_date).getTime() : Number.NaN;
        const bothDatesPresent = Number.isFinite(leftDate) && Number.isFinite(rightDate);
        if (bothDatesPresent && leftDate !== rightDate) {
          return leftDate - rightDate;
        }

        const leftSprintId = toFiniteNumber(left.sprint_id);
        const rightSprintId = toFiniteNumber(right.sprint_id);
        const bothIdsPresent = leftSprintId !== null && rightSprintId !== null;
        if (bothIdsPresent && leftSprintId !== rightSprintId) {
          return leftSprintId - rightSprintId;
        }

        return 0;
      })
    : [];
  const labels = sprintVelocities.map((item, index) => {
    const sprintName = typeof item.sprint_name === 'string' && item.sprint_name.trim() ? item.sprint_name : '';
    if (sprintName) return sprintName;
    if (typeof item.sprint_id === 'number' && Number.isFinite(item.sprint_id)) {
      return `Sprint #${item.sprint_id}`;
    }
    return `Sprint ${index + 1}`;
  });
  const values = sprintVelocities.map((item) => Number(item.velocity) || 0);

  return {
    labels,
    datasets: [
      {
        label: 'Velocity (h)',
        data: values,
        borderColor: 'rgb(75,192,192)',
        backgroundColor: 'rgba(75,192,192,0.2)',
      },
    ],
  };
};

export const buildBurndownData = (burndown: BurndownResponse | null): BurndownChartModel => {
  if (!burndown) {
    return { data: EMPTY_LINE_CHART_DATA, hasData: false };
  }

  const idealPoints = Array.isArray(burndown.ideal_burndown) ? burndown.ideal_burndown : [];
  const actualPoints = Array.isArray(burndown.actual_burndown) ? burndown.actual_burndown : [];

  if (idealPoints.length === 0 && actualPoints.length === 0) {
    return { data: EMPTY_LINE_CHART_DATA, hasData: false };
  }

  const days = getBurndownSortedDays(burndown);
  if (days.length === 0) {
    return { data: EMPTY_LINE_CHART_DATA, hasData: false };
  }

  const labels = days.map((day) => `Day ${day}`);
  const datasets: ChartData<'line', number[], string>['datasets'] = [];

  if (idealPoints.length > 0) {
    datasets.push({
      label: 'Ideal',
      data: buildBurndownSeries(days, idealPoints, 'ideal'),
      borderColor: 'rgb(255,99,132)',
      borderDash: [5, 5],
      backgroundColor: 'rgba(255,99,132,0.1)',
    });
  }

  if (actualPoints.length > 0) {
    datasets.push({
      label: 'Actual',
      data: buildBurndownSeries(days, actualPoints, 'actual'),
      borderColor: 'rgb(54,162,235)',
      backgroundColor: 'rgba(54,162,235,0.1)',
    });
  }

  return {
    data: { labels, datasets },
    hasData: datasets.length > 0,
  };
};

export const buildTaskDistribution = (tasks: Task[]): ChartData<'doughnut', number[], string> => {
  const labels = ['Todo', 'In Progress', 'Blocked', 'Done', 'Other'];
  const counts: Record<string, number> = {
    Todo: 0,
    'In Progress': 0,
    Blocked: 0,
    Done: 0,
    Other: 0,
  };

  tasks.forEach((task) => {
    const bucket = categorizeStatus(task.status);
    if (bucket === 'todo') counts.Todo += 1;
    else if (bucket === 'in_progress') counts['In Progress'] += 1;
    else if (bucket === 'blocked') counts.Blocked += 1;
    else if (bucket === 'done') counts.Done += 1;
    else counts.Other += 1;
  });

  return {
    labels,
    datasets: [
      {
        data: labels.map((label) => counts[label] || 0),
        backgroundColor: [
          'rgba(255,99,132,0.8)',
          'rgba(54,162,235,0.8)',
          'rgba(255,159,64,0.8)',
          'rgba(75,192,192,0.8)',
          'rgba(201,203,207,0.8)',
        ],
      },
    ],
  };
};

export const buildOverdueTasks = (tasks: Task[], now: number): Task[] =>
  tasks.filter((task) => {
    if (isDoneStatus(task.status) || !task.due_date) return false;
    const due = new Date(task.due_date).getTime();
    return Number.isFinite(due) && due < now;
  });

export const buildActiveBlockers = (tasks: Task[]): Task[] =>
  tasks.filter((task) => task?.is_blocker || categorizeStatus(task.status) === 'blocked');

export const buildStaleInProgressTasks = (tasks: Task[], now: number): Task[] => {
  const threshold = now - STALE_TASK_DAYS * DAY_IN_MS;
  return tasks.filter((task) => {
    if (categorizeStatus(task.status) !== 'in_progress') return false;
    if (!task.updated_date) return true;
    const updated = new Date(task.updated_date).getTime();
    return !Number.isFinite(updated) || updated < threshold;
  });
};

export const buildVelocitySeries = (velocityData: ChartData<'line', number[], string>): number[] => {
  const dataset = velocityData.datasets?.[0]?.data ?? [];
  return dataset.map((value) => Number(value) || 0);
};

const inferVelocityTrendFromSeries = (velocitySeries: number[]): VelocityTrend => {
  if (velocitySeries.length < 3) return 'flat';
  const last = velocitySeries[velocitySeries.length - 1];
  const average =
    velocitySeries.slice(0, -1).reduce((acc, value) => acc + value, 0) / (velocitySeries.length - 1) || 0;

  if (average === 0) return last > 0 ? 'up' : 'flat';
  if (last < average * 0.7) return 'down';
  if (last > average * 1.3) return 'up';
  return 'flat';
};

export const buildVelocityTrend = (
  velocityResponse: VelocityResponse | null,
  velocitySeries: number[]
): VelocityTrend => {
  const trendFromApi = toVelocityTrend(velocityResponse?.velocity_trend);
  if (trendFromApi !== null) {
    return trendFromApi;
  }
  return inferVelocityTrendFromSeries(velocitySeries);
};

export const buildEnhancedVelocityData = (
  velocityData: ChartData<'line', number[], string>,
  velocitySeries: number[]
): VelocityDataPoint[] => {
  const labels = velocityData.labels || [];
  return labels.map((label, index) => {
    const value = velocitySeries[index] || 0;
    const average =
      velocitySeries.length > 0
        ? velocitySeries.reduce((acc, seriesValue) => acc + seriesValue, 0) / velocitySeries.length
        : 0;
    return {
      label: String(label),
      value,
      annotation: velocitySeries.length > 1 && value > 0 && value < average * 0.5 ? 'Low velocity' : undefined,
    };
  });
};

export const buildTargetVelocity = (velocitySeries: number[]): number | undefined => {
  if (velocitySeries.length === 0) return undefined;
  const average = velocitySeries.reduce((acc, value) => acc + value, 0) / velocitySeries.length;
  return Math.round(average);
};

export const buildRiskItems = (
  overdueTasks: Task[],
  activeBlockers: Task[],
  staleInProgressTasks: Task[],
  velocityTrend: VelocityTrend,
  openDrilldown: DrilldownOpener
): RiskItem[] => {
  const items: RiskItem[] = [];

  if (overdueTasks.length > 0) {
    const count = overdueTasks.length;
    items.push({
      level: 'High',
      message: `${count} overdue ${count === 1 ? 'task needs' : 'tasks need'} attention`,
      color: 'error.main',
      onClick: () =>
        openDrilldown('Overdue tasks', (task: Task) =>
          overdueTasks.some((overdueTask) => sameTaskIdentity(overdueTask, task))
        ),
    });
  }

  if (activeBlockers.length > 0) {
    const count = activeBlockers.length;
    items.push({
      level: overdueTasks.length > 0 ? 'Medium' : 'High',
      message: `${count} blocker${count === 1 ? '' : 's'} impacting flow`,
      color: 'warning.main',
      onClick: () =>
        openDrilldown(
          'Blocking tasks',
          (task: Task) => task?.is_blocker || categorizeStatus(task.status) === 'blocked'
        ),
    });
  }

  if (staleInProgressTasks.length > 0) {
    const count = staleInProgressTasks.length;
    items.push({
      level: 'Medium',
      message: `${count} task${count === 1 ? '' : 's'} stuck >5 days`,
      color: 'warning.main',
      onClick: () =>
        openDrilldown('Stalled tasks', (task: Task) =>
          staleInProgressTasks.some((staleTask) => sameTaskIdentity(staleTask, task))
        ),
    });
  }

  if (velocityTrend === 'down') {
    items.push({
      level: 'Medium',
      message: 'Velocity dropped versus recent average',
      color: 'warning.main',
    });
  } else if (
    overdueTasks.length === 0 &&
    activeBlockers.length === 0 &&
    staleInProgressTasks.length === 0 &&
    velocityTrend === 'up'
  ) {
    items.push({
      level: 'Low',
      message: 'Velocity trending upward',
      color: 'success.main',
    });
  }

  if (items.length === 0) {
    items.push({
      level: 'Low',
      message: 'No major risks detected',
      color: 'success.main',
    });
  }

  return items.slice(0, 4);
};

export const buildUpcomingTasks = (
  tasks: Task[],
  now: number,
  horizonDays = UPCOMING_DAYS
): UpcomingTaskItem[] => {
  const horizon = now + Math.max(1, horizonDays) * DAY_IN_MS;
  return tasks
    .filter((task: Task) => {
      if (isDoneStatus(task.status)) return false;
      const due = task.due_date ? new Date(task.due_date).getTime() : NaN;
      if (Number.isFinite(due)) {
        return due <= horizon;
      }
      return categorizeStatus(task.status) === 'todo';
    })
    .map((task: Task) => {
      const due = task.due_date ? new Date(task.due_date).getTime() : NaN;
      const created = task.created_date ? new Date(task.created_date).getTime() : NaN;
      const sortKey = Number.isFinite(due)
        ? due
        : Number.isFinite(created)
          ? created
          : Number.MAX_SAFE_INTEGER;
      const daysRemaining = Number.isFinite(due) ? Math.ceil((due - now) / DAY_IN_MS) : null;
      return { row: task, sortKey, daysRemaining };
    })
    .sort((left, right) => left.sortKey - right.sortKey)
    .slice(0, 6);
};

export const formatDueDate = (value?: string | null): string => {
  if (!value) return '--';
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) return '--';
  return parsed.toLocaleDateString();
};

export const buildKpiMetrics = (
  stats: DashboardStats,
  velocitySeries: number[],
  velocityTrend: VelocityTrend,
  overdueTasks: Task[],
  activeBlockers: Task[],
  openDrilldown: DrilldownOpener,
  options?: { isPartialScope?: boolean; velocityValue?: number }
): KPIMetric[] => {
  const completionRate = stats.totalTasks > 0 ? Math.round((stats.completedTasks / stats.totalTasks) * 100) : 0;
  const velocityChange =
    velocitySeries.length >= 2
      ? ((velocitySeries[velocitySeries.length - 1] - velocitySeries[velocitySeries.length - 2]) /
          Math.max(1, velocitySeries[velocitySeries.length - 2])) *
        100
      : 0;
  const isPartialScope = options?.isPartialScope === true;
  const velocityValue = typeof options?.velocityValue === 'number' ? options.velocityValue : stats.velocity;

  return [
    {
      label: 'Velocity',
      value: velocityValue,
      unit: 'hrs',
      change: velocityChange,
      trend: velocityTrend,
      status: velocityTrend === 'up' ? 'success' : velocityTrend === 'down' ? 'warning' : 'neutral',
      tooltip: 'Total hours completed in last 2 weeks',
    },
    {
      label: 'On Time',
      value: isPartialScope ? '--' : completionRate,
      unit: isPartialScope ? undefined : '%',
      status: isPartialScope
        ? 'neutral'
        : completionRate >= 80
          ? 'success'
          : completionRate >= 60
            ? 'warning'
            : 'error',
      tooltip: isPartialScope
        ? 'Task completion rate hidden because only partial task scope is loaded.'
        : 'Task completion rate',
    },
    {
      label: 'At Risk',
      value: overdueTasks.length + activeBlockers.length,
      status:
        overdueTasks.length + activeBlockers.length === 0
          ? 'success'
          : overdueTasks.length + activeBlockers.length < 5
            ? 'warning'
            : 'error',
      tooltip: isPartialScope
        ? 'Overdue and blocked tasks (partial scope).'
        : 'Overdue and blocked tasks',
      onClick: () =>
        openDrilldown('At Risk tasks', (task: Task) =>
          overdueTasks.some((overdueTask) => sameTaskIdentity(overdueTask, task)) ||
          activeBlockers.some((blockerTask) => sameTaskIdentity(blockerTask, task))
        ),
    },
    {
      label: 'In Progress',
      value: stats.inProgress,
      status: 'neutral',
      tooltip: 'Tasks currently in progress',
    },
  ];
};
