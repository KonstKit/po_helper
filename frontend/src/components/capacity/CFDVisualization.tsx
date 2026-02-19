import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Paper,
  Typography,
  Stack,
  Alert,
  Button,
  Skeleton,
  Card,
  CardContent,
  Grid,
  Chip,
  Tooltip,
  ToggleButton,
  ToggleButtonGroup,
  Divider,
} from '@mui/material';
import type { ChipProps } from '@mui/material';
import {
  Refresh as RefreshIcon,
  TrendingUp as TrendingUpIcon,
  TrendingDown as TrendingDownIcon,
  TrendingFlat as TrendingFlatIcon,
  Speed as SpeedIcon,
  Schedule as ScheduleIcon,
  Warning as WarningIcon,
  DataUsage as DataUsageIcon,
} from '@mui/icons-material';
import { Line } from 'react-chartjs-2';
import { ChartOptions } from 'chart.js';
import {
  CFDData,
  CFDSnapshot,
  FlowMetrics,
  getCFDData,
  getFlowMetrics,
} from '../../services/api';

interface CFDVisualizationProps {
  projectId: number;
  sprintId?: number;
  height?: number;
}

// Color palette for CFD status areas (from Done to Backlog for proper stacking)
const STATUS_COLORS = {
  done: { bg: 'rgba(76, 175, 80, 0.7)', border: 'rgb(76, 175, 80)' },
  testing: { bg: 'rgba(156, 39, 176, 0.7)', border: 'rgb(156, 39, 176)' },
  in_review: { bg: 'rgba(33, 150, 243, 0.7)', border: 'rgb(33, 150, 243)' },
  in_progress: { bg: 'rgba(255, 152, 0, 0.7)', border: 'rgb(255, 152, 0)' },
  todo: { bg: 'rgba(158, 158, 158, 0.7)', border: 'rgb(158, 158, 158)' },
  backlog: { bg: 'rgba(96, 125, 139, 0.7)', border: 'rgb(96, 125, 139)' },
};

const STATUS_LABELS: Record<string, string> = {
  done: 'Done',
  testing: 'Testing',
  in_review: 'In Review',
  in_progress: 'In Progress',
  todo: 'To Do',
  backlog: 'Backlog',
};

type ViewMode = 'cumulative' | 'wip' | 'throughput';
type WipTrend = 'increasing' | 'decreasing' | 'stable';

const MetricCard: React.FC<{
  title: string;
  value: string | number;
  subtitle?: string;
  icon: React.ReactNode;
  color?: 'success' | 'warning' | 'error' | 'info';
}> = ({ title, value, subtitle, icon, color = 'info' }) => (
  <Card sx={{ height: '100%' }}>
    <CardContent>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
        <Box sx={{ color: `${color}.main` }}>{icon}</Box>
        <Typography variant="body2" color="text.secondary">
          {title}
        </Typography>
      </Stack>
      <Typography variant="h5" fontWeight="bold">
        {value}
      </Typography>
      {subtitle && (
        <Typography variant="caption" color="text.secondary">
          {subtitle}
        </Typography>
      )}
    </CardContent>
  </Card>
);

const WIP_TREND_CONFIG: Record<WipTrend, { icon: typeof TrendingUpIcon; color: ChipProps['color']; label: string }> = {
  increasing: { icon: TrendingUpIcon, color: 'warning', label: 'WIP Increasing' },
  decreasing: { icon: TrendingDownIcon, color: 'success', label: 'WIP Decreasing' },
  stable: { icon: TrendingFlatIcon, color: 'info', label: 'WIP Stable' },
};

const WIPTrendIndicator: React.FC<{ trend: WipTrend }> = ({ trend }) => {
  const config = WIP_TREND_CONFIG[trend];
  const Icon = config.icon;

  return (
    <Chip
      icon={<Icon />}
      label={config.label}
      color={config.color}
      size="small"
      variant="outlined"
    />
  );
};

