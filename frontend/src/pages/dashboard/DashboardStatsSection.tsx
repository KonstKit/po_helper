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
import { DASHBOARD_TEST_IDS } from './dashboardContract';

type ProgressColor = 'primary' | 'success' | 'warning' | 'error';

interface StatCardProps {
  title: string;
  value: React.ReactNode;
  icon: React.ReactNode;
  color: string;
  /** True completion ratio shown in the caption; may exceed 100 (e.g. budget overrun). */
  progress?: number;
  /**
   * Optional fill width for the bar when it must differ from `progress`
   * (e.g. cap the bar at 100% while the caption still reports 152%).
   */
  progressBarValue?: number;
  progressColor?: ProgressColor;
  /** Overrides the default "{progress}% Complete" caption. */
  progressLabel?: string;
  helperText?: string;
  onClick?: () => void;
  testId?: string;
}

const clampPercent = (value: number): number => Math.min(100, Math.max(0, value));

const StatCard: React.FC<StatCardProps> = ({
  title,
  value,
  icon,
  color,
  progress,
  progressBarValue,
  progressColor = 'primary',
  progressLabel,
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
                <LinearProgress
                  variant="determinate"
                  color={progressColor}
                  value={clampPercent(progressBarValue ?? progress)}
                  sx={{ height: 8, borderRadius: 4 }}
                />
                <Typography variant="body2" color="textSecondary" mt={0.5}>
                  {progressLabel ?? `${progress}% Complete`}
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

const NOT_CONFIGURED = '—'; // em dash

// Coerce a possibly null/undefined/NaN numeric field to a finite number (C1).
const toFinite = (value: unknown): number => {
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

const formatHours = (value: number): string => `${Math.round(value)}h`;

interface BudgetCardModel {
  configured: boolean;
  value: string;
  helperText?: string;
  progress?: number;
  progressBarValue?: number;
  progressColor?: ProgressColor;
  progressLabel?: string;
  iconColor: string;
}

// C2 / M3: turn the raw budget payload into a self-consistent card model.
// When no budget is configured we surface a "not configured" state instead of a
// misleading 0; when spent exceeds budget we report the true percentage, flag
// the overrun and turn the bar red (while capping its visual fill at 100%).
const buildBudgetCardModel = (budgetData: BudgetHoursResponse | null): BudgetCardModel => {
  if (!budgetData) {
    return { configured: false, value: '--', iconColor: 'grey.500' };
  }

  const spent = toFinite(budgetData.total_spent_hours);
  const budget = toFinite(budgetData.total_estimate_hours);

  if (budget <= 0) {
    return {
      configured: false,
      value: NOT_CONFIGURED,
      helperText:
        spent > 0
          ? `No estimate set (spent ${formatHours(spent)})`
          : 'Budget not configured',
      iconColor: 'grey.500',
    };
  }

  const remaining = budget - spent;
  const percent = Math.round((spent / budget) * 100);
  const overBudget = spent > budget;

  return {
    configured: true,
    value: overBudget ? `Over by ${formatHours(spent - budget)}` : `${formatHours(remaining)} left`,
    helperText: `Spent ${formatHours(spent)} of ${formatHours(budget)}`,
    progress: percent,
    progressBarValue: Math.min(100, percent),
    progressColor: overBudget ? 'error' : percent >= 80 ? 'warning' : 'success',
    progressLabel: overBudget ? `${percent}% of budget - over budget` : `${percent}% of budget`,
    iconColor: overBudget ? 'error.main' : 'success.main',
  };
};

interface ValueCardModel {
  configured: boolean;
  value: React.ReactNode;
  helperText?: string;
}

// M3: ROI / value-delivered render "Not configured" when there is genuinely no
// input data, instead of a bare 0 that looks like a measured result.
const buildValueCardModel = (valueMetrics: ValueMetricsResponse | null): ValueCardModel => {
  if (!valueMetrics) {
    return { configured: false, value: '--' };
  }

  const roi = toFinite(valueMetrics.roi);
  const valueDelivered = toFinite(valueMetrics.value_delivered);
  const spent = toFinite(valueMetrics.total_spent_hours);
  const hasInputs = roi !== 0 || valueDelivered !== 0 || spent !== 0;

  if (!hasInputs) {
    return {
      configured: false,
      value: NOT_CONFIGURED,
      helperText: 'Value tracking not configured',
    };
  }

  return {
    configured: true,
    value: Math.round(roi * 1000) / 1000,
    helperText: `Value delivered: ${Math.round(valueDelivered * 10) / 10}`,
  };
};

interface DashboardStatsSectionProps {
  stats: DashboardStats;
  totalTasksValue: number;
  budgetData: BudgetHoursResponse | null;
  valueMetrics: ValueMetricsResponse | null;
  wipStatus: SprintWipStatus | null;
  hasActiveSprint: boolean;
  wipState: 'no_sprint' | 'loading' | 'ready' | 'not_available' | 'error';
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
  wipState,
  onOpenAllTasks,
  onOpenCompletedTasks,
  onOpenInProgressTasks,
  onOpenBlockingTasks,
  onOpenActiveWipTasks,
}) => {
  const budgetCard = buildBudgetCardModel(budgetData);
  const valueCard = buildValueCardModel(valueMetrics);
  const hasReadyWip = hasActiveSprint && wipState === 'ready' && wipStatus !== null;
  const wipValue = hasReadyWip ? wipStatus.total_active : wipState === 'no_sprint' ? '--' : 'N/A';
  const wipHelperText =
    wipState === 'ready'
      ? `Limit: ${wipStatus?.limit || '--'}`
      : wipState === 'loading'
        ? 'Loading sprint WIP'
        : wipState === 'error'
          ? 'Failed to load WIP data'
          : wipState === 'not_available'
            ? 'WIP data not available for active sprint'
            : 'No active sprint';
  const wipColor =
    wipState === 'ready'
      ? (wipStatus?.assignees || []).some((assignee) => assignee.wip_exceeded)
        ? 'error.main'
        : 'success.main'
      : wipState === 'error'
        ? 'warning.main'
        : 'grey.500';

  return (
    <Grid container spacing={3} data-testid={DASHBOARD_TEST_IDS.sectionStats}>
      <Grid item xs={12} sm={6} md={3}>
        <StatCard
          title="Total Tasks"
          testId={DASHBOARD_TEST_IDS.cardTotal}
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
          testId={DASHBOARD_TEST_IDS.cardCompleted}
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
          testId={DASHBOARD_TEST_IDS.cardInProgress}
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
          testId={DASHBOARD_TEST_IDS.cardBlockers}
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
          testId={DASHBOARD_TEST_IDS.cardBudget}
          value={budgetCard.value}
          icon={<Speed sx={{ color: 'white' }} />}
          color={budgetCard.iconColor}
          progress={budgetCard.progress}
          progressBarValue={budgetCard.progressBarValue}
          progressColor={budgetCard.progressColor}
          progressLabel={budgetCard.progressLabel}
          helperText={budgetCard.helperText}
        />
      </Grid>
      <Grid item xs={12} sm={6} md={4}>
        <StatCard
          title="ROI"
          testId={DASHBOARD_TEST_IDS.cardRoi}
          value={valueCard.value}
          icon={<TrendingUp sx={{ color: 'white' }} />}
          color={valueCard.configured ? 'info.main' : 'grey.500'}
          helperText={valueCard.helperText}
        />
      </Grid>
      <Grid item xs={12} sm={6} md={4}>
        <StatCard
          title="WIP Active"
          testId={DASHBOARD_TEST_IDS.cardWip}
          value={wipValue}
          icon={<Assignment sx={{ color: 'white' }} />}
          color={wipColor}
          helperText={wipHelperText}
          onClick={hasReadyWip ? onOpenActiveWipTasks : undefined}
        />
      </Grid>
    </Grid>
  );
};

DashboardStatsSection.displayName = 'DashboardStatsSection';

export default React.memo(DashboardStatsSection);
