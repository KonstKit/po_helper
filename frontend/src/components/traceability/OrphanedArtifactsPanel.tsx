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

  const handleTypeFilterChange = (event: SelectChangeEvent) => {
    setTypeFilter(event.target.value);
    setPage(0);
  };

  const availableTypes = data ? Object.keys(data.by_type) : [];
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
          <Stack direction="row" spacing={2} mb={2}>
            <Chip
              icon={<LinkOff />}
              label={`${data.meta.total} orphaned`}
              color="warning"
              variant="outlined"
            />
          </Stack>

          {/* Breakdown by type */}
          <Typography variant="subtitle2" gutterBottom>
            By Type:
          </Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap mb={2}>
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
                onClick={() => setTypeFilter(type === typeFilter ? '' : type)}
                color={type === typeFilter ? 'primary' : 'default'}
              />
            ))}
          </Stack>

          {/* Breakdown by source */}
          <Typography variant="subtitle2" gutterBottom>
            By Source:
          </Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            {Object.entries(data.by_source).map(([source, count]) => (
              <Chip
                key={source}
                size="small"
                label={`${source}: ${count}`}
                variant="outlined"
              />
            ))}
          </Stack>
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

      {data && data.meta.total > rowsPerPage && (
        <TablePagination
          component="div"
          count={data.meta.total}
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
