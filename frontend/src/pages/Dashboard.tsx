import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';
import { AssignmentTurnedIn } from '@mui/icons-material';
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  List,
  ListItem,
  ListItemText,
  Typography,
} from '@mui/material';
import type { ChartOptions } from 'chart.js';
import { type AppDispatch, type RootState } from '../store/store';
import { loadProjectData } from '../store/dataThunks';
import type { Task } from '../store/taskSlice';
import { categorizeStatus, isDoneStatus } from '../hooks/useTaskStatuses';
import {
  getIntegrationsStatus,
  getProjectBudgetHours,
  getProjectValueMetrics,
  getSprintBurndown,
  getSprintWipStatus,
  getVelocity,
  type BurndownResponse,
  type BudgetHoursResponse,
  type SprintWipStatus,
  type VelocityResponse,
  type ValueMetricsResponse,
} from '../services/api';
import DashboardSkeleton from '../components/DashboardSkeleton';
import EmptyState from '../components/EmptyState';
import { DashboardFilters } from '../components/DashboardFilters';
import { useSelectedProject } from '../hooks/useSelectedProject';
import DashboardKpiBanner from './dashboard/DashboardKpiBanner';
import DashboardHeader from './dashboard/DashboardHeader';
import DashboardChartsSection from './dashboard/DashboardChartsSection';
import DashboardInsightsSection from './dashboard/DashboardInsightsSection';
import DashboardStatsSection from './dashboard/DashboardStatsSection';
import { getCanonicalSprintId } from '../utils/sprintNormalization';
import {
  isAboveBudget,
  recordDuration,
  shouldReportBudgetBreach,
} from '../utils/dashboardPerfGuards';
import {
  DASHBOARD_GUARDRAIL_TARGETS,
} from './dashboard/dashboardGuardrails';
import {
  detectTaskScopeAnomaly,
  DASHBOARD_STORAGE_KEYS,
  DASHBOARD_TEST_IDS,
  VELOCITY_SPRINTS_COUNT_MAP,
  formatTaskScopeLabel,
  migrateDashboardStorageContract,
  parseChartViewOption,
  parseDateRangeOption,
  type ChartViewOption,
  type DateRangeOption,
} from './dashboard/dashboardContract';
import {
  buildKpiMetrics,
  buildRiskItems,
  formatDueDate,
} from './dashboard/dashboardDerivations';
import { makeSelectDashboardDerivedState } from './dashboard/dashboardSelectors';
import {
  emitDashboardFilterBudgetExceeded,
  emitDashboardInitBudgetExceeded,
  emitDashboardRefreshLoop,
  emitDashboardRuntimeWarning,
} from './dashboard/dashboardSignalEmitter';

type WipWidgetState = 'no_sprint' | 'loading' | 'ready' | 'not_available' | 'error';
type BurndownWidgetState = 'no_sprint' | 'loading' | 'ready' | 'not_available' | 'error';

const isValidWipPayload = (value: SprintWipStatus | null): value is SprintWipStatus =>
  value !== null &&
  typeof value.total_active === 'number' &&
  Array.isArray(value.assignees);

const lineChartOptions: ChartOptions<'line'> = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      position: 'top',
    },
  },
};

const doughnutChartOptions: ChartOptions<'doughnut'> = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      position: 'bottom',
    },
  },
};

const nowMs = (): number => {
  if (typeof performance !== 'undefined' && typeof performance.now === 'function') {
    return performance.now();
  }
  return Date.now();
};

const toErrorMessage = (error: unknown): string => {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
};

const isAbortLikeError = (error: unknown): boolean => {
  if (!error || typeof error !== 'object') return false;
  const details = error as { name?: string; code?: string; message?: string };
  return (
    details.name === 'AbortError' ||
    details.name === 'CanceledError' ||
    details.code === 'ERR_CANCELED' ||
    details.message === 'canceled'
  );
};

