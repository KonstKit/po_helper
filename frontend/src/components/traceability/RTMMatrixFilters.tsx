/**
 * RTMMatrixFilters - Filter controls for the RTM Matrix.
 *
 * Provides UI for filtering matrix by:
 * - Row/column artifact types
 * - Row/column statuses
 * - Link types
 * - Minimum confidence threshold
 * - Search query
 * - Link direction
 */
import React, { useCallback, useState } from 'react';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  Chip,
  FormControl,
  FormControlLabel,
  IconButton,
  InputAdornment,
  InputLabel,
  MenuItem,
  OutlinedInput,
  Select,
  Slider,
  Stack,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import type { SelectChangeEvent } from '@mui/material/Select';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import FilterListIcon from '@mui/icons-material/FilterList';
import ClearIcon from '@mui/icons-material/Clear';
import SearchIcon from '@mui/icons-material/Search';
import type { RTMFilters } from '../../services/api/types';

interface RTMMatrixFiltersProps {
  filters: RTMFilters;
  onChange: (filters: RTMFilters) => void;
  onReset: () => void;
  disabled?: boolean;
}

// Common artifact types in the system
const ARTIFACT_TYPES = [
  { value: 'jira_issue', label: 'Jira Issues' },
  { value: 'commit', label: 'Commits' },
  { value: 'confluence_page', label: 'Confluence Pages' },
  { value: 'testrail_case', label: 'TestRail Cases' },
  { value: 'pull_request', label: 'Pull Requests' },
  { value: 'manual', label: 'Manual Artifacts' },
];

// Common link types
const LINK_TYPES = [
  { value: 'implements', label: 'Implements' },
  { value: 'tests', label: 'Tests' },
  { value: 'deploys', label: 'Deploys' },
  { value: 'derives_from', label: 'Derives From' },
  { value: 'relates_to', label: 'Relates To' },
  { value: 'references', label: 'References' },
  { value: 'mentions', label: 'Mentions' },
  { value: 'child_of', label: 'Child Of' },
  { value: 'parent_of', label: 'Parent Of' },
];

// Common statuses
const STATUS_OPTIONS = [
  { value: 'Open', label: 'Open' },
  { value: 'In Progress', label: 'In Progress' },
  { value: 'Done', label: 'Done' },
  { value: 'Closed', label: 'Closed' },
  { value: 'To Do', label: 'To Do' },
  { value: 'Ready for QA', label: 'Ready for QA' },
];

// Link direction options
const DIRECTION_OPTIONS = [
  { value: 'both', label: 'Both Directions' },
  { value: 'row_to_col', label: 'Row → Column' },
  { value: 'col_to_row', label: 'Column → Row' },
];

