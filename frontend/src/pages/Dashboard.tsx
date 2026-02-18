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
  getSprintWipStatus,
  type BudgetHoursResponse,
  type SprintWipStatus,
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
import {
  buildActiveBlockers,
  buildBurndownData,
  buildDashboardStats,
  buildEnhancedVelocityData,
  buildKpiMetrics,
  buildOverdueTasks,
  buildRiskItems,
  buildStaleInProgressTasks,
  buildTargetVelocity,
  buildTaskDistribution,
  buildUpcomingTasks,
  buildVelocityData,
  buildVelocitySeries,
  buildVelocityTrend,
  formatDueDate,
} from './dashboard/dashboardDerivations';

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
    loading: tasksLoading,
    error: tasksError,
  } = useSelector((state: RootState) => state.task);
  const { activeSprint } = useSelector((state: RootState) => state.sprint);

  const [budgetData, setBudgetData] = useState<BudgetHoursResponse | null>(null);
  const [valueMetrics, setValueMetrics] = useState<ValueMetricsResponse | null>(null);
  const [wipStatus, setWipStatus] = useState<SprintWipStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [now, setNow] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const [drilldown, setDrilldown] = useState<{ open: boolean; title: string; tasks: Task[] }>({
    open: false,
    title: '',
    tasks: [],
  });

  const [dateRange, setDateRange] = useState<string>(() => localStorage.getItem('dashboard_date_range') || '30d');
  const [chartView, setChartView] = useState<string>(() => localStorage.getItem('dashboard_chart_view') || 'both');

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
    setDateRange(range);
    localStorage.setItem('dashboard_date_range', range);
  }, []);

  const handleChartViewChange = useCallback((view: string) => {
    setChartView(view);
    localStorage.setItem('dashboard_chart_view', view);
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
      dispatch(setCurrentProject(projects[0]));
    }
  }, [currentProject, projects, dispatch]);

  useEffect(() => {
    if (!currentProject) return;
    dispatch(loadProjectData({ projectId: currentProject.id }));
  }, [currentProject, dispatch]);

  const refreshProjectMetrics = useCallback(async () => {
    if (!currentProject) {
      setBudgetData(null);
      setValueMetrics(null);
      setWipStatus(null);
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

    if (!activeSprint?.id) {
      setWipStatus(null);
      return;
    }

    try {
      const wip = await getSprintWipStatus(activeSprint.id);
      setWipStatus(wip);
    } catch (error) {
      console.warn('Failed to load WIP status', error);
      setWipStatus(null);
    }
  }, [currentProject, activeSprint?.id]);

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
  const velocityData = useMemo(() => buildVelocityData(projectTasks, now), [projectTasks, now]);
  const burndownData = useMemo(() => buildBurndownData(projectTasks), [projectTasks]);
  const taskDistribution = useMemo(() => buildTaskDistribution(projectTasks), [projectTasks]);
  const overdueTasks = useMemo(() => buildOverdueTasks(projectTasks, now), [projectTasks, now]);
  const activeBlockers = useMemo(() => buildActiveBlockers(projectTasks), [projectTasks]);
  const staleInProgressTasks = useMemo(
    () => buildStaleInProgressTasks(projectTasks, now),
    [projectTasks, now]
  );
  const velocitySeries = useMemo(() => buildVelocitySeries(velocityData), [velocityData]);
  const velocityTrend = useMemo(() => buildVelocityTrend(velocitySeries), [velocitySeries]);
  const enhancedVelocityData = useMemo(
    () => buildEnhancedVelocityData(velocityData, velocitySeries),
    [velocityData, velocitySeries]
  );
  const targetVelocity = useMemo(() => buildTargetVelocity(velocitySeries), [velocitySeries]);
  const riskItems = useMemo(
    () =>
      buildRiskItems(overdueTasks, activeBlockers, staleInProgressTasks, velocityTrend, openDrilldown),
    [overdueTasks, activeBlockers, staleInProgressTasks, velocityTrend, openDrilldown]
  );
  const upcomingTasks = useMemo(() => buildUpcomingTasks(projectTasks, now), [projectTasks, now]);
  const kpiMetrics = useMemo(
    () =>
      buildKpiMetrics(stats, velocitySeries, velocityTrend, overdueTasks, activeBlockers, openDrilldown),
    [stats, velocitySeries, velocityTrend, overdueTasks, activeBlockers, openDrilldown]
  );

  const isLoading = projectsLoading || tasksLoading;
  const hasProject = Boolean(currentProject);
  const hasTasks = projectTasks.length > 0;
  const dashboardError = loadError || projectsError || tasksError;
  const shouldShowVelocity = chartView === 'velocity' || chartView === 'both';
  const shouldShowBurndown = chartView === 'burndown' || chartView === 'both';

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
            isLoading={isLoading}
            hasTasks={hasTasks}
            showVelocity={shouldShowVelocity}
            showBurndown={shouldShowBurndown}
            velocityData={enhancedVelocityData}
            targetVelocity={targetVelocity}
            burndownData={burndownData}
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
              hasActiveSprint={Boolean(activeSprint?.id)}
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
