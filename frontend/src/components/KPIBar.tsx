import React from 'react';
import { Box, Paper, Typography, Grid, Tooltip } from '@mui/material';
import {
  TrendingUp as TrendingUpIcon,
  TrendingDown as TrendingDownIcon,
  Remove as RemoveIcon,
  Info as InfoIcon,
} from '@mui/icons-material';

export interface KPIMetric {
  label: string;
  value: string | number;
  unit?: string;
  change?: number; // Percentage change (e.g., +5.2 or -3.1)
  trend?: 'up' | 'down' | 'flat';
  status?: 'success' | 'warning' | 'error' | 'neutral';
  tooltip?: string;
  onClick?: () => void;
}

export interface KPIBarProps {
  metrics: KPIMetric[];
}

const KPIBar: React.FC<KPIBarProps> = React.memo(({ metrics }) => {
  const getStatusColor = (status?: string) => {
    switch (status) {
      case 'success':
        return '#4caf50'; // Green
      case 'warning':
        return '#ff9800'; // Orange
      case 'error':
        return '#f44336'; // Red
      case 'neutral':
      default:
        return '#2196f3'; // Blue
    }
  };

  const getTrendIcon = (trend?: string, change?: number) => {
    if (!trend || trend === 'flat') {
      return <RemoveIcon sx={{ fontSize: 16, color: 'text.secondary' }} />;
    }
    if (trend === 'up') {
      return <TrendingUpIcon sx={{ fontSize: 16, color: change && change > 0 ? 'success.main' : 'error.main' }} />;
    }
    if (trend === 'down') {
      return <TrendingDownIcon sx={{ fontSize: 16, color: change && change < 0 ? 'error.main' : 'success.main' }} />;
    }
    return null;
  };

  const formatChange = (change?: number) => {
    if (change === undefined || change === null) return null;
    const sign = change > 0 ? '+' : '';
    return `${sign}${change.toFixed(1)}%`;
  };

  return (
    <Paper
      elevation={0}
      sx={{
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        color: 'white',
        p: 3,
        mb: 3,
        borderRadius: 2,
      }}
    >
      <Grid container spacing={3}>
        {metrics.map((metric, index) => (
          <Grid item xs={12} sm={6} md={3} key={index}>
            <Box
              sx={{
                cursor: metric.onClick ? 'pointer' : 'default',
                '&:hover': metric.onClick
                  ? {
                      opacity: 0.9,
                      transform: 'translateY(-2px)',
                      transition: 'all 0.2s',
                    }
                  : {},
              }}
              onClick={metric.onClick}
            >
              <Box display="flex" alignItems="center" mb={1}>
                <Typography
                  variant="body2"
                  sx={{
                    opacity: 0.9,
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
                    <InfoIcon
                      sx={{
                        fontSize: 14,
                        ml: 0.5,
                        opacity: 0.7,
                        cursor: 'help',
                      }}
                    />
                  </Tooltip>
                )}
              </Box>

              <Box display="flex" alignItems="baseline" gap={1}>
                <Typography
                  variant="h3"
                  sx={{
                    fontWeight: 700,
                    color: getStatusColor(metric.status),
                    textShadow: '0 2px 4px rgba(0,0,0,0.1)',
                  }}
                >
                  {metric.value}
                </Typography>
                {metric.unit && (
                  <Typography
                    variant="body1"
                    sx={{
                      opacity: 0.8,
                      fontWeight: 500,
                    }}
                  >
                    {metric.unit}
                  </Typography>
                )}
              </Box>

              {(metric.change !== undefined || metric.trend) && (
                <Box display="flex" alignItems="center" gap={0.5} mt={1}>
                  {getTrendIcon(metric.trend, metric.change)}
                  {metric.change !== undefined && (
                    <Typography
                      variant="body2"
                      sx={{
                        fontWeight: 600,
                        color:
                          metric.change > 0
                            ? 'rgba(76, 175, 80, 0.9)'
                            : metric.change < 0
                            ? 'rgba(244, 67, 54, 0.9)'
                            : 'rgba(255, 255, 255, 0.7)',
                      }}
                    >
                      {formatChange(metric.change)}
                    </Typography>
                  )}
                  <Typography
                    variant="caption"
                    sx={{
                      opacity: 0.7,
                      ml: 0.5,
                    }}
                  >
                    vs last week
                  </Typography>
                </Box>
              )}
            </Box>
          </Grid>
        ))}
      </Grid>
    </Paper>
  );
});

KPIBar.displayName = 'KPIBar';

export default KPIBar;