const CFDVisualization: React.FC<CFDVisualizationProps> = ({
  projectId,
  sprintId,
  height = 400,
}) => {
  const [cfdData, setCfdData] = useState<CFDData | null>(null);
  const [metrics, setMetrics] = useState<FlowMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>('cumulative');

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cfd, flowMetrics] = await Promise.all([
        getCFDData(projectId, { sprintId, limit: 30 }),
        getFlowMetrics(projectId, { sprintId }),
      ]);
      setCfdData(cfd);
      setMetrics(flowMetrics);
    } catch (err) {
      console.error('Failed to load CFD data:', err);
      setError('Failed to load Cumulative Flow Diagram data');
    } finally {
      setLoading(false);
    }
  }, [projectId, sprintId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const buildCumulativeChartData = (snapshots: CFDSnapshot[]) => {
    const labels = snapshots.map((s) =>
      new Date(s.snapshot_date).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
      })
    );

    // For CFD, we stack from bottom (Done) to top (Backlog)
    // Each area shows cumulative totals
    const datasets = [
      {
        label: STATUS_LABELS.done,
        data: snapshots.map((s) => s.done_count),
        backgroundColor: STATUS_COLORS.done.bg,
        borderColor: STATUS_COLORS.done.border,
        borderWidth: 1,
        fill: true,
        tension: 0.3,
        pointRadius: 2,
      },
      {
        label: STATUS_LABELS.testing,
        data: snapshots.map((s) => s.done_count + s.testing_count),
        backgroundColor: STATUS_COLORS.testing.bg,
        borderColor: STATUS_COLORS.testing.border,
        borderWidth: 1,
        fill: '-1', // Fill to previous dataset
        tension: 0.3,
        pointRadius: 2,
      },
      {
        label: STATUS_LABELS.in_review,
        data: snapshots.map((s) => s.done_count + s.testing_count + s.in_review_count),
        backgroundColor: STATUS_COLORS.in_review.bg,
        borderColor: STATUS_COLORS.in_review.border,
        borderWidth: 1,
        fill: '-1',
        tension: 0.3,
        pointRadius: 2,
      },
      {
        label: STATUS_LABELS.in_progress,
        data: snapshots.map(
          (s) => s.done_count + s.testing_count + s.in_review_count + s.in_progress_count
        ),
        backgroundColor: STATUS_COLORS.in_progress.bg,
        borderColor: STATUS_COLORS.in_progress.border,
        borderWidth: 1,
        fill: '-1',
        tension: 0.3,
        pointRadius: 2,
      },
      {
        label: STATUS_LABELS.todo,
        data: snapshots.map(
          (s) =>
            s.done_count +
            s.testing_count +
            s.in_review_count +
            s.in_progress_count +
            s.todo_count
        ),
        backgroundColor: STATUS_COLORS.todo.bg,
        borderColor: STATUS_COLORS.todo.border,
        borderWidth: 1,
        fill: '-1',
        tension: 0.3,
        pointRadius: 2,
      },
      {
        label: STATUS_LABELS.backlog,
        data: snapshots.map((s) => s.total_count),
        backgroundColor: STATUS_COLORS.backlog.bg,
        borderColor: STATUS_COLORS.backlog.border,
        borderWidth: 1,
        fill: '-1',
        tension: 0.3,
        pointRadius: 2,
      },
    ];

    return { labels, datasets };
  };

  const buildWIPChartData = (snapshots: CFDSnapshot[]) => {
    const labels = snapshots.map((s) =>
      new Date(s.snapshot_date).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
      })
    );

    return {
      labels,
      datasets: [
        {
          label: 'Work In Progress',
          data: snapshots.map((s) => s.wip_count),
          backgroundColor: 'rgba(255, 152, 0, 0.3)',
          borderColor: 'rgb(255, 152, 0)',
          borderWidth: 2,
          fill: true,
          tension: 0.3,
          pointRadius: 4,
          pointHoverRadius: 6,
        },
        {
          label: 'Done',
          data: snapshots.map((s) => s.done_count),
          backgroundColor: 'rgba(76, 175, 80, 0.3)',
          borderColor: 'rgb(76, 175, 80)',
          borderWidth: 2,
          fill: true,
          tension: 0.3,
          pointRadius: 4,
          pointHoverRadius: 6,
        },
      ],
    };
  };

  const buildThroughputChartData = (snapshots: CFDSnapshot[]) => {
    const labels = snapshots.map((s) =>
      new Date(s.snapshot_date).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
      })
    );

    // Calculate daily throughput (items completed per day)
    const throughputData = snapshots.map((s, i) => {
      if (i === 0) return 0;
      const prevDone = snapshots[i - 1].done_count;
      return Math.max(0, s.done_count - prevDone);
    });

    return {
      labels,
      datasets: [
        {
          label: 'Daily Throughput',
          data: throughputData,
          backgroundColor: 'rgba(33, 150, 243, 0.5)',
          borderColor: 'rgb(33, 150, 243)',
          borderWidth: 2,
          fill: true,
          tension: 0.3,
          pointRadius: 4,
          pointHoverRadius: 6,
        },
      ],
    };
  };

  const getChartOptions = (): ChartOptions<'line'> => ({
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: true,
        position: 'bottom',
        labels: {
          usePointStyle: true,
          padding: 15,
        },
      },
      tooltip: {
        mode: 'index',
        intersect: false,
        callbacks: {
          label: (context) => {
            const label = context.dataset.label || '';
            const value = context.parsed.y;
            if (viewMode === 'cumulative') {
              // For cumulative view, show the actual count in that status
              const dataIndex = context.dataIndex;
              if (cfdData?.snapshots[dataIndex]) {
                const snapshot = cfdData.snapshots[dataIndex];
                const statusCounts: Record<string, number> = {
                  Done: snapshot.done_count,
                  Testing: snapshot.testing_count,
                  'In Review': snapshot.in_review_count,
                  'In Progress': snapshot.in_progress_count,
                  'To Do': snapshot.todo_count,
                  Backlog: snapshot.backlog_count,
                };
                return `${label}: ${statusCounts[label] || 0} items`;
              }
            }
            return `${label}: ${value}`;
          },
        },
      },
    },
    scales: {
      y: {
        stacked: viewMode === 'cumulative',
        beginAtZero: true,
        title: {
          display: true,
          text: viewMode === 'throughput' ? 'Items Completed' : 'Number of Items',
          font: { size: 12 },
        },
      },
      x: {
        title: {
          display: true,
          text: 'Date',
          font: { size: 12 },
        },
      },
    },
    interaction: {
      mode: 'nearest',
      axis: 'x',
      intersect: false,
    },
  });

  if (loading) {
    return (
      <Paper sx={{ p: 2 }}>
        <Stack spacing={2}>
          <Skeleton variant="rectangular" height={60} />
          <Skeleton variant="rectangular" height={height} />
        </Stack>
      </Paper>
    );
  }

  const chartData =
    cfdData && cfdData.snapshots.length > 0
      ? viewMode === 'cumulative'
        ? buildCumulativeChartData(cfdData.snapshots)
        : viewMode === 'wip'
        ? buildWIPChartData(cfdData.snapshots)
        : buildThroughputChartData(cfdData.snapshots)
      : null;

  return (
    <Box>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Header */}
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        sx={{ mb: 3 }}
        flexWrap="wrap"
        gap={2}
      >
        <Typography variant="h6">Cumulative Flow Diagram</Typography>
        <Stack direction="row" spacing={1} alignItems="center">
          <ToggleButtonGroup
            value={viewMode}
            exclusive
            onChange={(_, v) => v && setViewMode(v)}
            size="small"
          >
            <ToggleButton value="cumulative">
              <Tooltip title="Cumulative Flow">
                <DataUsageIcon fontSize="small" />
              </Tooltip>
            </ToggleButton>
            <ToggleButton value="wip">
              <Tooltip title="WIP Over Time">
                <SpeedIcon fontSize="small" />
              </Tooltip>
            </ToggleButton>
            <ToggleButton value="throughput">
              <Tooltip title="Daily Throughput">
                <TrendingUpIcon fontSize="small" />
              </Tooltip>
            </ToggleButton>
          </ToggleButtonGroup>
          <Button startIcon={<RefreshIcon />} onClick={loadData} size="small">
            Refresh
          </Button>
        </Stack>
      </Stack>

      {/* Flow Metrics Cards */}
      {metrics && (
        <Grid container spacing={2} sx={{ mb: 3 }}>
          <Grid item xs={6} sm={3}>
            <MetricCard
              title="Avg Cycle Time"
              value={
                metrics.avg_cycle_time_hours
                  ? `${(metrics.avg_cycle_time_hours / 24).toFixed(1)}d`
                  : '-'
              }
              subtitle="Start → Done"
              icon={<ScheduleIcon />}
              color="info"
            />
          </Grid>
          <Grid item xs={6} sm={3}>
            <MetricCard
              title="Avg Lead Time"
              value={metrics.avg_lead_time_days ? `${metrics.avg_lead_time_days.toFixed(1)}d` : '-'}
              subtitle="Created → Done"
              icon={<ScheduleIcon />}
              color="info"
            />
          </Grid>
          <Grid item xs={6} sm={3}>
            <MetricCard
              title="Throughput"
              value={
                metrics.avg_throughput_per_day
                  ? `${metrics.avg_throughput_per_day.toFixed(1)}/day`
                  : '-'
              }
              subtitle="Items completed"
              icon={<SpeedIcon />}
              color="success"
            />
          </Grid>
          <Grid item xs={6} sm={3}>
            <Card sx={{ height: '100%' }}>
              <CardContent>
                <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
                  {metrics.bottleneck_status && (
                    <Box sx={{ color: 'warning.main' }}>
                      <WarningIcon fontSize="small" />
                    </Box>
                  )}
                  <Typography variant="body2" color="text.secondary">
                    WIP Trend
                  </Typography>
                </Stack>
                <WIPTrendIndicator trend={metrics.wip_trend} />
                {metrics.bottleneck_status && (
                  <Typography variant="caption" color="warning.main" sx={{ display: 'block', mt: 1 }}>
                    Bottleneck: {STATUS_LABELS[metrics.bottleneck_status] || metrics.bottleneck_status}
                  </Typography>
                )}
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}

      {/* Chart */}
      <Paper sx={{ p: 2 }}>
        {cfdData && cfdData.snapshots.length > 0 ? (
          <Box sx={{ height }}>
            <Line data={chartData!} options={getChartOptions()} />
          </Box>
        ) : (
          <Alert severity="info">
            No CFD data available. CFD snapshots are generated automatically when issues are
            synchronized. Run a sync to start collecting flow data.
          </Alert>
        )}

        {/* Legend explanation */}
        <Divider sx={{ my: 2 }} />
        <Typography variant="caption" color="text.secondary">
          {viewMode === 'cumulative' && (
            <>
              <strong>How to read:</strong> Each colored band represents items in that status.
              Wider bands indicate more items; growing bands may indicate bottlenecks.
              The slope of the Done area shows delivery rate.
            </>
          )}
          {viewMode === 'wip' && (
            <>
              <strong>How to read:</strong> WIP (Work In Progress) shows items currently being
              worked on. High WIP can indicate context switching and longer cycle times.
            </>
          )}
          {viewMode === 'throughput' && (
            <>
              <strong>How to read:</strong> Daily throughput shows how many items were completed
              each day. Consistent throughput indicates predictable delivery.
            </>
          )}
        </Typography>
      </Paper>
    </Box>
  );
};

export default CFDVisualization;
