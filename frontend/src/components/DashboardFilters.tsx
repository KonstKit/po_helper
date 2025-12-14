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

interface Project {
  id: number;
  name: string;
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

const QUICK_PROJECT_FILTERS = ['all', 'active', 'recent'];

export const DashboardFilters: React.FC<DashboardFiltersProps> = ({
  projectId,
  onProjectChange,
  projects,
  dateRange = '30d',
  onDateRangeChange,
  chartView = 'both',
  onChartViewChange,
}) => {
  const [expanded, setExpanded] = useState(false);
  const [quickFilter, setQuickFilter] = useState<string>('recent');

  const handleQuickFilterChange = (filter: string) => {
    setQuickFilter(filter);

    if (filter === 'all' && projects.length > 0) {
      onProjectChange(projects[0].id);
    } else if (filter === 'active') {
      // Find first active project (simplified - use first project)
      const activeProject = projects.find(p => p.id === projectId) || projects[0];
      if (activeProject) {
        onProjectChange(activeProject.id);
      }
    } else if (filter === 'recent') {
      // Use most recently viewed (simplified - use current or first)
      if (!projectId && projects.length > 0) {
        onProjectChange(projects[0].id);
      }
    }
  };

  const handleReset = () => {
    setQuickFilter('recent');
    if (projects.length > 0) {
      onProjectChange(projects[0].id);
    }
    if (onDateRangeChange) onDateRangeChange('30d');
    if (onChartViewChange) onChartViewChange('both');
    setExpanded(false);
  };

  const activeFiltersCount = [
    dateRange !== '30d',
    chartView !== 'both',
  ].filter(Boolean).length;

  return (
    <Box mb={3}>
      {/* Quick Filters - Always Visible */}
      <Paper sx={{ p: 2, mb: expanded ? 0 : 0 }}>
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
              <Button
                size="small"
                startIcon={<RestartAltIcon />}
                onClick={handleReset}
              >
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

        {/* Quick Project Chips */}
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          {QUICK_PROJECT_FILTERS.map((filter) => (
            <Chip
              key={filter}
              label={filter === 'all' ? 'All Projects' : filter === 'active' ? 'Active Only' : 'Recent'}
              onClick={() => handleQuickFilterChange(filter)}
              color={quickFilter === filter ? 'primary' : 'default'}
              variant={quickFilter === filter ? 'filled' : 'outlined'}
              sx={{ textTransform: 'capitalize' }}
            />
          ))}

          {/* Current Project Chip */}
          {projectId && projects.length > 0 && (
            <>
              <Divider orientation="vertical" flexItem sx={{ mx: 1 }} />
              <Chip
                label={projects.find(p => p.id === projectId)?.name || 'Unknown Project'}
                color="success"
                variant="filled"
                onDelete={projects.length > 1 ? () => {
                  const nextProject = projects.find(p => p.id !== projectId);
                  if (nextProject) onProjectChange(nextProject.id);
                } : undefined}
              />
            </>
          )}
        </Stack>

        {/* Advanced Filters - Collapsible */}
        <Collapse in={expanded}>
          <Box mt={3}>
            <Divider sx={{ mb: 2 }} />
            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
              Advanced Options
            </Typography>
            <Stack spacing={2} mt={2}>
              <FormControl fullWidth size="small">
                <InputLabel>Project</InputLabel>
                <Select
                  label="Project"
                  value={projectId || ''}
                  onChange={(e) => onProjectChange(Number(e.target.value))}
                >
                  {projects.map((project) => (
                    <MenuItem key={project.id} value={project.id}>
                      {project.name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>

              {onDateRangeChange && (
                <FormControl fullWidth size="small">
                  <InputLabel>Date Range</InputLabel>
                  <Select
                    label="Date Range"
                    value={dateRange}
                    onChange={(e) => onDateRangeChange(e.target.value)}
                  >
                    <MenuItem value="7d">Last 7 Days</MenuItem>
                    <MenuItem value="14d">Last 14 Days</MenuItem>
                    <MenuItem value="30d">Last 30 Days</MenuItem>
                    <MenuItem value="90d">Last 90 Days</MenuItem>
                    <MenuItem value="180d">Last 6 Months</MenuItem>
                    <MenuItem value="365d">Last Year</MenuItem>
                    <MenuItem value="all">All Time</MenuItem>
                  </Select>
                </FormControl>
              )}

              {onChartViewChange && (
                <FormControl fullWidth size="small">
                  <InputLabel>Chart View</InputLabel>
                  <Select
                    label="Chart View"
                    value={chartView}
                    onChange={(e) => onChartViewChange(e.target.value)}
                  >
                    <MenuItem value="velocity">Velocity Only</MenuItem>
                    <MenuItem value="burndown">Burndown Only</MenuItem>
                    <MenuItem value="both">Both Charts</MenuItem>
                    <MenuItem value="distribution">Distribution Only</MenuItem>
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
