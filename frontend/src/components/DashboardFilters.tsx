import React, { useCallback, useEffect, useMemo, useState } from 'react';
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
  DATE_RANGE_OPTIONS,
  QUICK_FILTER_OPTIONS,
  parseChartViewOption,
  parseDateRangeOption,
  parseNumberListFromStorage,
  parseQuickFilterOption,
  type ChartViewOption,
  type DateRangeOption,
  type QuickFilterOption,
} from '../pages/dashboard/dashboardContract';

interface Project {
  id: number;
  name: string;
  status?: string;
  state?: string;
}

interface DashboardFiltersProps {
  projectId: number | null;
  onProjectChange: (id: number) => void;
  projects: Project[];
  dateRange?: string;
  onDateRangeChange?: (range: string) => void;
  chartView?: string;
  onChartViewChange?: (view: string) => void;
}

const isActiveProject = (project: Project): boolean => {
  const status = typeof project.status === 'string' ? project.status.toLowerCase() : '';
  const state = typeof project.state === 'string' ? project.state.toLowerCase() : '';
  return status === 'active' || state === 'active';
};

const sortProjectsByName = (projects: Project[]): Project[] =>
  [...projects].sort((left, right) => left.name.localeCompare(right.name));

const sortProjectsById = (projects: Project[]): Project[] =>
  [...projects].sort((left, right) => left.id - right.id);

const parseLastProjectId = (value: string | null): number | null => {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
};

