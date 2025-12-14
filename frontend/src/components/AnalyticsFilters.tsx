import React, { useState } from 'react';
import {
  Box,
  Paper,
  Button,
  Chip,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Collapse,
  IconButton,
  Typography,
  Grid,
  Divider,
} from '@mui/material';
import {
  ExpandMore as ExpandMoreIcon,
  FilterList as FilterIcon,
  Settings as SettingsIcon,
} from '@mui/icons-material';

interface AnalyticsFiltersProps {
  projectId: number | 'all';
  onProjectChange: (id: number | 'all') => void;
  projects: any[];
  timeRange: '1month' | '3months' | '6months' | '1year';
  onTimeRangeChange: (range: '1month' | '3months' | '6months' | '1year') => void;
  prMetricsRange?: '14d' | '30d' | '90d' | 'all';
  onPRMetricsRangeChange?: (range: '14d' | '30d' | '90d' | 'all') => void;
}

const QUICK_FILTERS = [
  { value: '1month', label: 'Last Month' },
  { value: '3months', label: 'Last 3 Months' },
  { value: '6months', label: 'Last 6 Months' },
];

export const AnalyticsFilters: React.FC<AnalyticsFiltersProps> = ({
  projectId,
  onProjectChange,
  projects,
  timeRange,
  onTimeRangeChange,
  prMetricsRange,
  onPRMetricsRangeChange,
}) => {
  const [advancedExpanded, setAdvancedExpanded] = useState(false);

  const currentProject = projects.find((p) => p.id === projectId);

  return (
    <Paper sx={{ p: 2, mb: 3 }}>
      {/* Quick Filters */}
      <Box display="flex" alignItems="center" gap={2} mb={2}>
        <FilterIcon color="action" />
        <Typography variant="subtitle1" fontWeight={600}>
          Quick Filters
        </Typography>
      </Box>

      <Grid container spacing={2} alignItems="center" mb={2}>
        <Grid item xs={12} sm={6} md={4}>
          <FormControl fullWidth size="small">
            <InputLabel>Project</InputLabel>
            <Select
              value={projectId}
              onChange={(e) => onProjectChange(e.target.value as number | 'all')}
              label="Project"
            >
              <MenuItem value="all">All Projects</MenuItem>
              {projects.map((p) => (
                <MenuItem key={p.id} value={p.id}>
                  {p.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Grid>

        <Grid item xs={12} sm={6} md={8}>
          <Box display="flex" gap={1} flexWrap="wrap">
            {QUICK_FILTERS.map((filter) => (
              <Chip
                key={filter.value}
                label={filter.label}
                onClick={() => onTimeRangeChange(filter.value as any)}
                color={timeRange === filter.value ? 'primary' : 'default'}
                variant={timeRange === filter.value ? 'filled' : 'outlined'}
                clickable
              />
            ))}
          </Box>
        </Grid>
      </Grid>

      {/* Currently Selected */}
      <Box display="flex" alignItems="center" gap={1} mb={1}>
        <Typography variant="body2" color="text.secondary">
          Showing:
        </Typography>
        <Chip
          label={currentProject?.name || 'All Projects'}
          size="small"
          color="primary"
          variant="outlined"
        />
        <Chip
          label={QUICK_FILTERS.find((f) => f.value === timeRange)?.label || timeRange}
          size="small"
          color="primary"
          variant="outlined"
        />
      </Box>

      <Divider sx={{ my: 2 }} />

      {/* Advanced Filters Toggle */}
      <Box display="flex" justifyContent="space-between" alignItems="center">
        <Button
          startIcon={<SettingsIcon />}
          endIcon={
            <ExpandMoreIcon
              sx={{
                transform: advancedExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
                transition: 'transform 0.3s',
              }}
            />
          }
          onClick={() => setAdvancedExpanded(!advancedExpanded)}
          size="small"
        >
          Advanced Filters
        </Button>
        {advancedExpanded && (
          <Button
            size="small"
            onClick={() => {
              onTimeRangeChange('6months');
              if (onPRMetricsRangeChange) onPRMetricsRangeChange('30d');
            }}
          >
            Reset to Defaults
          </Button>
        )}
      </Box>

      {/* Advanced Filters Content */}
      <Collapse in={advancedExpanded}>
        <Box mt={2} p={2} bgcolor="action.hover" borderRadius={1}>
          <Grid container spacing={2}>
            <Grid item xs={12} sm={6} md={4}>
              <FormControl fullWidth size="small">
                <InputLabel>Time Range</InputLabel>
                <Select
                  value={timeRange}
                  onChange={(e) =>
                    onTimeRangeChange(e.target.value as '1month' | '3months' | '6months' | '1year')
                  }
                  label="Time Range"
                >
                  <MenuItem value="1month">Last Month</MenuItem>
                  <MenuItem value="3months">Last 3 Months</MenuItem>
                  <MenuItem value="6months">Last 6 Months</MenuItem>
                  <MenuItem value="1year">Last Year</MenuItem>
                </Select>
              </FormControl>
            </Grid>

            {onPRMetricsRangeChange && prMetricsRange && (
              <Grid item xs={12} sm={6} md={4}>
                <FormControl fullWidth size="small">
                  <InputLabel>PR Metrics Range</InputLabel>
                  <Select
                    value={prMetricsRange}
                    onChange={(e) => onPRMetricsRangeChange(e.target.value as any)}
                    label="PR Metrics Range"
                  >
                    <MenuItem value="14d">Last 14 Days</MenuItem>
                    <MenuItem value="30d">Last 30 Days</MenuItem>
                    <MenuItem value="90d">Last 90 Days</MenuItem>
                    <MenuItem value="all">All Time</MenuItem>
                  </Select>
                </FormControl>
              </Grid>
            )}

            <Grid item xs={12}>
              <Typography variant="caption" color="text.secondary">
                <strong>Tip:</strong> Use quick filters above for common date ranges. Advanced
                filters provide additional granularity for PR metrics and custom time ranges.
              </Typography>
            </Grid>
          </Grid>
        </Box>
      </Collapse>
    </Paper>
  );
};
