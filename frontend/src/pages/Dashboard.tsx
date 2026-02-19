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
import { setCurrentProject } from '../store/projectSlice';
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
import KPIBar from '../components/KPIBar';
import { DashboardFilters } from '../components/DashboardFilters';
import DashboardHeader from './dashboard/DashboardHeader';
import DashboardChartsSection from './dashboard/DashboardChartsSection';
import DashboardInsightsSection from './dashboard/DashboardInsightsSection';
import DashboardStatsSection from './dashboard/DashboardStatsSection';
import { getCanonicalSprintId } from '../utils/sprintNormalization';
import {
  DASHBOARD_STORAGE_KEYS,
  DASHBOARD_TEST_IDS,
  VELOCITY_SPRINTS_COUNT_MAP,
  formatTaskScopeLabel,
  getUpcomingHorizonDays,
  parseChartViewOption,
  parseDateRangeOption,
  parseNumberListFromStorage,
  parseQuickFilterOption,
  type ChartViewOption,
  type DateRangeOption,
} from './dashboard/dashboardContract';
import {
  buildActiveBlockers,
  buildBurndownData,
  buildDashboardStats,
  buildVelocityDataFromApi,
  buildEnhancedVelocityData,
  buildKpiMetrics,
  buildOverdueTasks,
  buildRiskItems,
  buildStaleInProgressTasks,
  buildTargetVelocity,
  buildTaskDistribution,
  buildUpcomingTasks,
  buildVelocitySeries,
  buildVelocityTrend,
  filterTasksByDateRange,
  formatDueDate,
} from './dashboard/dashboardDerivations';

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

interface DashboardProjectCandidate {
  id: number;
  name: string;
  status?: string | null;
  state?: string | null;
}

const parseStoredProjectId = (value: string | null): number | null => {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
};

const isActiveProjectCandidate = (project: DashboardProjectCandidate): boolean => {
  const status = typeof project.status === 'string' ? project.status.toLowerCase() : '';
  const state = typeof project.state === 'string' ? project.state.toLowerCase() : '';
  return status === 'active' || state === 'active';
};

const resolveInitialProjectId = (projects: DashboardProjectCandidate[]): number | null => {
  if (projects.length === 0) return null;

  const sortedById = [...projects].sort((left, right) => left.id - right.id);
  const sortedByName = [...projects].sort((left, right) => left.name.localeCompare(right.name));
  const projectIds = new Set(sortedById.map((project) => project.id));
  const quickFilter = parseQuickFilterOption(localStorage.getItem(DASHBOARD_STORAGE_KEYS.quickFilter));
  const recentProjectIds = parseNumberListFromStorage(
    localStorage.getItem(DASHBOARD_STORAGE_KEYS.recentProjectIds)
  );
  const recentMatch = recentProjectIds.find((projectId) => projectIds.has(projectId)) ?? null;
  const lastProjectId = parseStoredProjectId(localStorage.getItem(DASHBOARD_STORAGE_KEYS.lastProjectId));
  const lastMatch = lastProjectId !== null && projectIds.has(lastProjectId) ? lastProjectId : null;

  if (quickFilter === 'active') {
    const activeProjects = sortedByName.filter(isActiveProjectCandidate);
    if (activeProjects.length > 0) {
      return activeProjects[0].id;
    }
    if (lastMatch !== null) {
      return lastMatch;
    }
    return sortedById[0]?.id ?? null;
  }

  if (quickFilter === 'all') {
    if (lastMatch !== null) {
      return lastMatch;
    }
    if (recentMatch !== null) {
      return recentMatch;
    }
    return sortedById[0]?.id ?? null;
  }

  if (recentMatch !== null) {
    return recentMatch;
  }
  if (lastMatch !== null) {
    return lastMatch;
  }
  return sortedById[0]?.id ?? null;
};

