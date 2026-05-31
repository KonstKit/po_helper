import React from 'react';
import { Box, Grid, Paper, Tooltip, Typography, alpha, useTheme } from '@mui/material';
import type { Theme } from '@mui/material/styles';
import {
  Info as InfoIcon,
  Remove as RemoveIcon,
  TrendingDown as TrendingDownIcon,
  TrendingUp as TrendingUpIcon,
} from '@mui/icons-material';
import { DASHBOARD_TEST_IDS } from './dashboardContract';
import type { KPIMetric } from './dashboardContract';

export interface DashboardKpiBannerProps {
  metrics: KPIMetric[];
}

/**
 * Flat, on-theme KPI banner (UX review M8 + M9).
 *
 * Replaces the previous off-brand purple gradient banner with a flat, subtle
 * teal tint pulled from the app palette, and colours each KPI number by its
 * semantic `status` (success = good, warning = at risk, error = over threshold,
 * neutral = informational) instead of a meaningless per-position rainbow.
 *
 * Rendered from within the dashboard scope so the shared `KPIBar` component is
 * left untouched for any other callers.
 */
const statusColor = (theme: Theme, status?: KPIMetric['status']): string => {
  switch (status) {
    case 'success':
      return theme.palette.success.main;
    case 'warning':
      return theme.palette.warning.main;
    case 'error':
      return theme.palette.error.main;
    case 'neutral':
    default:
      // Informational metrics read as neutral text rather than an accent colour.
      return theme.palette.text.primary;
  }
};

const formatChange = (change?: number): string | null => {
  if (change === undefined || change === null || !Number.isFinite(change)) return null;
  const sign = change > 0 ? '+' : '';
  return `${sign}${change.toFixed(1)}%`;
};

const TrendIcon: React.FC<{ trend?: KPIMetric['trend'] }> = ({ trend }) => {
  if (trend === 'up') {
    return <TrendingUpIcon sx={{ fontSize: 16, color: 'success.main' }} />;
  }
  if (trend === 'down') {
    return <TrendingDownIcon sx={{ fontSize: 16, color: 'error.main' }} />;
  }
  return <RemoveIcon sx={{ fontSize: 16, color: 'text.secondary' }} />;
};

const DashboardKpiBanner: React.FC<DashboardKpiBannerProps> = ({ metrics }) => {
  const theme = useTheme();
  // Teal accent from the app palette (this theme's teal lives in `secondary`).
  const teal = theme.palette.secondary.main;

  return (
    <Paper
      elevation={0}
      data-testid={DASHBOARD_TEST_IDS.kpiBanner}
      sx={{
        backgroundColor: alpha(teal, 0.06),
        border: `1px solid ${alpha(teal, 0.24)}`,
        borderRadius: 2,
        p: 3,
        mb: 3,
      }}
    >
      <Grid container spacing={3}>
        {metrics.map((metric, index) => {
          const changeLabel = formatChange(metric.change);
          return (
            <Grid item xs={12} sm={6} md={3} key={index}>
              <Box
                onClick={metric.onClick}
                sx={{
                  cursor: metric.onClick ? 'pointer' : 'default',
                  '&:hover': metric.onClick
                    ? { transform: 'translateY(-2px)', transition: 'all 0.2s' }
                    : {},
                }}
              >
                <Box display="flex" alignItems="center" mb={1}>
                  <Typography
                    variant="body2"
                    sx={{
                      color: 'text.secondary',
                      textTransform: 'uppercase',
                      letterSpacing: 1,
                      fontSize: '0.75rem',
                      fontWeight: 600,
                    }}
                  >
                    {metric.label}
                  </Typography>
                  {metric.tooltip && (
                    <Tooltip title={metric.tooltip} arrow>
                      <InfoIcon sx={{ fontSize: 14, ml: 0.5, color: 'text.disabled', cursor: 'help' }} />
                    </Tooltip>
                  )}
                </Box>

                <Box display="flex" alignItems="baseline" gap={1}>
                  <Typography variant="h3" sx={{ fontWeight: 700, color: statusColor(theme, metric.status) }}>
                    {metric.value}
                  </Typography>
                  {metric.unit && (
                    <Typography variant="body1" sx={{ color: 'text.secondary', fontWeight: 500 }}>
                      {metric.unit}
                    </Typography>
                  )}
                </Box>

                {(changeLabel !== null || metric.trend) && (
                  <Box display="flex" alignItems="center" gap={0.5} mt={1}>
                    <TrendIcon trend={metric.trend} />
                    {changeLabel !== null && (
                      <Typography
                        variant="body2"
                        sx={{
                          fontWeight: 600,
                          color:
                            metric.change && metric.change > 0
                              ? 'success.main'
                              : metric.change && metric.change < 0
                                ? 'error.main'
                                : 'text.secondary',
                        }}
                      >
                        {changeLabel}
                      </Typography>
                    )}
                    <Typography variant="caption" sx={{ color: 'text.secondary', ml: 0.5 }}>
                      vs last week
                    </Typography>
                  </Box>
                )}
              </Box>
            </Grid>
          );
        })}
      </Grid>
    </Paper>
  );
};

DashboardKpiBanner.displayName = 'DashboardKpiBanner';

export default React.memo(DashboardKpiBanner);