const RTMMatrixFilters: React.FC<RTMMatrixFiltersProps> = ({
  filters,
  onChange,
  onReset,
  disabled = false,
}) => {
  const [expanded, setExpanded] = useState(true);

  // Count active filters
  const activeFilterCount = [
    filters.row_types?.length ?? 0,
    filters.col_types?.length ?? 0,
    filters.row_statuses?.length ?? 0,
    filters.col_statuses?.length ?? 0,
    filters.link_types?.length ?? 0,
    filters.min_confidence !== undefined ? 1 : 0,
    filters.search_query ? 1 : 0,
    filters.direction && filters.direction !== 'both' ? 1 : 0,
    filters.include_orphans ? 1 : 0,
  ].reduce((sum, count) => sum + (count > 0 ? 1 : 0), 0);

  // Handle multi-select changes
  const handleMultiSelect = useCallback(
    (field: keyof RTMFilters) => (event: SelectChangeEvent<string[]>) => {
      const value = event.target.value;
      onChange({
        ...filters,
        [field]: typeof value === 'string' ? value.split(',') : value,
      });
    },
    [filters, onChange]
  );

  // Handle single value changes
  const handleChange = useCallback(
    <K extends keyof RTMFilters>(field: K, value: RTMFilters[K]) => {
      onChange({
        ...filters,
        [field]: value,
      });
    },
    [filters, onChange]
  );

  // Handle search query with debounce-like behavior
  const handleSearchChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      handleChange('search_query', event.target.value || undefined);
    },
    [handleChange]
  );

  // Handle confidence slider
  const handleConfidenceChange = useCallback(
    (_: Event, value: number | number[]) => {
      const confidence = Array.isArray(value) ? value[0] : value;
      handleChange('min_confidence', confidence > 0 ? confidence : undefined);
    },
    [handleChange]
  );

  // Handle direction change
  const handleDirectionChange = useCallback(
    (event: SelectChangeEvent<string>) => {
      const value = event.target.value as RTMFilters['direction'];
      handleChange('direction', value === 'both' ? undefined : value);
    },
    [handleChange]
  );

  return (
    <Accordion
      expanded={expanded}
      onChange={(_, isExpanded) => setExpanded(isExpanded)}
      sx={{ mb: 2 }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Stack direction="row" spacing={1} alignItems="center">
          <FilterListIcon fontSize="small" />
          <Typography variant="subtitle2">Filters</Typography>
          {activeFilterCount > 0 && (
            <Chip
              size="small"
              label={activeFilterCount}
              color="primary"
              sx={{ height: 20, fontSize: '0.75rem' }}
            />
          )}
        </Stack>
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={2}>
          {/* Search query */}
          <TextField
            fullWidth
            size="small"
            label="Search"
            placeholder="Search artifacts by title or ID..."
            value={filters.search_query || ''}
            onChange={handleSearchChange}
            disabled={disabled}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" />
                </InputAdornment>
              ),
              endAdornment: filters.search_query ? (
                <InputAdornment position="end">
                  <IconButton
                    size="small"
                    onClick={() => handleChange('search_query', undefined)}
                  >
                    <ClearIcon fontSize="small" />
                  </IconButton>
                </InputAdornment>
              ) : null,
            }}
          />

          {/* Row/Column type filters */}
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <FormControl fullWidth size="small" disabled={disabled}>
              <InputLabel>Row Types</InputLabel>
              <Select
                multiple
                value={filters.row_types || []}
                onChange={handleMultiSelect('row_types')}
                input={<OutlinedInput label="Row Types" />}
                renderValue={(selected) => (
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                    {selected.map((value) => (
                      <Chip
                        key={value}
                        label={
                          ARTIFACT_TYPES.find((t) => t.value === value)?.label || value
                        }
                        size="small"
                      />
                    ))}
                  </Box>
                )}
              >
                {ARTIFACT_TYPES.map((type) => (
                  <MenuItem key={type.value} value={type.value}>
                    {type.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            <FormControl fullWidth size="small" disabled={disabled}>
              <InputLabel>Column Types</InputLabel>
              <Select
                multiple
                value={filters.col_types || []}
                onChange={handleMultiSelect('col_types')}
                input={<OutlinedInput label="Column Types" />}
                renderValue={(selected) => (
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                    {selected.map((value) => (
                      <Chip
                        key={value}
                        label={
                          ARTIFACT_TYPES.find((t) => t.value === value)?.label || value
                        }
                        size="small"
                      />
                    ))}
                  </Box>
                )}
              >
                {ARTIFACT_TYPES.map((type) => (
                  <MenuItem key={type.value} value={type.value}>
                    {type.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Stack>

          {/* Status filters */}
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <FormControl fullWidth size="small" disabled={disabled}>
              <InputLabel>Row Statuses</InputLabel>
              <Select
                multiple
                value={filters.row_statuses || []}
                onChange={handleMultiSelect('row_statuses')}
                input={<OutlinedInput label="Row Statuses" />}
                renderValue={(selected) => (
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                    {selected.map((value) => (
                      <Chip key={value} label={value} size="small" />
                    ))}
                  </Box>
                )}
              >
                {STATUS_OPTIONS.map((status) => (
                  <MenuItem key={status.value} value={status.value}>
                    {status.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            <FormControl fullWidth size="small" disabled={disabled}>
              <InputLabel>Column Statuses</InputLabel>
              <Select
                multiple
                value={filters.col_statuses || []}
                onChange={handleMultiSelect('col_statuses')}
                input={<OutlinedInput label="Column Statuses" />}
                renderValue={(selected) => (
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                    {selected.map((value) => (
                      <Chip key={value} label={value} size="small" />
                    ))}
                  </Box>
                )}
              >
                {STATUS_OPTIONS.map((status) => (
                  <MenuItem key={status.value} value={status.value}>
                    {status.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Stack>

          {/* Link type and direction */}
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <FormControl fullWidth size="small" disabled={disabled}>
              <InputLabel>Link Types</InputLabel>
              <Select
                multiple
                value={filters.link_types || []}
                onChange={handleMultiSelect('link_types')}
                input={<OutlinedInput label="Link Types" />}
                renderValue={(selected) => (
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                    {selected.map((value) => (
                      <Chip
                        key={value}
                        label={
                          LINK_TYPES.find((t) => t.value === value)?.label || value
                        }
                        size="small"
                      />
                    ))}
                  </Box>
                )}
              >
                {LINK_TYPES.map((type) => (
                  <MenuItem key={type.value} value={type.value}>
                    {type.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            <FormControl fullWidth size="small" disabled={disabled}>
              <InputLabel>Link Direction</InputLabel>
              <Select
                value={filters.direction || 'both'}
                onChange={handleDirectionChange}
                label="Link Direction"
              >
                {DIRECTION_OPTIONS.map((opt) => (
                  <MenuItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Stack>

          {/* Confidence slider */}
          <Box sx={{ px: 1 }}>
            <Typography variant="caption" color="text.secondary" gutterBottom>
              Minimum Confidence: {((filters.min_confidence ?? 0) * 100).toFixed(0)}%
            </Typography>
            <Slider
              value={filters.min_confidence ?? 0}
              onChange={handleConfidenceChange}
              min={0}
              max={1}
              step={0.05}
              marks={[
                { value: 0, label: '0%' },
                { value: 0.5, label: '50%' },
                { value: 1, label: '100%' },
              ]}
              valueLabelDisplay="auto"
              valueLabelFormat={(v) => `${(v * 100).toFixed(0)}%`}
              disabled={disabled}
              size="small"
            />
          </Box>

          {/* Include orphans toggle */}
          <FormControlLabel
            control={
              <Switch
                checked={filters.include_orphans ?? false}
                onChange={(e) => handleChange('include_orphans', e.target.checked)}
                disabled={disabled}
                size="small"
              />
            }
            label={
              <Typography variant="body2">
                Include orphaned artifacts (no links)
              </Typography>
            }
          />

          {/* Action buttons */}
          <Stack direction="row" spacing={1} justifyContent="flex-end">
            <Tooltip title="Clear all filters">
              <Button
                variant="outlined"
                size="small"
                onClick={onReset}
                disabled={disabled || activeFilterCount === 0}
                startIcon={<ClearIcon />}
              >
                Reset
              </Button>
            </Tooltip>
          </Stack>
        </Stack>
      </AccordionDetails>
    </Accordion>
  );
};

export default RTMMatrixFilters;