const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const dispatch = useDispatch<AppDispatch>();

  // Global selected project is the single source of truth (UX review C4): the
  // dashboard no longer owns a local project picker — it reads/writes the
  // globally-selected project through this hook, which the header selector and
  // other screens share.
  const { projects, currentProject, projectId, selectProject, loading: projectsLoading } =
    useSelectedProject();
  const projectsError = useSelector((state: RootState) => state.project.error);
  const {
    tasksByProject,
    taskScopeByProject,
    loading: tasksLoading,
    error: tasksError,
  } = useSelector((state: RootState) => state.task);
  const { activeSprint } = useSelector((state: RootState) => state.sprint);

  const [budgetData, setBudgetData] = useState<BudgetHoursResponse | null>(null);
  const [valueMetrics, setValueMetrics] = useState<ValueMetricsResponse | null>(null);
  const [velocityData, setVelocityData] = useState<VelocityResponse | null>(null);
  const [burndownTimeline, setBurndownTimeline] = useState<BurndownResponse | null>(null);
  const [velocityLoading, setVelocityLoading] = useState(false);
  const [wipStatus, setWipStatus] = useState<SprintWipStatus | null>(null);
  const [wipWidgetState, setWipWidgetState] = useState<WipWidgetState>('no_sprint');
  const [burndownWidgetState, setBurndownWidgetState] = useState<BurndownWidgetState>('no_sprint');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const wsRef = useRef<WebSocket | null>(null);
  const initStartedAtRef = useRef<number>(nowMs());
  const initMetricsRecordedRef = useRef(false);
  const pendingFilterApplyStartRef = useRef<number | null>(null);
  const refreshEventsRef = useRef<number[]>([]);
  const refreshLoopWarnedRef = useRef(false);
  const refreshAbortRef = useRef<AbortController | null>(null);
  const refreshRequestIdRef = useRef(0);
  const refreshProjectMetricsRef = useRef<(() => Promise<void>) | null>(null);
  const selectDashboardDerivedState = useMemo(makeSelectDashboardDerivedState, []);
  const [drilldown, setDrilldown] = useState<{ open: boolean; title: string; tasks: Task[] }>({
    open: false,
    title: '',
    tasks: [],
  });

  const [dateRange, setDateRange] = useState<DateRangeOption>(() =>
    migrateDashboardStorageContract().dateRange
  );
  const [chartView, setChartView] = useState<ChartViewOption>(() =>
    migrateDashboardStorageContract().chartView
  );

  const projectTasks = useMemo(
    () => (currentProject ? tasksByProject[currentProject.id] || [] : []),
    [currentProject, tasksByProject]
  );
  const currentProjectId = projectId;

  useEffect(() => {
    const updateNow = () => setNow(Date.now());
    updateNow();
    const intervalId = setInterval(updateNow, 60_000);
    return () => {
      clearInterval(intervalId);
    };
  }, []);

  const openDrilldown = useCallback(
    (title: string, filter: (task: Task) => boolean) => {
      const filtered = projectTasks.filter(filter).slice(0, 100);
      setDrilldown({ open: true, title, tasks: filtered });
    },
    [projectTasks]
  );

  const closeDrilldown = useCallback(() => {
    setDrilldown({ open: false, title: '', tasks: [] });
  }, []);

  const handleDateRangeChange = useCallback((range: string) => {
    pendingFilterApplyStartRef.current = nowMs();
    const nextRange = parseDateRangeOption(range);
    setDateRange(nextRange);
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.dateRange, nextRange);
  }, []);

  const handleChartViewChange = useCallback((view: string) => {
    pendingFilterApplyStartRef.current = nowMs();
    const nextView = parseChartViewOption(view);
    setChartView(nextView);
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.chartView, nextView);
  }, []);

  useEffect(() => {
    const startedAt = pendingFilterApplyStartRef.current;
    if (startedAt === null) {
      return;
    }
    pendingFilterApplyStartRef.current = null;

    const timeoutId = setTimeout(() => {
      const duration = Math.max(0, nowMs() - startedAt);
      const filterApplyTarget = DASHBOARD_GUARDRAIL_TARGETS.filterApplyBudget;
      recordDuration('filter_apply_ms', duration, filterApplyTarget.sampleWindow);
      if (
        isAboveBudget('filter_apply_ms', filterApplyTarget.p95BudgetMs) &&
        shouldReportBudgetBreach('filter_apply_ms', filterApplyTarget.p95BudgetMs)
      ) {
        emitDashboardFilterBudgetExceeded({
          duration,
          budget: filterApplyTarget.p95BudgetMs,
          sampleWindow: filterApplyTarget.sampleWindow,
        });
      }
    }, 0);

    return () => clearTimeout(timeoutId);
  }, [dateRange, chartView]);

  const currentTaskScope = useMemo(
    () => (currentProject ? taskScopeByProject[currentProject.id] : undefined),
    [currentProject, taskScopeByProject]
  );
  const taskScopeAnomaly = useMemo(
    () => detectTaskScopeAnomaly(currentTaskScope),
    [currentTaskScope]
  );
  const activeSprintId = useMemo(() => getCanonicalSprintId(activeSprint), [activeSprint]);

  const isPartialTaskScope = currentTaskScope?.isPartial === true;

  useEffect(() => {
    refreshAbortRef.current?.abort();
    refreshAbortRef.current = null;
    refreshRequestIdRef.current += 1;
    refreshEventsRef.current = [];
    refreshLoopWarnedRef.current = false;
    initStartedAtRef.current = nowMs();
    initMetricsRecordedRef.current = false;
  }, [currentProjectId]);

  const resetLocalMetrics = useCallback(() => {
    setBudgetData(null);
    setValueMetrics(null);
    setVelocityData(null);
    setBurndownTimeline(null);
    setWipStatus(null);
    setWipWidgetState('no_sprint');
    setBurndownWidgetState('no_sprint');
    setVelocityLoading(false);
  }, []);

  useEffect(() => {
    if (!currentProject) return;
    dispatch(loadProjectData({ projectId: currentProject.id }));
  }, [currentProject, dispatch]);

  const refreshProjectMetrics = useCallback(async () => {
    if (!currentProject) {
      refreshAbortRef.current?.abort();
      refreshAbortRef.current = null;
      resetLocalMetrics();
      return;
    }

    refreshAbortRef.current?.abort();
    const controller = new AbortController();
    refreshAbortRef.current = controller;
    const signal = controller.signal;
    const requestId = refreshRequestIdRef.current + 1;
    refreshRequestIdRef.current = requestId;
    const isActiveRequest = () =>
      refreshRequestIdRef.current === requestId && !signal.aborted;

    const refreshEventTime = nowMs();
    const refreshLoopTarget = DASHBOARD_GUARDRAIL_TARGETS.refreshLoop;
    refreshEventsRef.current = refreshEventsRef.current.filter(
      (timestamp) => refreshEventTime - timestamp <= refreshLoopTarget.windowMs
    );
    refreshEventsRef.current.push(refreshEventTime);
    if (!refreshLoopWarnedRef.current && refreshEventsRef.current.length >= refreshLoopTarget.threshold) {
      refreshLoopWarnedRef.current = true;
      emitDashboardRefreshLoop({
        eventsInWindow: refreshEventsRef.current.length,
        threshold: refreshLoopTarget.threshold,
        windowMs: refreshLoopTarget.windowMs,
      });
    }

    try {
      const [budget, metrics] = await Promise.all([
        getProjectBudgetHours(currentProject.id, { signal }),
        getProjectValueMetrics(currentProject.id, { signal }),
      ]);
      if (!isActiveRequest()) return;
      setBudgetData(budget);
      setValueMetrics(metrics);
      setLoadError(null);
    } catch (error) {
      if (isAbortLikeError(error) || !isActiveRequest()) {
        return;
      }
      emitDashboardRuntimeWarning('refreshMetricsFailed', {
        projectId: currentProject.id,
        error: toErrorMessage(error),
      });
      setLoadError('Failed to refresh project metrics.');
    }

    try {
      if (!isActiveRequest()) return;
      setVelocityLoading(true);
      const velocity = await getVelocity(currentProject.id, {
        sprintsCount: VELOCITY_SPRINTS_COUNT_MAP[dateRange],
        signal,
      });
      if (!isActiveRequest()) return;
      setVelocityData(velocity);
    } catch (error) {
      if (isAbortLikeError(error) || !isActiveRequest()) {
        return;
      }
      emitDashboardRuntimeWarning('velocityLoadFailed', {
        projectId: currentProject.id,
        dateRange,
        error: toErrorMessage(error),
      });
      setVelocityData(null);
    } finally {
      if (isActiveRequest()) {
        setVelocityLoading(false);
      }
    }

    if (!isActiveRequest()) return;
    if (activeSprintId === null) {
      setBurndownTimeline(null);
      setBurndownWidgetState('no_sprint');
      setWipStatus(null);
      setWipWidgetState('no_sprint');
      return;
    }

    setWipWidgetState('loading');
    setBurndownWidgetState('loading');

    const [wipResult, burndownResult] = await Promise.allSettled([
      getSprintWipStatus(activeSprintId, { signal }),
      getSprintBurndown(activeSprintId, { signal }),
    ]);

    if (!isActiveRequest()) return;
    if (wipResult.status === 'fulfilled') {
      const wip = wipResult.value;
      if (!isValidWipPayload(wip) || typeof wip.error === 'string') {
        setWipStatus(null);
        setWipWidgetState('not_available');
      } else {
        setWipStatus(wip);
        setWipWidgetState('ready');
      }
    } else {
      if (!isAbortLikeError(wipResult.reason)) {
        emitDashboardRuntimeWarning('wipLoadFailed', {
          sprintId: activeSprintId,
          error: toErrorMessage(wipResult.reason),
        });
      }
      setWipStatus(null);
      setWipWidgetState('error');
    }

    if (burndownResult.status === 'fulfilled') {
      const payload = burndownResult.value;
      const hasIdeal = Array.isArray(payload.ideal_burndown) && payload.ideal_burndown.length > 0;
      const hasActual = Array.isArray(payload.actual_burndown) && payload.actual_burndown.length > 0;

      if (!hasIdeal && !hasActual) {
        setBurndownTimeline(null);
        setBurndownWidgetState('not_available');
      } else {
        setBurndownTimeline(payload);
        setBurndownWidgetState('ready');
      }
    } else {
      if (!isAbortLikeError(burndownResult.reason)) {
        emitDashboardRuntimeWarning('burndownLoadFailed', {
          sprintId: activeSprintId,
          error: toErrorMessage(burndownResult.reason),
        });
      }
      setBurndownTimeline(null);
      setBurndownWidgetState('error');
    }
  }, [activeSprintId, currentProject, dateRange, resetLocalMetrics]);

  useEffect(() => {
    refreshProjectMetricsRef.current = refreshProjectMetrics;
  }, [refreshProjectMetrics]);

  useEffect(() => {
    void refreshProjectMetrics();
  }, [refreshProjectMetrics]);

  useEffect(() => {
    if (currentProjectId === null) {
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch (error) {
          emitDashboardRuntimeWarning('websocketCloseFailed', {
            error: toErrorMessage(error),
          });
        }
        wsRef.current = null;
      }
      return;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const socket = new WebSocket(`${protocol}://${window.location.host}/api/v1/ws`);
    wsRef.current = socket;

    socket.onmessage = async (event) => {
      try {
        const message = JSON.parse(event.data || '{}');
        if (message?.type === 'jira_sync_complete' && Number(message?.project_id) === currentProjectId) {
          await dispatch(loadProjectData({ projectId: currentProjectId, force: true }));
          await refreshProjectMetricsRef.current?.();
          setLoadError(null);
        } else if (message?.type === 'jira_sync_failed' && Number(message?.project_id) === currentProjectId) {
          const detail = typeof message?.detail === 'string' ? message.detail : '';
          setLoadError(detail ? `Background sync failed: ${detail}` : 'Background sync failed.');
        }
      } catch (error) {
        emitDashboardRuntimeWarning('websocketMessageFailed', {
          error: toErrorMessage(error),
        });
      }
    };

    socket.onerror = (error) => {
      emitDashboardRuntimeWarning('websocketError', {
        error: toErrorMessage(error),
      });
    };

    socket.onclose = () => {
      if (wsRef.current === socket) {
        wsRef.current = null;
      }
    };

    return () => {
      if (wsRef.current === socket) {
        try {
          socket.close();
        } catch (error) {
          emitDashboardRuntimeWarning('websocketCleanupCloseFailed', {
            error: toErrorMessage(error),
          });
        }
        wsRef.current = null;
      }
    };
  }, [currentProjectId, dispatch]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await getIntegrationsStatus();
        if (!cancelled) {
          // no-op: connectivity check
        }
      } catch (error) {
        emitDashboardRuntimeWarning('integrationsStatusFailed', {
          error: toErrorMessage(error),
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    return () => {
      refreshAbortRef.current?.abort();
      refreshAbortRef.current = null;
    };
  }, []);

  const handleRetry = useCallback(() => {
    if (!currentProject) return;
    dispatch(loadProjectData({ projectId: currentProject.id, force: true }));
    void refreshProjectMetrics();
  }, [currentProject, dispatch, refreshProjectMetrics]);

  const derivedState = selectDashboardDerivedState({
    projectTasks,
    dateRange,
    now,
    velocityData,
    burndownTimeline,
  });
  const {
    stats,
    scopedStats,
    burndownModel,
    taskDistribution,
    overdueTasks,
    activeBlockers,
    staleInProgressTasks,
    velocitySeries,
    velocityTrend,
    enhancedVelocityData,
    targetVelocity,
    upcomingTasks,
  } = derivedState;
  const riskItems = useMemo(
    () =>
      buildRiskItems(overdueTasks, activeBlockers, staleInProgressTasks, velocityTrend, openDrilldown),
    [overdueTasks, activeBlockers, staleInProgressTasks, velocityTrend, openDrilldown]
  );
  const kpiMetrics = useMemo(
    () =>
      buildKpiMetrics(scopedStats, velocitySeries, velocityTrend, overdueTasks, activeBlockers, openDrilldown, {
        isPartialScope: isPartialTaskScope,
        velocityValue: typeof velocityData?.average_velocity === 'number' ? velocityData.average_velocity : undefined,
      }),
    [
      scopedStats,
      velocitySeries,
      velocityTrend,
      overdueTasks,
      activeBlockers,
      openDrilldown,
      isPartialTaskScope,
      velocityData,
    ]
  );

  const isLoading = projectsLoading || tasksLoading;
  const hasProject = Boolean(currentProject);
  const hasTasks = projectTasks.length > 0;
  const dashboardError = loadError || projectsError || tasksError;
  const shouldShowVelocity = chartView === 'velocity' || chartView === 'both';
  const shouldShowBurndown = chartView === 'burndown' || chartView === 'both';
  const shouldShowDistribution = chartView === 'distribution';
  const velocityTrendLabel = useMemo(() => {
    if (typeof velocityData?.velocity_trend !== 'string') {
      return undefined;
    }
    const normalized = velocityData.velocity_trend.toLowerCase();
    if (!['increasing', 'decreasing', 'stable', 'insufficient_data'].includes(normalized)) {
      return undefined;
    }
    return normalized.replace('_', ' ');
  }, [velocityData]);
  const shouldShowVelocityTrendLine =
    velocitySeries.length >= 3 && velocityTrendLabel !== 'insufficient data';
  const isBurndownAvailable = burndownWidgetState === 'ready' && burndownModel.hasData;
  const burndownUnavailableMessage = useMemo(() => {
    if (burndownWidgetState === 'loading') return '';
    if (burndownWidgetState === 'no_sprint') return 'Not available for this sprint (no active sprint).';
    if (burndownWidgetState === 'not_available') return 'Not available for this sprint.';
    if (burndownWidgetState === 'error') return 'Unable to load burndown timeline.';
    if (!burndownModel.hasData) return 'Not available for this sprint.';
    return '';
  }, [burndownWidgetState, burndownModel.hasData]);
  const burndownModeLabel = isBurndownAvailable ? 'Timeline data' : undefined;

  useEffect(() => {
    if (!hasProject || isLoading || initMetricsRecordedRef.current) {
      return;
    }

    const duration = Math.max(0, nowMs() - initStartedAtRef.current);
    const initBudgetTarget = DASHBOARD_GUARDRAIL_TARGETS.initBudget;
    recordDuration('dashboard_init_ms', duration, initBudgetTarget.sampleWindow);
    if (
      isAboveBudget('dashboard_init_ms', initBudgetTarget.p95BudgetMs) &&
      shouldReportBudgetBreach('dashboard_init_ms', initBudgetTarget.p95BudgetMs)
    ) {
      emitDashboardInitBudgetExceeded({
        duration,
        budget: initBudgetTarget.p95BudgetMs,
        sampleWindow: initBudgetTarget.sampleWindow,
      });
    }
    initMetricsRecordedRef.current = true;
  }, [hasProject, isLoading]);

  if (isLoading && !hasProject) {
    return <DashboardSkeleton />;
  }

  return (
    <Box data-testid={DASHBOARD_TEST_IDS.page}>
      <DashboardHeader
        hasProject={hasProject}
        onOpenProjectDetails={
          currentProject ? () => navigate(`/projects/${currentProject.id}`) : undefined
        }
      />

      {projects.length > 0 && (
        <Box data-testid={DASHBOARD_TEST_IDS.filtersRoot}>
          <DashboardFilters
            dateRange={dateRange}
            onDateRangeChange={handleDateRangeChange}
            chartView={chartView}
            onChartViewChange={handleChartViewChange}
          />
        </Box>
      )}

      {!hasProject ? (
        <EmptyState
          icon={<AssignmentTurnedIn fontSize="inherit" />}
          title={projects.length === 0 ? 'No projects available' : 'Select a project'}
          description={
            projects.length === 0
              ? 'Create or connect a project to start tracking dashboard metrics.'
              : 'Choose a project to load dashboard metrics and insights.'
          }
          primaryAction={{
            label: projects.length === 0 ? 'Open Projects' : 'Select First Project',
            onClick: () =>
              projects.length === 0 ? navigate('/projects') : selectProject(projects[0]?.id ?? null),
          }}
          secondaryAction={
            projects.length === 0
              ? undefined
              : {
                  label: 'Go to Projects',
                  variant: 'outlined',
                  onClick: () => navigate('/projects'),
                }
          }
        />
      ) : (
        <>
          {taskScopeAnomaly && (
            <Alert data-testid={DASHBOARD_TEST_IDS.taskScopeAnomalyBadge} severity="warning" sx={{ mb: 3 }}>
              {taskScopeAnomaly.message}
            </Alert>
          )}

          {isPartialTaskScope && currentTaskScope && (
            <Alert data-testid={DASHBOARD_TEST_IDS.partialScopeBadge} severity="info" sx={{ mb: 3 }}>
              {formatTaskScopeLabel(currentTaskScope)}
            </Alert>
          )}

          <DashboardKpiBanner metrics={kpiMetrics} />

          {dashboardError && (
            <Alert
              severity="warning"
              sx={{ mb: 3 }}
              action={
                <Button color="inherit" size="small" onClick={handleRetry} disabled={isLoading}>
                  Retry
                </Button>
              }
            >
              {dashboardError}
            </Alert>
          )}

          <DashboardChartsSection
            isLoading={isLoading || velocityLoading}
            hasTasks={hasTasks}
            showVelocity={shouldShowVelocity}
            showBurndown={shouldShowBurndown}
            showDistribution={shouldShowDistribution}
            velocityData={enhancedVelocityData}
            targetVelocity={targetVelocity}
            velocityShowTrend={shouldShowVelocityTrendLine}
            velocityTrendLabel={velocityTrendLabel}
            burndownData={burndownModel.data}
            burndownLoading={burndownWidgetState === 'loading'}
            burndownAvailable={isBurndownAvailable}
            burndownUnavailableMessage={burndownUnavailableMessage}
            burndownModeLabel={burndownModeLabel}
            taskDistributionData={taskDistribution}
            lineChartOptions={lineChartOptions}
            doughnutChartOptions={doughnutChartOptions}
          />

          <Box mt={3}>
            <DashboardInsightsSection
              isLoading={isLoading}
              riskItems={riskItems}
              upcomingTasks={upcomingTasks}
            />
          </Box>

          <Box mt={3}>
            <DashboardStatsSection
              stats={stats}
              totalTasksValue={currentProject?.total_tasks ?? stats.totalTasks}
              budgetData={budgetData}
              valueMetrics={valueMetrics}
              wipStatus={wipStatus}
              hasActiveSprint={activeSprintId !== null}
              wipState={wipWidgetState}
              onOpenAllTasks={() => openDrilldown('All tasks', () => true)}
              onOpenCompletedTasks={() =>
                openDrilldown('Completed tasks', (task: Task) => isDoneStatus(task.status))
              }
              onOpenInProgressTasks={() =>
                openDrilldown(
                  'In progress tasks',
                  (task: Task) => categorizeStatus(task.status) === 'in_progress'
                )
              }
              onOpenBlockingTasks={() =>
                openDrilldown(
                  'Blocking tasks',
                  (task: Task) => task?.is_blocker || categorizeStatus(task.status) === 'blocked'
                )
              }
              onOpenActiveWipTasks={() =>
                openDrilldown(
                  'Active WIP',
                  (task: Task) => categorizeStatus(task.status) === 'in_progress'
                )
              }
            />
          </Box>
        </>
      )}

      <Dialog open={drilldown.open} onClose={closeDrilldown} maxWidth="md" fullWidth>
        <DialogTitle>{drilldown.title || 'Details'}</DialogTitle>
        <DialogContent dividers>
          {drilldown.tasks.length > 0 ? (
            <List dense>
              {drilldown.tasks.map((task, index) => (
                <ListItem
                  data-testid={DASHBOARD_TEST_IDS.drilldownItem}
                  key={task.id || index}
                  alignItems="flex-start"
                  divider
                >
                  <ListItemText
                    primary={`${task.key || task.id}${task.summary ? ' -- ' + task.summary : ''}`}
                    secondary={`Status: ${task.status || '--'} | Assignee: ${
                      task.assignee_name || 'Unassigned'
                    } | Due: ${formatDueDate(task.due_date)}`}
                  />
                </ListItem>
              ))}
            </List>
          ) : (
            <Typography variant="body2" color="text.secondary">
              No items to display.
            </Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={closeDrilldown}>Close</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default Dashboard;