export const DashboardFilters: React.FC<DashboardFiltersProps> = ({
  projectId,
  onProjectChange,
  projects,
  dateRange = DASHBOARD_DEFAULTS.dateRange,
  onDateRangeChange,
  chartView = DASHBOARD_DEFAULTS.chartView,
  onChartViewChange,
}) => {
  const [expanded, setExpanded] = useState(false);
  const [quickFilter, setQuickFilter] = useState<QuickFilterOption>(() =>
    parseQuickFilterOption(localStorage.getItem(DASHBOARD_STORAGE_KEYS.quickFilter))
  );

  const projectIds = useMemo(() => new Set(projects.map((project) => project.id)), [projects]);
  const sortedById = useMemo(() => sortProjectsById(projects), [projects]);
  const sortedByName = useMemo(() => sortProjectsByName(projects), [projects]);

  const persistRecentProject = useCallback(
    (selectedProjectId: number) => {
      if (!projectIds.has(selectedProjectId)) return;

      localStorage.setItem(DASHBOARD_STORAGE_KEYS.lastProjectId, String(selectedProjectId));

      const recent = parseNumberListFromStorage(
        localStorage.getItem(DASHBOARD_STORAGE_KEYS.recentProjectIds)
      );
      const deduped = [selectedProjectId, ...recent.filter((id) => id !== selectedProjectId)];
      const bounded = deduped.slice(0, DASHBOARD_DEFAULTS.recentProjectsLimit);
      localStorage.setItem(DASHBOARD_STORAGE_KEYS.recentProjectIds, JSON.stringify(bounded));
    },
    [projectIds]
  );

  useEffect(() => {
    if (typeof projectId === 'number') {
      persistRecentProject(projectId);
    }
  }, [projectId, persistRecentProject]);

  useEffect(() => {
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.quickFilter, quickFilter);
  }, [quickFilter]);

  const resolveRecentProjectId = useCallback((): number | null => {
    const recent = parseNumberListFromStorage(localStorage.getItem(DASHBOARD_STORAGE_KEYS.recentProjectIds));
    const recentMatch = recent.find((id) => projectIds.has(id));
    if (recentMatch) return recentMatch;

    const lastProjectId = parseLastProjectId(localStorage.getItem(DASHBOARD_STORAGE_KEYS.lastProjectId));
    if (lastProjectId && projectIds.has(lastProjectId)) return lastProjectId;

    return sortedById[0]?.id ?? null;
  }, [projectIds, sortedById]);

  const resolveActiveProjectId = useCallback((): number | null => {
    const activeProjects = sortedByName.filter(isActiveProject);
    if (activeProjects.length > 0) {
      const activeIds = new Set(activeProjects.map((project) => project.id));
      if (typeof projectId === 'number' && activeIds.has(projectId)) {
        return projectId;
      }
      return activeProjects[0].id;
    }

    const lastProjectId = parseLastProjectId(localStorage.getItem(DASHBOARD_STORAGE_KEYS.lastProjectId));
    if (lastProjectId && projectIds.has(lastProjectId)) return lastProjectId;

    return sortedById[0]?.id ?? null;
  }, [projectId, projectIds, sortedById, sortedByName]);

  const resolveAllProjectsSelection = useCallback((): number | null => {
    if (typeof projectId === 'number' && projectIds.has(projectId)) {
      return projectId;
    }
    return resolveRecentProjectId();
  }, [projectId, projectIds, resolveRecentProjectId]);

  const applyProjectSelection = useCallback(
    (nextProjectId: number | null) => {
      if (nextProjectId === null) return;
      if (!projectIds.has(nextProjectId)) return;
      if (nextProjectId !== projectId) {
        onProjectChange(nextProjectId);
      }
      persistRecentProject(nextProjectId);
    },
    [projectId, projectIds, onProjectChange, persistRecentProject]
  );

  const handleQuickFilterChange = (filter: QuickFilterOption) => {
    setQuickFilter(filter);

    if (filter === 'all') {
      applyProjectSelection(resolveAllProjectsSelection());
      return;
    }
    if (filter === 'active') {
      applyProjectSelection(resolveActiveProjectId());
      return;
    }
    applyProjectSelection(resolveRecentProjectId());
  };

  const handleProjectSelectChange = (selectedProjectId: number) => {
    if (!projectIds.has(selectedProjectId)) return;
    onProjectChange(selectedProjectId);
    persistRecentProject(selectedProjectId);
  };

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
    const defaultQuickFilter = DASHBOARD_DEFAULTS.quickFilter;
    setQuickFilter(defaultQuickFilter);
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.quickFilter, defaultQuickFilter);
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.dateRange, DASHBOARD_DEFAULTS.dateRange);
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.chartView, DASHBOARD_DEFAULTS.chartView);

    onDateRangeChange?.(DASHBOARD_DEFAULTS.dateRange);
    onChartViewChange?.(DASHBOARD_DEFAULTS.chartView);
    applyProjectSelection(resolveRecentProjectId());
    setExpanded(false);
  };

  const normalizedDateRange: DateRangeOption = parseDateRangeOption(dateRange);
  const normalizedChartView: ChartViewOption = parseChartViewOption(chartView);

  const activeFiltersCount = [
    normalizedDateRange !== DASHBOARD_DEFAULTS.dateRange,
    normalizedChartView !== DASHBOARD_DEFAULTS.chartView,
    quickFilter !== DASHBOARD_DEFAULTS.quickFilter,
  ].filter(Boolean).length;

  return (
    <Box mb={3}>
      <Paper sx={{ p: 2 }}>
        <Box display="flex" alignItems="center" justifyContent="space-between" mb={2}>
          <Box display="flex" alignItems="center" gap={1}>
            <FilterListIcon color="action" />
            <Typography variant="subtitle1" fontWeight={500}>
              Quick Filters
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

        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          {QUICK_FILTER_OPTIONS.map((filter) => (
            <Chip
              key={filter}
              label={filter === 'all' ? 'All Projects' : filter === 'active' ? 'Active Only' : 'Recent'}
              onClick={() => handleQuickFilterChange(filter)}
              color={quickFilter === filter ? 'primary' : 'default'}
              variant={quickFilter === filter ? 'filled' : 'outlined'}
              sx={{ textTransform: 'capitalize' }}
            />
          ))}

          {projectId && projects.length > 0 && (
            <>
              <Divider orientation="vertical" flexItem sx={{ mx: 1 }} />
              <Chip
                label={projects.find((project) => project.id === projectId)?.name || 'Unknown Project'}
                color="success"
                variant="filled"
                onDelete={
                  projects.length > 1
                    ? () => {
                        const nextProject = sortedById.find((project) => project.id !== projectId);
                        if (nextProject) {
                          handleProjectSelectChange(nextProject.id);
                        }
                      }
                    : undefined
                }
              />
            </>
          )}
        </Stack>

        <Collapse in={expanded}>
          <Box mt={3}>
            <Divider sx={{ mb: 2 }} />
            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
              Advanced Options
            </Typography>
            <Stack spacing={2} mt={2}>
              <FormControl fullWidth size="small" data-testid="dashboard-filter-project">
                <InputLabel>Project</InputLabel>
                <Select<number | ''>
                  label="Project"
                  value={projectId || ''}
                  onChange={(event) => handleProjectSelectChange(Number(event.target.value))}
                >
                  {sortedById.map((project) => (
                    <MenuItem key={project.id} value={project.id}>
                      {project.name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>

              {onDateRangeChange && (
                <FormControl fullWidth size="small" data-testid="dashboard-filter-date-range">
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
                <FormControl fullWidth size="small" data-testid="dashboard-filter-chart-view">
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
