import React, { useState } from 'react';
import {
  Box,
  Chip,
  Stack,
  Collapse,
  Button,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Paper,
  Typography,
  Divider,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import FilterListIcon from '@mui/icons-material/FilterList';
import RestartAltIcon from '@mui/icons-material/RestartAlt';
import {
  CHART_VIEW_OPTIONS,
  DASHBOARD_DEFAULTS,
  DASHBOARD_STORAGE_KEYS,
  DASHBOARD_TEST_IDS,
  DATE_RANGE_OPTIONS,
  parseChartViewOption,
  parseDateRangeOption,
  type ChartViewOption,
  type DateRangeOption,
} from '../pages/dashboard/dashboardContract';

// NOTE (UX review C4): this component used to own a project picker — quick-filter
// chips ("All Projects" / "Active Only" / "Recent"), a selected-project chip and
// a "Project" dropdown. Project selection is now global (see `useSelectedProject`
// and the header selector), so the duplicate picker has been removed and only the
// non-project view filters (date range + chart view) remain here.
interface DashboardFiltersProps {
  dateRange?: string;
  onDateRangeChange?: (range: string) => void;
  chartView?: string;
  onChartViewChange?: (view: string) => void;
}

export const DashboardFilters: React.FC<DashboardFiltersProps> = ({
  dateRange = DASHBOARD_DEFAULTS.dateRange,
  onDateRangeChange,
  chartView = DASHBOARD_DEFAULTS.chartView,
  onChartViewChange,
}) => {
  const [expanded, setExpanded] = useState(false);

  const handleDateRangeSelectChange = (range: string) => {
    const normalized = parseDateRangeOption(range);
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.dateRange, normalized);
    onDateRangeChange?.(normalized);
  };

  const handleChartViewSelectChange = (view: string) => {
    const normalized = parseChartViewOption(view);
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.chartView, normalized);
    onChartViewChange?.(normalized);
  };

  const handleReset = () => {
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.dateRange, DASHBOARD_DEFAULTS.dateRange);
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.chartView, DASHBOARD_DEFAULTS.chartView);

    onDateRangeChange?.(DASHBOARD_DEFAULTS.dateRange);
    onChartViewChange?.(DASHBOARD_DEFAULTS.chartView);
    setExpanded(false);
  };

  const normalizedDateRange: DateRangeOption = parseDateRangeOption(dateRange);
  const normalizedChartView: ChartViewOption = parseChartViewOption(chartView);

  const activeFiltersCount = [
    normalizedDateRange !== DASHBOARD_DEFAULTS.dateRange,
    normalizedChartView !== DASHBOARD_DEFAULTS.chartView,
  ].filter(Boolean).length;

  return (
    <Box mb={3}>
      <Paper sx={{ p: 2 }}>
        <Box display="flex" alignItems="center" justifyContent="space-between">
          <Box display="flex" alignItems="center" gap={1}>
            <FilterListIcon color="action" />
            <Typography variant="subtitle1" fontWeight={500}>
              Filters
            </Typography>
            {activeFiltersCount > 0 && (
              <Chip
                label={`${activeFiltersCount} active`}
                size="small"
                color="primary"
                variant="outlined"
              />
            )}
          </Box>
          <Box display="flex" gap={1}>
            {activeFiltersCount > 0 && (
              <Button size="small" startIcon={<RestartAltIcon />} onClick={handleReset}>
                Reset
              </Button>
            )}
            <Button
              size="small"
              endIcon={expanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
              onClick={() => setExpanded(!expanded)}
            >
              {expanded ? 'Hide' : 'More'} Filters
            </Button>
          </Box>
        </Box>

        <Collapse in={expanded}>
          <Box mt={3}>
            <Divider sx={{ mb: 2 }} />
            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
              Advanced Options
            </Typography>
            <Stack spacing={2} mt={2}>
              {onDateRangeChange && (
                <FormControl fullWidth size="small" data-testid={DASHBOARD_TEST_IDS.filterDateRange}>
                  <InputLabel>Date Range</InputLabel>
                  <Select<DateRangeOption>
                    label="Date Range"
                    value={normalizedDateRange}
                    onChange={(event) => handleDateRangeSelectChange(event.target.value)}
                  >
                    {DATE_RANGE_OPTIONS.map((option) => (
                      <MenuItem key={option} value={option}>
                        {option === '7d'
                          ? 'Last 7 Days'
                          : option === '14d'
                            ? 'Last 14 Days'
                            : option === '30d'
                              ? 'Last 30 Days'
                              : option === '90d'
                                ? 'Last 90 Days'
                                : option === '180d'
                                  ? 'Last 6 Months'
                                  : option === '365d'
                                    ? 'Last Year'
                                    : 'All Time'}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              )}

              {onChartViewChange && (
                <FormControl fullWidth size="small" data-testid={DASHBOARD_TEST_IDS.filterChartView}>
                  <InputLabel>Chart View</InputLabel>
                  <Select<ChartViewOption>
                    label="Chart View"
                    value={normalizedChartView}
                    onChange={(event) => handleChartViewSelectChange(event.target.value)}
                  >
                    {CHART_VIEW_OPTIONS.map((option) => (
                      <MenuItem key={option} value={option}>
                        {option === 'velocity'
                          ? 'Velocity Only'
                          : option === 'burndown'
                            ? 'Burndown Only'
                            : option === 'both'
                              ? 'Velocity + Burndown'
                              : 'Distribution Only'}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              )}
            </Stack>
          </Box>
        </Collapse>
      </Paper>
    </Box>
  );
};
