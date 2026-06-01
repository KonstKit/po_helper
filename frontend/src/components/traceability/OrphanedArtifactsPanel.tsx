import React, { useEffect, useState, useCallback } from 'react';
import {
  Box,
  Paper,
  Typography,
  Alert,
  Chip,
  Button,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TablePagination,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Stack,
  IconButton,
  Tooltip,
  LinearProgress,
} from '@mui/material';
import type { SelectChangeEvent } from '@mui/material/Select';
import {
  Refresh,
  LinkOff,
  AddLink,
  FilterList,
} from '@mui/icons-material';
import {
  getOrphanedArtifacts,
  OrphanedArtifactsResponse,
} from '../../services/api';
import { getErrorMessage } from '../../utils/errorUtils';

interface OrphanedArtifactsPanelProps {
  projectId?: number;
  onCreateLink?: (artifactId: number) => void;
}

const TYPE_COLORS: Record<string, string> = {
  requirement: '#2196F3',
  jira_issue: '#FF9800',
  confluence_page: '#4CAF50',
  commit: '#9C27B0',
  pr: '#E91E63',
  test_case: '#8BC34A',
  default: '#9E9E9E',
};

const OrphanedArtifactsPanel: React.FC<OrphanedArtifactsPanelProps> = ({
  projectId,
  onCreateLink,
}) => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<OrphanedArtifactsResponse | null>(null);
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(10);
  const [typeFilter, setTypeFilter] = useState<string>('');

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await getOrphanedArtifacts({
        projectId,
        artifactType: typeFilter || undefined,
        limit: rowsPerPage,
        offset: page * rowsPerPage,
      });
      setData(response);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to load orphaned artifacts'));
    } finally {
      setLoading(false);
    }
  }, [projectId, typeFilter, page, rowsPerPage]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handlePageChange = (_: React.MouseEvent<HTMLButtonElement> | null, newPage: number) => {
    setPage(newPage);
  };

  const handleRowsPerPageChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const nextValue = parseInt(event.target.value, 10);
    setRowsPerPage(Number.isFinite(nextValue) ? nextValue : 10);
    setPage(0);
  };

  const selectTypeFilter = (nextType: string) => {
    setTypeFilter(nextType);
    setPage(0); // a new filter changes the result set, so restart pagination
  };

  const handleTypeFilterChange = (event: SelectChangeEvent) => {
    selectTypeFilter(event.target.value);
  };

  const availableTypes = data ? Object.keys(data.by_type) : [];

  // The backend returns a project-wide `total`, but `by_type`/`by_source` are
  // computed only over the rows on the current page. Surface that distinction
  // honestly so a "1266 orphaned" headline isn't shown next to a 10-item
  // breakdown as if they reconciled.
  const pageCount = data?.data.length ?? 0;
  const total = data?.meta.total ?? 0;
  const isPaged = total > pageCount;
  return (
    <Paper sx={{ p: 2 }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" mb={2}>
        <Stack direction="row" alignItems="center" spacing={1}>
          <LinkOff color="warning" />
          <Typography variant="h6">Orphaned Artifacts</Typography>
        </Stack>
        <Button
          size="small"
          startIcon={<Refresh />}
          onClick={fetchData}
          disabled={loading}
        >
          Refresh
        </Button>
      </Stack>

      {/* Stats */}
      {data && (
        <Box mb={2}>
          <Stack direction="row" spacing={2} mb={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <Chip
              icon={<LinkOff />}
              label={
                isPaged
                  ? `Showing ${pageCount} of ${total.toLocaleString()} orphaned`
                  : `${total.toLocaleString()} orphaned`
              }
              color="warning"
              variant="outlined"
            />
            {typeFilter && (
              <Typography variant="caption" color="text.secondary">
                Filtered by type: {typeFilter}
              </Typography>
            )}
          </Stack>

          {/* Breakdown by type. NOTE: the API computes these counts over the
              current page only, not the whole project, so they are labelled as
              such to stay consistent with the total above. */}
          <Typography variant="subtitle2" gutterBottom>
            By Type{isPaged ? ' (this page)' : ''}:
          </Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap mb={2}>
            {Object.entries(data.by_type).length === 0 && (
              <Typography variant="caption" color="text.secondary">
                None on this page
              </Typography>
            )}
            {Object.entries(data.by_type).map(([type, count]) => (
              <Chip
                key={type}
                size="small"
                label={`${type}: ${count}`}
                sx={{
                  bgcolor: `${TYPE_COLORS[type] || TYPE_COLORS.default}20`,
                  borderColor: TYPE_COLORS[type] || TYPE_COLORS.default,
                }}
                variant="outlined"
                onClick={() => selectTypeFilter(type === typeFilter ? '' : type)}
                color={type === typeFilter ? 'primary' : 'default'}
              />
            ))}
          </Stack>

          {/* Breakdown by source (also page-scoped, see note above). */}
          <Typography variant="subtitle2" gutterBottom>
            By Source{isPaged ? ' (this page)' : ''}:
          </Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            {Object.entries(data.by_source).length === 0 && (
              <Typography variant="caption" color="text.secondary">
                None on this page
              </Typography>
            )}
            {Object.entries(data.by_source).map(([source, count]) => (
              <Chip
                key={source}
                size="small"
                label={`${source}: ${count}`}
                variant="outlined"
              />
            ))}
          </Stack>

          {isPaged && (
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
              Breakdown reflects the {pageCount} artifact{pageCount === 1 ? '' : 's'} on this page.
              Use the type filter or pagination below to explore all {total.toLocaleString()}.
            </Typography>
          )}
        </Box>
      )}

      {/* Filter */}
      <Stack direction="row" spacing={2} mb={2}>
        <FormControl size="small" sx={{ minWidth: 150 }}>
          <InputLabel>Filter by Type</InputLabel>
          <Select
            value={typeFilter}
            label="Filter by Type"
            onChange={handleTypeFilterChange}
            startAdornment={<FilterList sx={{ mr: 1 }} />}
          >
            <MenuItem value="">All Types</MenuItem>
            {availableTypes.map((type) => (
              <MenuItem key={type} value={type}>
                {type}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {loading && <LinearProgress sx={{ mb: 2 }} />}

      {/* Table */}
      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Key</TableCell>
              <TableCell>Title</TableCell>
              <TableCell>Type</TableCell>
              <TableCell>Source</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Suggestion</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {!loading && data?.data.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} align="center">
                  <Typography variant="body2" color="text.secondary" py={4}>
                    No orphaned artifacts found
                  </Typography>
                </TableCell>
              </TableRow>
            )}
            {data?.data.map((artifact) => (
              <TableRow key={artifact.id} hover>
                <TableCell>
                  <Typography variant="body2" fontFamily="monospace">
                    {artifact.display_key || artifact.external_id}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Typography
                    variant="body2"
                    sx={{
                      maxWidth: 200,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {artifact.title || '-'}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Chip
                    size="small"
                    label={artifact.type}
                    sx={{
                      bgcolor: `${TYPE_COLORS[artifact.type] || TYPE_COLORS.default}20`,
                      color: TYPE_COLORS[artifact.type] || TYPE_COLORS.default,
                      fontWeight: 500,
                    }}
                  />
                </TableCell>
                <TableCell>
                  <Typography variant="body2" color="text.secondary">
                    {artifact.source}
                  </Typography>
                </TableCell>
                <TableCell>
                  {artifact.status ? (
                    <Chip size="small" label={artifact.status} variant="outlined" />
                  ) : (
                    '-'
                  )}
                </TableCell>
                <TableCell>
                  {artifact.suggestion && (
                    <Typography variant="caption" color="info.main">
                      {artifact.suggestion}
                    </Typography>
                  )}
                </TableCell>
                <TableCell align="right">
                  <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                    {onCreateLink && (
                      <Tooltip title="Create Link">
                        <IconButton
                          size="small"
                          color="primary"
                          onClick={() => onCreateLink(artifact.id)}
                        >
                          <AddLink fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    )}
                  </Stack>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Always render pagination when there is at least one orphan so the
          authoritative total and the visible page always reconcile (the headline
          can read e.g. "Showing 10 of 1266" and the user can page through them). */}
      {data && total > 0 && (
        <TablePagination
          component="div"
          count={total}
          page={page}
          onPageChange={handlePageChange}
          rowsPerPage={rowsPerPage}
          onRowsPerPageChange={handleRowsPerPageChange}
          rowsPerPageOptions={[5, 10, 25, 50]}
        />
      )}
    </Paper>
  );
};

export default OrphanedArtifactsPanel;
