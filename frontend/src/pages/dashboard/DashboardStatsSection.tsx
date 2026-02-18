import React from 'react';
import {
  Assignment,
  CheckCircle,
  Speed,
  TrendingUp,
  Warning,
} from '@mui/icons-material';
import { Box, Card, CardActionArea, CardContent, Grid, LinearProgress, Typography } from '@mui/material';
import type {
  BudgetHoursResponse,
  SprintWipStatus,
  ValueMetricsResponse,
} from '../../services/api';
import type { DashboardStats } from './dashboardDerivations';

interface StatCardProps {
  title: string;
  value: React.ReactNode;
  icon: React.ReactNode;
  color: string;
  progress?: number;
  helperText?: string;
  onClick?: () => void;
  testId?: string;
}

const StatCard: React.FC<StatCardProps> = ({
  title,
  value,
  icon,
  color,
  progress,
  helperText,
  onClick,
  testId,
}) => (
  <Card sx={{ height: '100%' }}>
    <CardActionArea
      data-testid={testId}
      sx={{ height: '100%', alignItems: 'stretch' }}
      onClick={onClick}
      disabled={!onClick}
    >
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
                <LinearProgress variant="determinate" value={progress} sx={{ height: 8, borderRadius: 4 }} />
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

interface DashboardStatsSectionProps {
  stats: DashboardStats;
  totalTasksValue: number;
  budgetData: BudgetHoursResponse | null;
  valueMetrics: ValueMetricsResponse | null;
  wipStatus: SprintWipStatus | null;
  hasActiveSprint: boolean;
  onOpenAllTasks: () => void;
  onOpenCompletedTasks: () => void;
  onOpenInProgressTasks: () => void;
  onOpenBlockingTasks: () => void;
  onOpenActiveWipTasks: () => void;
}

const DashboardStatsSection: React.FC<DashboardStatsSectionProps> = ({
  stats,
  totalTasksValue,
  budgetData,
  valueMetrics,
  wipStatus,
  hasActiveSprint,
  onOpenAllTasks,
  onOpenCompletedTasks,
  onOpenInProgressTasks,
  onOpenBlockingTasks,
  onOpenActiveWipTasks,
}) => {
  const wipValue = hasActiveSprint ? (wipStatus ? wipStatus.total_active : '--') : '--';
  const wipHelperText = hasActiveSprint
    ? wipStatus
      ? `Limit: ${wipStatus.limit || '--'}`
      : 'Loading sprint WIP'
    : 'No active sprint';

  return (
    <Grid container spacing={3} data-testid="dashboard-section-stats">
      <Grid item xs={12} sm={6} md={3}>
        <StatCard
          title="Total Tasks"
          testId="card-total"
          value={totalTasksValue}
          icon={<Assignment sx={{ color: 'white' }} />}
          color="primary.main"
          helperText="All items in scope"
          onClick={onOpenAllTasks}
        />
      </Grid>
      <Grid item xs={12} sm={6} md={3}>
        <StatCard
          title="Completed"
          testId="card-completed"
          value={stats.completedTasks}
          icon={<CheckCircle sx={{ color: 'white' }} />}
          color="success.main"
          progress={stats.totalTasks > 0 ? Math.round((stats.completedTasks / stats.totalTasks) * 100) : 0}
          helperText="Click for recently completed work"
          onClick={onOpenCompletedTasks}
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
          onClick={onOpenInProgressTasks}
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
          onClick={onOpenBlockingTasks}
        />
      </Grid>

      <Grid item xs={12} sm={6} md={4}>
        <StatCard
          title="Budget Health"
          testId="card-budget"
          value={budgetData ? `${budgetData.remaining_hours}h` : '--'}
          icon={<Speed sx={{ color: 'white' }} />}
          color={budgetData?.overrun ? 'error.main' : 'success.main'}
          progress={
            budgetData
              ? Math.min(
                  100,
                  Math.round(
                    (budgetData.total_spent_hours / Math.max(1, budgetData.total_estimate_hours)) * 100
                  )
                )
              : undefined
          }
          helperText={
            budgetData
              ? `Spent ${Math.round(budgetData.total_spent_hours || 0)}h of ${Math.round(
                  budgetData.total_estimate_hours || 0
                )}h`
              : undefined
          }
        />
      </Grid>
      <Grid item xs={12} sm={6} md={4}>
        <StatCard
          title="ROI"
          testId="card-roi"
          value={valueMetrics ? Math.round((valueMetrics.roi || 0) * 1000) / 1000 : '--'}
          icon={<TrendingUp sx={{ color: 'white' }} />}
          color="info.main"
          helperText={
            valueMetrics
              ? `Value delivered: ${Math.round((valueMetrics.value_delivered || 0) * 10) / 10}`
              : undefined
          }
        />
      </Grid>
      <Grid item xs={12} sm={6} md={4}>
        <StatCard
          title="WIP Active"
          testId="card-wip"
          value={wipValue}
          icon={<Assignment sx={{ color: 'white' }} />}
          color={
            !hasActiveSprint
              ? 'grey.500'
              : (wipStatus?.assignees || []).some((assignee) => assignee.wip_exceeded)
                ? 'error.main'
                : 'success.main'
          }
          helperText={wipHelperText}
          onClick={hasActiveSprint ? onOpenActiveWipTasks : undefined}
        />
      </Grid>
    </Grid>
  );
};

DashboardStatsSection.displayName = 'DashboardStatsSection';

export default React.memo(DashboardStatsSection);
