import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';
import { AppDispatch, RootState } from '../store/store';
import { setCurrentProject } from '../store/projectSlice';
import { loadProjectData } from '../store/dataThunks';
import {
  Alert,
  Box,
  Button,
  Card,
  CardActionArea,
  CardContent,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  Grid,
  InputLabel,
  LinearProgress,
  List,
  ListItem,
  ListItemText,
  MenuItem,
  Paper,
  Select,
  Typography,
} from '@mui/material';
import {
  TrendingUp,
  Assignment,
  CheckCircle,
  Warning,
  Speed,
} from '@mui/icons-material';
import { Line, Bar, Doughnut } from 'react-chartjs-2';
import { getIntegrationsStatus, getProjectBudgetHours, getProjectValueMetrics, getProjectSprints, getSprintWipStatus } from '../services/api';
import KPIBar, { KPIMetric } from '../components/KPIBar';
import DashboardSkeleton from '../components/DashboardSkeleton';
import { DashboardFilters } from '../components/DashboardFilters';
import VelocityChart, { VelocityDataPoint } from '../components/VelocityChart';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  Title,
  Tooltip,
  Legend
);

type StatusBucket = 'todo' | 'in_progress' | 'blocked' | 'done' | 'other';

const normalizeStatus = (status?: string | null) => (status ?? '').trim().toLowerCase();

const DAY_IN_MS = 24 * 60 * 60 * 1000;

const categorizeStatus = (status?: string | null): StatusBucket => {
  const normalized = normalizeStatus(status);
  if (!normalized) return 'other';
  if (normalized.includes('block')) return 'blocked';

  const doneMatches = [
    'done',
    'closed',
    'resolved',
    'work done',
    'workdone',
    'requirements done',
    'completed',
    'complete',
  ];
  if (doneMatches.includes(normalized) || normalized.endsWith(' done') || normalized.startsWith('done ')) {
    return 'done';
  }

  const todoMatches = [
    'backlog',
    'to do',
    'todo',
    'design ready',
    'ready for refinement',
  ];
  if (todoMatches.includes(normalized)) {
    return 'todo';
  }

  const inProgressExact = [
    'in progress',
    'in review',
    'code review',
    'review',
    'testing',
    'ready for qa',
    'ready for test',
    'qa',
    'po review',
    'requirements review',
    'in ba',
    'in design',
  ];
  if (inProgressExact.includes(normalized)) {
    return 'in_progress';
  }
  if (normalized.includes('progress') || normalized.includes('review') || normalized.includes('qa') || normalized.includes('testing')) {
    return 'in_progress';
  }

  return 'other';
};

const isDoneStatus = (status?: string | null) => categorizeStatus(status) === 'done';

type StatCardProps = {
  title: string;
  value: React.ReactNode;
  icon: React.ReactNode;
  color: string;
  progress?: number;
  helperText?: string;
  onClick?: () => void;
  testId?: string;
};