const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const dispatch = useDispatch<AppDispatch>();

  const {
    projects,
    currentProject,
    loading: projectsLoading,
    error: projectsError,
  } = useSelector((state: RootState) => state.project);
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
  const [now, setNow] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const [drilldown, setDrilldown] = useState<{ open: boolean; title: string; tasks: Task[] }>({
    open: false,
    title: '',
    tasks: [],
  });

  const [dateRange, setDateRange] = useState<DateRangeOption>(() =>
    parseDateRangeOption(localStorage.getItem(DASHBOARD_STORAGE_KEYS.dateRange))
  );
  const [chartView, setChartView] = useState<ChartViewOption>(() =>
    parseChartViewOption(localStorage.getItem(DASHBOARD_STORAGE_KEYS.chartView))
  );

  const projectTasks = useMemo(
    () => (currentProject ? tasksByProject[currentProject.id] || [] : []),
    [currentProject, tasksByProject]
  );

  useEffect(() => {
    const updateNow = () => setNow(Date.now());
    const timeoutId = setTimeout(updateNow, 0);
    const intervalId = setInterval(updateNow, 60_000);
    return () => {
      clearTimeout(timeoutId);
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
    const nextRange = parseDateRangeOption(range);
    setDateRange(nextRange);
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.dateRange, nextRange);
  }, []);

  const handleChartViewChange = useCallback((view: string) => {
    const nextView = parseChartViewOption(view);
    setChartView(nextView);
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.chartView, nextView);
  }, []);

  const currentTaskScope = useMemo(
    () => (currentProject ? taskScopeByProject[currentProject.id] : undefined),
    [currentProject, taskScopeByProject]
  );
  const activeSprintId = useMemo(() => getCanonicalSprintId(activeSprint), [activeSprint]);

  const isPartialTaskScope = currentTaskScope?.isPartial === true;

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

  const handleProjectChange = useCallback(
    (projectId: number) => {
      const nextProject = projects.find((project) => project.id === projectId);
      if (nextProject) {
        dispatch(setCurrentProject(nextProject));
      }
    },
    [projects, dispatch]
  );

  useEffect(() => {
    if (!currentProject && projects.length > 0) {
      const initialProjectId = resolveInitialProjectId(projects);
      const initialProject =
        initialProjectId !== null
          ? projects.find((project) => project.id === initialProjectId) ?? projects[0]
          : projects[0];
      if (initialProject) {
        dispatch(setCurrentProject(initialProject));
      }
    }
  }, [currentProject, projects, dispatch]);

  useEffect(() => {
    if (!currentProject) return;
    dispatch(loadProjectData({ projectId: currentProject.id }));
  }, [currentProject, dispatch]);

  const refreshProjectMetrics = useCallback(async () => {
    if (!currentProject) {
      resetLocalMetrics();
      return;
    }

    try {
      const [budget, metrics] = await Promise.all([
        getProjectBudgetHours(currentProject.id),
        getProjectValueMetrics(currentProject.id),
      ]);
      setBudgetData(budget);
      setValueMetrics(metrics);
      setLoadError(null);
    } catch (error) {
      console.warn('Failed to refresh project metrics', error);
      setLoadError('Failed to refresh project metrics.');
    }

    try {
      setVelocityLoading(true);
      const velocity = await getVelocity(currentProject.id, {
        sprintsCount: VELOCITY_SPRINTS_COUNT_MAP[dateRange],
      });
      setVelocityData(velocity);
    } catch (error) {
      console.warn('Failed to load velocity metrics', error);
      setVelocityData(null);
    } finally {
      setVelocityLoading(false);
    }

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
      getSprintWipStatus(activeSprintId),
      getSprintBurndown(activeSprintId),
    ]);

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
      console.warn('Failed to load WIP status', wipResult.reason);
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
      console.warn('Failed to load burndown timeline', burndownResult.reason);
      setBurndownTimeline(null);
      setBurndownWidgetState('error');
    }
  }, [activeSprintId, currentProject, dateRange, resetLocalMetrics]);

  useEffect(() => {
    const timeoutId = setTimeout(() => {
      void refreshProjectMetrics();
    }, 0);
    return () => clearTimeout(timeoutId);
  }, [refreshProjectMetrics]);

  useEffect(() => {
    if (!currentProject) {
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch (error) {
          console.warn('Failed to close dashboard websocket', error);
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
        if (message?.type === 'jira_sync_complete' && Number(message?.project_id) === currentProject.id) {
          await dispatch(loadProjectData({ projectId: currentProject.id, force: true }));
          await refreshProjectMetrics();
          setLoadError(null);
        } else if (message?.type === 'jira_sync_failed' && Number(message?.project_id) === currentProject.id) {
          const detail = typeof message?.detail === 'string' ? message.detail : '';
          setLoadError(detail ? `Background sync failed: ${detail}` : 'Background sync failed.');
        }
      } catch (error) {
        console.warn('Failed to process dashboard websocket message', error);
      }
    };

    socket.onerror = (error) => {
      console.warn('Dashboard websocket error', error);
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
          console.warn('Failed to close dashboard websocket on cleanup', error);
        }
        wsRef.current = null;
      }
    };
  }, [currentProject, dispatch, refreshProjectMetrics]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await getIntegrationsStatus();
        if (!cancelled) {
          // no-op: connectivity check
        }
      } catch (error) {
        console.warn('Integrations status check failed', error);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleRetry = useCallback(() => {
    if (!currentProject) return;
    dispatch(loadProjectData({ projectId: currentProject.id, force: true }));
    void refreshProjectMetrics();
  }, [currentProject, dispatch, refreshProjectMetrics]);

  const stats = useMemo(() => buildDashboardStats(projectTasks, now), [projectTasks, now]);
  const dateScopedTasks = useMemo(
    () => filterTasksByDateRange(projectTasks, dateRange, now),
    [projectTasks, dateRange, now]
  );
  const scopedStats = useMemo(() => buildDashboardStats(dateScopedTasks, now), [dateScopedTasks, now]);
  const velocityChartData = useMemo(
    () => buildVelocityDataFromApi(velocityData),
    [velocityData]
  );
  const burndownModel = useMemo(() => buildBurndownData(burndownTimeline), [burndownTimeline]);
  const taskDistribution = useMemo(() => buildTaskDistribution(projectTasks), [projectTasks]);
  const overdueTasks = useMemo(() => buildOverdueTasks(dateScopedTasks, now), [dateScopedTasks, now]);
  const activeBlockers = useMemo(() => buildActiveBlockers(dateScopedTasks), [dateScopedTasks]);
  const staleInProgressTasks = useMemo(
    () => buildStaleInProgressTasks(dateScopedTasks, now),
    [dateScopedTasks, now]
  );
  const velocitySeries = useMemo(() => buildVelocitySeries(velocityChartData), [velocityChartData]);
  const velocityTrend = useMemo(
    () => buildVelocityTrend(velocityData, velocitySeries),
    [velocityData, velocitySeries]
  );
  const enhancedVelocityData = useMemo(
    () => buildEnhancedVelocityData(velocityChartData, velocitySeries),
    [velocityChartData, velocitySeries]
  );
  const targetVelocity = useMemo(() => {
    if (typeof velocityData?.average_velocity === 'number') {
      return Math.round(velocityData.average_velocity);
    }
    return buildTargetVelocity(velocitySeries);
  }, [velocityData, velocitySeries]);
  const riskItems = useMemo(
    () =>
      buildRiskItems(overdueTasks, activeBlockers, staleInProgressTasks, velocityTrend, openDrilldown),
    [overdueTasks, activeBlockers, staleInProgressTasks, velocityTrend, openDrilldown]
  );
  const upcomingTasks = useMemo(
    () => buildUpcomingTasks(dateScopedTasks, now, getUpcomingHorizonDays(dateRange)),
    [dateScopedTasks, now, dateRange]
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

  if (isLoading && !hasProject) {
    return <DashboardSkeleton />;
  }

  return (
    <Box data-testid="dashboard-page">
      <DashboardHeader
        hasProject={hasProject}
        onOpenProjectDetails={
          currentProject ? () => navigate(`/projects/${currentProject.id}`) : undefined
        }
      />

      {projects.length > 0 && (
        <Box data-testid="dashboard-filters">
          <DashboardFilters
            projectId={currentProject?.id || null}
            onProjectChange={handleProjectChange}
            projects={projects}
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
              projects.length === 0 ? navigate('/projects') : dispatch(setCurrentProject(projects[0])),
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
          {isPartialTaskScope && currentTaskScope && (
            <Alert data-testid={DASHBOARD_TEST_IDS.partialScopeBadge} severity="info" sx={{ mb: 3 }}>
              {formatTaskScopeLabel(currentTaskScope)}
            </Alert>
          )}

          <KPIBar metrics={kpiMetrics} />

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
                  data-testid="dashboard-drilldown-item"
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