const Dashboard = () => {
  const navigate = useNavigate();
  const dispatch = useDispatch<AppDispatch>();

  // Redux state
  const { projects, currentProject, loading: projectsLoading } = useSelector((state: RootState) => state.project);
  const { tasks, tasksByProject, loading: tasksLoading } = useSelector((state: RootState) => state.task);
  const { sprints, sprintsByProject, activeSprint } = useSelector((state: RootState) => state.sprint);

  // Local state for additional data
  const [integrations, setIntegrations] = useState<any>(null);
  const [budgetData, setBudgetData] = useState<any | null>(null);
  const [valueMetrics, setValueMetrics] = useState<any | null>(null);
  const [wipStatus, setWipStatus] = useState<any | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [drilldown, setDrilldown] = useState<{ open: boolean; title: string; tasks: any[] }>({ open: false, title: '', tasks: [] });

  // Filter preferences (saved to localStorage)
  const [dateRange, setDateRange] = useState<string>(() => {
    return localStorage.getItem('dashboard_date_range') || '30d';
  });
  const [chartView, setChartView] = useState<string>(() => {
    return localStorage.getItem('dashboard_chart_view') || 'both';
  });

  // Save preferences to localStorage
  const handleDateRangeChange = (range: string) => {
    setDateRange(range);
    localStorage.setItem('dashboard_date_range', range);
  };

  const handleChartViewChange = (view: string) => {
    setChartView(view);
    localStorage.setItem('dashboard_chart_view', view);
  };


  const projectTasks = currentProject ? (tasksByProject[currentProject.id] || []) : [];
  const projectSprints = currentProject ? (sprintsByProject[currentProject.id] || []) : [];

  const stats = useMemo(() => {
    const twoWeeksAgo = new Date(Date.now() - 14 * 24 * 3600 * 1000);
    let totalTasks = 0;
    let completedTasks = 0;
    let inProgress = 0;
    let velocityHours = 0;
    const blockerIds = new Set<number>();

    projectTasks.forEach((row: any, index) => {
      totalTasks += 1;
      const bucket = categorizeStatus(row.status);
      if (bucket === 'done') completedTasks += 1;
      if (bucket === 'in_progress') inProgress += 1;
      if (bucket === 'blocked') blockerIds.add(row?.id ?? index);
      if (row?.is_blocker) blockerIds.add(row?.id ?? index);

      if (isDoneStatus(row.status) && row?.updated_date) {
        const updated = new Date(row.updated_date);
        if (!Number.isNaN(updated.getTime()) && updated >= twoWeeksAgo) {
          velocityHours += row?.estimate_hours || 0;
        }
      }
    });

    return {
      totalTasks,
      completedTasks,
      inProgress,
      blockers: blockerIds.size,
      velocity: Math.round(velocityHours),
    };
  }, [projectTasks]);

  const openDrilldown = useCallback((title: string, filter: (row: any) => boolean) => {
    const filtered = projectTasks.filter(filter).slice(0, 100);
    setDrilldown({ open: true, title, tasks: filtered });
  }, [projectTasks]);

  const closeDrilldown = useCallback(() => {
    setDrilldown({ open: false, title: '', tasks: [] });
  }, []);

  // Initialize with first project if none selected
  useEffect(() => {
    if (!currentProject && projects.length > 0) {
      console.log('[Dashboard] Auto-selecting first project:', projects[0].id);
      dispatch(setCurrentProject(projects[0]));
    }
  }, [currentProject, projects, dispatch]);

  // Load project-specific data when current project changes
  useEffect(() => {
    if (!currentProject) return;
    console.log('[Dashboard] Loading data for project:', currentProject.id);
    dispatch(loadProjectData({ projectId: currentProject.id }));
  }, [currentProject, dispatch]);

  const refreshProjectMetrics = useCallback(async () => {
    if (!currentProject) return;
    try {
      const [budget, metrics] = await Promise.all([
        getProjectBudgetHours(currentProject.id),
        getProjectValueMetrics(currentProject.id),
      ]);
      setBudgetData(budget);
      setValueMetrics(metrics);
      setLoadError(null);
    } catch (err) {
      console.warn('Failed to refresh project metrics', err);
      setLoadError('Failed to refresh project metrics.');
    }

    if (activeSprint?.id) {
      try {
        const wip = await getSprintWipStatus(activeSprint.id);
        setWipStatus(wip);
      } catch (err) {
        console.warn('Failed to load WIP status', err);
      }
    } else {
      setWipStatus(null);
    }
  }, [currentProject, activeSprint?.id]);

  useEffect(() => {
    refreshProjectMetrics();
  }, [refreshProjectMetrics]);

  useEffect(() => {
    if (!currentProject) {
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch (err) {
          console.warn('Failed to close dashboard websocket', err);
        }
        wsRef.current = null;
      }
      return;
    }

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const base = window.location.host;
    const ws = new WebSocket(`${proto}://${base}/api/v1/ws`);
    wsRef.current = ws;

    ws.onmessage = async (event) => {
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
      } catch (err) {
        console.warn('Failed to process dashboard websocket message', err);
      }
    };

    ws.onerror = (err) => {
      console.warn('Dashboard websocket error', err);
    };

    ws.onclose = () => {
      if (wsRef.current === ws) {
        wsRef.current = null;
      }
    };

    return () => {
      if (wsRef.current === ws) {
        try {
          ws.close();
        } catch (err) {
          console.warn('Failed to close dashboard websocket on cleanup', err);
        }
        wsRef.current = null;
      }
    };
  }, [currentProject, dispatch, refreshProjectMetrics]);

  // Load integrations status once
  // Load integrations status once
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const st = await getIntegrationsStatus();
        if (!cancelled) {
          setIntegrations(st);
        }
      } catch {}
    })();
    return () => {
      cancelled = true;
    };
  }, []);


  useEffect(() => {
    refreshProjectMetrics();
  }, [refreshProjectMetrics]);


  const handleProjectChange = (projectId: number) => {
    const project = projects.find(p => p.id === projectId);
    if (project) {
      dispatch(setCurrentProject(project));
    }
  };


  const handleRetry = useCallback(() => {
    if (currentProject) {
      dispatch(loadProjectData({ projectId: currentProject.id, force: true }));
      refreshProjectMetrics();
    }
  }, [currentProject, dispatch, refreshProjectMetrics]);

  // Weekly velocity (last 5 weeks) based on completed tasks' estimates
  const velocityData = useMemo(() => {
    const weeks: string[] = [];
    const buckets: Record<string, number> = {};
    for (let i = 4; i >= 0; i--) {
      const d = new Date();
      d.setDate(d.getDate() - i * 7);
      const label = `${d.getFullYear()}-W${Math.ceil(((+new Date(d) - +new Date(d.getFullYear(), 0, 1)) / 86400000 + new Date(d.getFullYear(), 0, 1).getDay() + 1) / 7)}`;
      weeks.push(label);
      buckets[label] = 0;
    }
    projectTasks.forEach((r) => {
      if (!isDoneStatus(r.status) || !r.updated_date) return;
      const d = new Date(r.updated_date);
      if (Number.isNaN(d.getTime())) return;
      const label = `${d.getFullYear()}-W${Math.ceil(((+new Date(d) - +new Date(d.getFullYear(), 0, 1)) / 86400000 + new Date(d.getFullYear(), 0, 1).getDay() + 1) / 7)}`;
      if (label in buckets) {
        const estimate = typeof r.estimate_hours === 'number' ? r.estimate_hours : Number(r.estimate_hours) || 0;
        buckets[label] += estimate;
      }
    });
    return {
      labels: weeks,
      datasets: [
        {
          label: 'Velocity (h)',
          data: weeks.map((w) => Math.round(buckets[w] || 0)),
          borderColor: 'rgb(75,192,192)',
          backgroundColor: 'rgba(75,192,192,0.2)',
        },
      ],
    };
  }, [projectTasks]);

  const burndownData = useMemo(() => {
    const total = projectTasks.reduce((acc, r) => acc + (typeof r.estimate_hours === 'number' ? r.estimate_hours : Number(r.estimate_hours) || 0), 0);
    const labels = Array.from({ length: 7 }, (_, i) => `Day ${i + 1}`);
    const steps = Math.max(1, labels.length - 1);
    const ideal = labels.map((_, i) => Math.round(total * (1 - i / steps)));
    const completedHours = projectTasks
      .filter((r) => isDoneStatus(r.status))
      .reduce((acc, r) => acc + (typeof r.estimate_hours === 'number' ? r.estimate_hours : Number(r.estimate_hours) || 0), 0);
    const actual = labels.map((_, i) => Math.max(0, Math.round(total - (completedHours * (i / steps)))));
    return {
      labels,
      datasets: [
        { label: 'Ideal', data: ideal, borderColor: 'rgb(255,99,132)', borderDash: [5, 5], backgroundColor: 'rgba(255,99,132,0.1)' },
        { label: 'Actual', data: actual, borderColor: 'rgb(54,162,235)', backgroundColor: 'rgba(54,162,235,0.1)' },
      ],
    };
  }, [projectTasks]);

  const taskDistribution = useMemo(() => {
    const labels = ['Todo', 'In Progress', 'Blocked', 'Done', 'Other'];
    const counts: Record<string, number> = { Todo: 0, 'In Progress': 0, Blocked: 0, Done: 0, Other: 0 };
    projectTasks.forEach((row) => {
      const bucket = categorizeStatus(row.status);
      if (bucket === 'todo') counts['Todo'] += 1;
      else if (bucket === 'in_progress') counts['In Progress'] += 1;
      else if (bucket === 'blocked') counts['Blocked'] += 1;
      else if (bucket === 'done') counts['Done'] += 1;
      else counts['Other'] += 1;
    });
    return {
      labels,
      datasets: [{
        data: labels.map((label) => counts[label] || 0),
        backgroundColor: [
          'rgba(255,99,132,0.8)',
          'rgba(54,162,235,0.8)',
          'rgba(255,159,64,0.8)',
          'rgba(75,192,192,0.8)',
          'rgba(201,203,207,0.8)',
        ],
      }],
    };
  }, [projectTasks]);

  const overdueTasks = useMemo(() => {
    const now = Date.now();
    return projectTasks.filter((row: any) => {
      if (isDoneStatus(row.status) || !row.due_date) return false;
      const due = new Date(row.due_date).getTime();
      return !Number.isNaN(due) && due < now;
    });
  }, [projectTasks]);

  const activeBlockers = useMemo(() =>
    projectTasks.filter((row: any) => row?.is_blocker || categorizeStatus(row.status) === 'blocked'),
  [projectTasks]);

  const staleInProgress = useMemo(() => {
    const threshold = Date.now() - 5 * DAY_IN_MS;
    return projectTasks.filter((row: any) => {
      if (categorizeStatus(row.status) !== 'in_progress') return false;
      if (!row.updated_date) return true;
      const updated = new Date(row.updated_date).getTime();
      if (Number.isNaN(updated)) return true;
      return updated < threshold;
    });
  }, [projectTasks]);

  const velocitySeries = useMemo<number[]>(() => {
    const dataset = (velocityData?.datasets?.[0]?.data as number[]) || [];
    return dataset.map((value) => Number(value) || 0);
  }, [velocityData]);

  const velocityTrend = useMemo(() => {
    if (velocitySeries.length < 3) return 'flat';
    const last = velocitySeries[velocitySeries.length - 1];
    const avg = velocitySeries.slice(0, -1).reduce((acc, value) => acc + value, 0) / (velocitySeries.length - 1) || 0;
    if (avg === 0) return last > 0 ? 'up' : 'flat';
    if (last < avg * 0.7) return 'down';
    if (last > avg * 1.3) return 'up';
    return 'flat';
  }, [velocitySeries]);

  // Enhanced velocity data for VelocityChart component
  const enhancedVelocityData = useMemo<VelocityDataPoint[]>(() => {
    const labels = velocityData?.labels || [];
    const values = velocitySeries;

    return labels.map((label, index) => ({
      label: String(label),
      value: values[index] || 0,
      // Add annotations for unusually low velocity (< 50% of average)
      annotation: (() => {
        if (values.length < 2) return undefined;
        const avg = values.reduce((acc, v) => acc + v, 0) / values.length;
        if (values[index] < avg * 0.5 && values[index] > 0) {
          return 'Low velocity';
        }
        return undefined;
      })(),
    }));
  }, [velocityData, velocitySeries]);

  // Calculate target velocity (average of historical velocity)
  const targetVelocity = useMemo(() => {
    if (velocitySeries.length === 0) return undefined;
    const avg = velocitySeries.reduce((acc, v) => acc + v, 0) / velocitySeries.length;
    return Math.round(avg);
  }, [velocitySeries]);

  const riskItems = useMemo(() => {
    const items: Array<{ level: string; message: string; color: string; onClick?: () => void }> = [];
    if (overdueTasks.length) {
      const count = overdueTasks.length;
      items.push({
        level: 'High',
        message: `${count} overdue ${count === 1 ? 'task needs' : 'tasks need'} attention`,
        color: 'error.main',
        onClick: () => openDrilldown('Overdue tasks', (row: any) => overdueTasks.some((item: any) => (item.id && row.id && item.id === row.id) || (item.key && row.key && item.key === row.key))),
      });
    }
    if (activeBlockers.length) {
      const count = activeBlockers.length;
      items.push({
        level: overdueTasks.length ? 'Medium' : 'High',
        message: `${count} blocker${count === 1 ? '' : 's'} impacting flow`,
        color: 'warning.main',
        onClick: () => openDrilldown('Blocking tasks', (row: any) => row?.is_blocker || categorizeStatus(row.status) === 'blocked'),
      });
    }
    if (staleInProgress.length) {
      const count = staleInProgress.length;
      items.push({
        level: 'Medium',
        message: `${count} task${count === 1 ? '' : 's'} stuck >5 days`,
        color: 'warning.main',
        onClick: () => openDrilldown('Stalled tasks', (row: any) => staleInProgress.some((item: any) => (item.id && row.id && item.id === row.id) || (item.key && row.key && item.key === row.key))),
      });
    }
    if (velocityTrend === 'down') {
      items.push({ level: 'Medium', message: 'Velocity dropped versus recent average', color: 'warning.main' });
    } else if (!overdueTasks.length && !activeBlockers.length && !staleInProgress.length && velocityTrend === 'up') {
      items.push({ level: 'Low', message: 'Velocity trending upward', color: 'success.main' });
    }
    if (!items.length) {
      items.push({ level: 'Low', message: 'No major risks detected', color: 'success.main' });
    }
    return items.slice(0, 4);
  }, [overdueTasks, activeBlockers, staleInProgress, velocityTrend, openDrilldown]);

  const upcomingTasks = useMemo(() => {
    const now = Date.now();
    const horizon = now + 14 * DAY_IN_MS;
    return projectTasks
      .filter((row: any) => {
        if (isDoneStatus(row.status)) return false;
        const due = row.due_date ? new Date(row.due_date).getTime() : NaN;
        if (!Number.isNaN(due)) {
          return due <= horizon;
        }
        return categorizeStatus(row.status) === 'todo';
      })
      .map((row: any) => {
        const due = row.due_date ? new Date(row.due_date).getTime() : NaN;
        const created = row.created_date ? new Date(row.created_date).getTime() : NaN;
        const sortKey = !Number.isNaN(due) ? due : (!Number.isNaN(created) ? created : Number.MAX_SAFE_INTEGER);
        const daysRemaining = !Number.isNaN(due) ? Math.ceil((due - now) / DAY_IN_MS) : null;
        return { row, sortKey, due, daysRemaining };
      })
      .sort((a, b) => (a.sortKey || Number.MAX_SAFE_INTEGER) - (b.sortKey || Number.MAX_SAFE_INTEGER))
      .slice(0, 6);
  }, [projectTasks]);

  const formatDueDate = useCallback((value?: string | null) => {
    if (!value) return '--';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return '--';
    return parsed.toLocaleDateString();
  }, []);

  const StatCard = ({ title, value, icon, color, progress, helperText, onClick, testId }: StatCardProps) => (
    <Card sx={{ height: '100%' }}>
      <CardActionArea data-testid={testId} sx={{ height: '100%', alignItems: 'stretch' }} onClick={onClick} disabled={!onClick}>
        <CardContent>
          <Box display="flex" justifyContent="space-between" alignItems="center">
            <Box>
              <Typography color="textSecondary" gutterBottom variant="body2">
                {title}
              </Typography>
              <Typography variant="h4" component="div">
                {value}
              </Typography>
              {progress !== undefined && (
                <Box mt={2}>
                  <LinearProgress
                    variant="determinate"
                    value={progress}
                    sx={{ height: 8, borderRadius: 4 }}
                  />
                  <Typography variant="body2" color="textSecondary" mt={0.5}>
                    {progress}% Complete
                  </Typography>
                </Box>
              )}
              {helperText && (
                <Typography variant="caption" color="textSecondary" display="block" mt={1}>
                  {helperText}
                </Typography>
              )}
            </Box>
            <Box
              sx={{
                bgcolor: color,
                borderRadius: '50%',
                p: 1.5,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {icon}
            </Box>
          </Box>
        </CardContent>
      </CardActionArea>
    </Card>
  );

  const isLoading = projectsLoading || tasksLoading;

  // KPI metrics calculation
  const kpiMetrics = useMemo<KPIMetric[]>(() => {
    const completionRate = stats.totalTasks > 0 ? Math.round((stats.completedTasks / stats.totalTasks) * 100) : 0;
    const velocityChange = velocitySeries.length >= 2
      ? ((velocitySeries[velocitySeries.length - 1] - velocitySeries[velocitySeries.length - 2]) / Math.max(1, velocitySeries[velocitySeries.length - 2])) * 100
      : 0;

    return [
      {
        label: 'Velocity',
        value: stats.velocity,
        unit: 'hrs',
        change: velocityChange,
        trend: velocityTrend,
        status: velocityTrend === 'up' ? 'success' : velocityTrend === 'down' ? 'warning' : 'neutral',
        tooltip: 'Total hours completed in last 2 weeks',
      },
      {
        label: 'On Time',
        value: completionRate,
        unit: '%',
        status: completionRate >= 80 ? 'success' : completionRate >= 60 ? 'warning' : 'error',
        tooltip: 'Task completion rate',
      },
      {
        label: 'At Risk',
        value: overdueTasks.length + activeBlockers.length,
        status: (overdueTasks.length + activeBlockers.length) === 0 ? 'success' : (overdueTasks.length + activeBlockers.length) < 5 ? 'warning' : 'error',
        tooltip: 'Overdue and blocked tasks',
        onClick: () => {
          if (overdueTasks.length) {
            openDrilldown('At Risk Tasks', (row: any) =>
              overdueTasks.some((item: any) => item.id === row.id) ||
              activeBlockers.some((item: any) => item.id === row.id)
            );
          }
        },
      },
      {
        label: 'In Progress',
        value: stats.inProgress,
        status: 'neutral',
        tooltip: 'Tasks currently in progress',
      },
    ];
  }, [stats, velocitySeries, velocityTrend, overdueTasks, activeBlockers, openDrilldown]);

  if (isLoading && !currentProject) {
    return <DashboardSkeleton />;
  }

  // Filter charts based on chartView preference
  const shouldShowVelocity = chartView === 'velocity' || chartView === 'both';
  const shouldShowBurndown = chartView === 'burndown' || chartView === 'both';
  const shouldShowDistribution = chartView === 'distribution' || chartView === 'both';

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4" fontWeight={700}>Dashboard</Typography>
        {currentProject && (
          <Button
            variant="outlined"
            size="small"
            onClick={() => navigate(`/projects/${currentProject.id}`)}
          >
            View Details
          </Button>
        )}
      </Box>

      {/* Progressive Disclosure Filters */}
      <DashboardFilters
        projectId={currentProject?.id || null}
        onProjectChange={handleProjectChange}
        projects={projects}
        dateRange={dateRange}
        onDateRangeChange={handleDateRangeChange}
        chartView={chartView}
        onChartViewChange={handleChartViewChange}
      />

      {/* KPI Bar - Top Priority */}
      {currentProject && <KPIBar metrics={kpiMetrics} />}

      {loadError && (
        <Alert
          severity="warning"
          sx={{ mb: 3 }}
          action={
            <Button color="inherit" size="small" onClick={handleRetry} disabled={isLoading}>
              Retry
            </Button>
          }
        >
          {loadError}
        </Alert>
      )}

      {/* F-Pattern Layout: Wide horizontal section first (charts) */}
      <Grid container spacing={3}>
        {/* Velocity Chart - Enhanced with target line and trend */}
        {shouldShowVelocity && (
          <Grid item xs={12} md={shouldShowBurndown ? 6 : 12}>
            <Card>
              <CardContent>
                <Typography variant="h6" gutterBottom fontWeight={600}>
                  Weekly Velocity
                  {targetVelocity && (
                    <Typography component="span" variant="body2" color="text.secondary" sx={{ ml: 1 }}>
                      (Target: {targetVelocity}h)
                    </Typography>
                  )}
                </Typography>
                {isLoading ? (
                  <Box height={250} display="flex" alignItems="center" justifyContent="center">
                    <LinearProgress sx={{ width: '80%' }} />
                  </Box>
                ) : (
                  <VelocityChart
                    data={enhancedVelocityData}
                    targetVelocity={targetVelocity}
                    showTrend={true}
                    height={250}
                  />
                )}
              </CardContent>
            </Card>
          </Grid>
        )}

        {/* Burndown Chart - Conditionally rendered */}
        {shouldShowBurndown && (
          <Grid item xs={12} md={shouldShowVelocity ? 6 : 12}>
            <Card>
              <CardContent>
                <Typography variant="h6" gutterBottom fontWeight={600}>Sprint Burndown</Typography>
                {isLoading ? (
                  <Box height={250} display="flex" alignItems="center" justifyContent="center">
                    <LinearProgress sx={{ width: '80%' }} />
                  </Box>
                ) : (
                  <Box height={250}>
                    <Line data={burndownData} options={{ responsive: true, maintainAspectRatio: false }} />
                  </Box>
                )}
              </CardContent>
            </Card>
          </Grid>
        )}

        {/* F-Pattern: Secondary row with detailed metrics (left-aligned focus) */}
        {/* Task Distribution Doughnut */}
        <Grid item xs={12} md={4}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Typography variant="h6" gutterBottom fontWeight={600}>Task Distribution</Typography>
              {isLoading ? (
                <Box height={250} display="flex" alignItems="center" justifyContent="center">
                  <LinearProgress />
                </Box>
              ) : (
                <Box height={250} display="flex" justifyContent="center" alignItems="center">
                  <Doughnut data={taskDistribution} options={{ responsive: true, maintainAspectRatio: false }} />
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* Risk Alerts - Critical info on left side */}
        <Grid item xs={12} md={4}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Typography variant="h6" gutterBottom fontWeight={600}>Risk Alerts</Typography>
              {isLoading ? (
                <Box>
                  <LinearProgress sx={{ mb: 1 }} />
                </Box>
              ) : (
                <List dense>
                  {riskItems.map((item, idx) => (
                    <ListItem
                      key={idx}
                      button={!!item.onClick}
                      onClick={item.onClick}
                      sx={{
                        borderLeft: 4,
                        borderColor: item.color,
                        mb: 1,
                        borderRadius: 1,
                        bgcolor: 'action.hover',
                      }}
                    >
                      <ListItemText
                        primary={
                          <Box display="flex" alignItems="center" gap={1}>
                            <Chip label={item.level} size="small" color={item.color === 'error.main' ? 'error' : item.color === 'warning.main' ? 'warning' : 'success'} />
                            <Typography variant="body2">{item.message}</Typography>
                          </Box>
                        }
                      />
                    </ListItem>
                  ))}
                </List>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* Upcoming Tasks - Right side*/}
        <Grid item xs={12} md={4}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Typography variant="h6" gutterBottom fontWeight={600}>Upcoming Tasks</Typography>
              {isLoading ? (
                <Box>
                  <LinearProgress sx={{ mb: 1 }} />
                </Box>
              ) : upcomingTasks.length === 0 ? (
                <Typography variant="body2" color="text.secondary">No upcoming tasks</Typography>
              ) : (
                <List dense>
                  {upcomingTasks.slice(0, 6).map(({ row, daysRemaining }, idx) => (
                    <ListItem key={idx} sx={{ py: 0.5 }}>
                      <ListItemText
                        primary={
                          <Typography variant="body2" noWrap>
                            {row.key || row.summary || 'Untitled'}
                          </Typography>
                        }
                        secondary={
                          daysRemaining !== null ? (
                            <Chip
                              label={daysRemaining > 0 ? `${daysRemaining}d left` : daysRemaining === 0 ? 'Due today' : `${Math.abs(daysRemaining)}d overdue`}
                              size="small"
                              color={daysRemaining < 0 ? 'error' : daysRemaining <= 3 ? 'warning' : 'default'}
                              sx={{ fontSize: '0.7rem', height: 18 }}
                            />
                          ) : (
                            <Typography variant="caption" color="text.secondary">No due date</Typography>
                          )
                        }
                      />
                    </ListItem>
                  ))}
                </List>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* Old Stats Cards - Moved below for secondary focus */}
        <Grid item xs={12} sm={6} md={3}>
          <StatCard
            title="Total Tasks"
            testId="card-total"
            value={currentProject?.total_tasks ?? stats.totalTasks}
            icon={<Assignment sx={{ color: 'white' }} />}
            color="primary.main"
            helperText="All items in scope"
            onClick={() => openDrilldown('All tasks', () => true)}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard
            title="Completed"
            testId="card-completed"
            value={stats.completedTasks}
            icon={<CheckCircle sx={{ color: 'white' }} />}
            color="success.main"
            progress={stats.totalTasks ? Math.round((stats.completedTasks / stats.totalTasks) * 100) : 0}
            helperText="Click for recently completed work"
            onClick={() => openDrilldown('Completed tasks', (row: any) => isDoneStatus(row.status))}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard
            title="In Progress"
            testId="card-in-progress"
            value={stats.inProgress}
            icon={<TrendingUp sx={{ color: 'white' }} />}
            color="info.main"
            helperText="Show tasks currently being worked on"
            onClick={() => openDrilldown('In progress tasks', (row: any) => categorizeStatus(row.status) === 'in_progress')}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard
            title="Blockers"
            testId="card-blockers"
            value={stats.blockers}
            icon={<Warning sx={{ color: 'white' }} />}
            color="error.main"
            helperText="Identify items blocking delivery"
            onClick={() => openDrilldown('Blocking tasks', (row: any) => row?.is_blocker || categorizeStatus(row.status) === 'blocked')}
          />
        </Grid>

        {/* Budget / ROI / WIP */}
        <Grid item xs={12} sm={6} md={4}>
          <StatCard
            title="Budget Health"
            testId="card-budget"
            value={budgetData ? `${budgetData.remaining_hours}h` : '--'}
            icon={<Speed sx={{ color: 'white' }} />}
            color={budgetData?.overrun ? 'error.main' : 'success.main'}
            progress={budgetData ? Math.min(100, Math.round((budgetData.total_spent_hours / Math.max(1, budgetData.total_estimate_hours)) * 100)) : undefined}
            helperText={budgetData ? `Spent ${Math.round(budgetData.total_spent_hours || 0)}h of ${Math.round(budgetData.total_estimate_hours || 0)}h` : undefined}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={4}>
          <StatCard
            title="ROI"
            testId="card-roi"
            value={valueMetrics ? (Math.round((valueMetrics.roi || 0) * 1000) / 1000) : 0}
            icon={<TrendingUp sx={{ color: 'white' }} />}
            color="info.main"
            helperText={valueMetrics ? `Value delivered: ${Math.round((valueMetrics.value_delivered || 0) * 10) / 10}` : undefined}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={4}>
          <StatCard
            title="WIP Active"
            testId="card-wip"
            value={wipStatus ? wipStatus.total_active : 0}
            icon={<Assignment sx={{ color: 'white' }} />}
            color={(wipStatus?.assignees || []).some((a:any) => a.wip_exceeded) ? 'error.main' : 'success.main'}
            helperText={wipStatus ? `Limit: ${wipStatus.limit || '--'}` : undefined}
            onClick={() => openDrilldown('Active WIP', (row: any) => categorizeStatus(row.status) === 'in_progress')}
          />
        </Grid>

        {/* Velocity Chart */}
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>
              Team Velocity
            </Typography>
            <Box height={300}>
              <Line
                data={velocityData}
                options={{
                  responsive: true,
                  maintainAspectRatio: false,
                  plugins: {
                    legend: {
                      position: 'top' as const,
                    },
                  },
                }}
              />
            </Box>
          </Paper>
        </Grid>

        {/* Burndown Chart */}
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>
              Sprint Burndown
            </Typography>
            <Box height={300}>
              <Line
                data={burndownData}
                options={{
                  responsive: true,
                  maintainAspectRatio: false,
                  plugins: {
                    legend: {
                      position: 'top' as const,
                    },
                  },
                }}
              />
            </Box>
          </Paper>
        </Grid>

        {/* Task Distribution */}
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>
              Task Distribution
            </Typography>
            <Box height={300} display="flex" justifyContent="center" alignItems="center">
              <Doughnut
                data={taskDistribution}
                options={{
                  responsive: true,
                  maintainAspectRatio: false,
                  plugins: {
                    legend: {
                      position: 'bottom' as const,
                    },
                  },
                }}
              />
            </Box>
          </Paper>
        </Grid>

        {/* Risk Assessment */}
        <Grid item xs={12} md={8}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>
              Risk Assessment
            </Typography>
            <Box>
              {riskItems.map((risk, index) => (
                <Box
                  key={`risk-${index}-${risk.level}`}
                  data-testid={`risk-item-${index}`}
                  display="flex"
                  alignItems="center"
                  mb={2}
                  p={1.5}
                  bgcolor="grey.50"
                  borderRadius={1}
                  sx={{ cursor: risk.onClick ? 'pointer' : 'default' }}
                  onClick={risk.onClick}
                >
                  <Box
                    sx={{
                      width: 8,
                      height: 40,
                      bgcolor: risk.color,
                      borderRadius: 1,
                      mr: 2,
                    }}
                  />
                  <Box flex={1}>
                    <Typography variant="subtitle2" color={risk.color}>
                      {risk.level} Risk
                    </Typography>
                    <Typography variant="body2">{risk.message}</Typography>
                  </Box>
                </Box>
              ))}
            </Box>
          </Paper>
        </Grid>

        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>
              Upcoming Focus
            </Typography>
            {upcomingTasks.length ? (
              <List dense>
                {upcomingTasks.map(({ row, daysRemaining }: any, index: number) => (
                  <ListItem data-testid="upcoming-item" key={`upcoming-${row.id || index}`} alignItems="flex-start" divider>
                    <ListItemText
                      primary={`${row.key || 'Task'}${row.summary ? ' -- ' + row.summary : ''}`}
                      secondary={`Status: ${row.status || '--'} | Due: ${formatDueDate(row.due_date)}`}
                    />
                    <Chip
                      size="small"
                      color={daysRemaining == null ? 'default' : (daysRemaining < 0 ? 'error' : daysRemaining <= 2 ? 'warning' : 'success')}
                      label={
                        daysRemaining == null
                          ? 'Backlog'
                          : daysRemaining < 0
                          ? `Overdue ${Math.abs(daysRemaining)}d`
                          : daysRemaining === 0
                          ? 'Due today'
                          : `Due in ${daysRemaining}d`
                      }
                      sx={{ ml: 1 }}
                    />
                  </ListItem>
                ))}
              </List>
            ) : (
              <Typography variant="body2" color="text.secondary">
                No upcoming items detected for the next two weeks.
              </Typography>
            )}
          </Paper>
        </Grid>
      </Grid>
      <Dialog open={drilldown.open} onClose={closeDrilldown} maxWidth="md" fullWidth>
        <DialogTitle>{drilldown.title || 'Details'}</DialogTitle>
        <DialogContent dividers>
          {drilldown.tasks.length ? (
            <List dense>
              {drilldown.tasks.map((task: any, index: number) => (
                <ListItem data-testid="drilldown-item" key={`drilldown-${task.id || index}`} alignItems="flex-start" divider>
                  <ListItemText
                    primary={`${task.key || task.id}${task.summary ? ' -- ' + task.summary : ''}`}
                    secondary={`Status: ${task.status || '--'} | Assignee: ${task.assignee_name || 'Unassigned'} | Due: ${formatDueDate(task.due_date)}`}
                  />
                </ListItem>
              ))}
            </List>
          ) : (
            <Typography variant="body2" color="text.secondary">No items to display.</Typography>
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