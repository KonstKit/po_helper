/**
 * RTMMatrixViewer - Interactive Requirements Traceability Matrix grid.
 *
 * Displays a sparse matrix of artifacts (rows × columns) with linked cells.
 * Features:
 * - Server-side pagination for large datasets
 * - Cell coloring by link count/confidence
 * - Popover with link details on cell click
 * - Sticky row headers
 * - Horizontal/vertical scroll
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  IconButton,
  Paper,
  Popover,
  Skeleton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import LinkIcon from '@mui/icons-material/Link';
import type {
  RTMMatrixResponse,
  RTMFilters,
  RTMPagination,
  ArtifactSummary,
  RTMCell,
  RTMCellLink,
} from '../../services/api/types';
import { queryRTMMatrix } from '../../services/api/traceability';
import { getErrorMessage } from '../../utils/errorUtils';

interface RTMMatrixViewerProps {
  projectId?: number;
  filters?: RTMFilters;
  onCoverageChange?: (coverage: RTMMatrixResponse['coverage']) => void;
  /** Optional initial pagination from saved config */
  initialPagination?: RTMPagination;
}

const DEFAULT_ROW_LIMIT = 25;
const DEFAULT_COL_LIMIT = 20;

/**
 * Get cell background color based on link count and confidence.
 */
const getCellColor = (cell: RTMCell | undefined): string => {
  if (!cell || !cell.has_link) return 'transparent';

  const avgConfidence = cell.avg_confidence ?? 0;

  // Color gradient based on confidence (green shades)
  if (avgConfidence >= 0.9) return 'rgba(76, 175, 80, 0.35)'; // High confidence
  if (avgConfidence >= 0.7) return 'rgba(76, 175, 80, 0.25)';
  if (avgConfidence >= 0.5) return 'rgba(255, 193, 7, 0.25)'; // Medium - warning
  if (cell.link_count > 0) return 'rgba(255, 152, 0, 0.2)'; // Low confidence - orange

  return 'rgba(76, 175, 80, 0.15)'; // Linked but no confidence data
};

/**
 * Format confidence as percentage.
 */
const formatConfidence = (confidence: number | null | undefined): string => {
  if (confidence == null) return 'N/A';
  return `${Math.round(confidence * 100)}%`;
};

/**
 * Get artifact display label.
 */
const getArtifactLabel = (artifact: ArtifactSummary): string => {
  return artifact.display_key || artifact.external_id || `ID:${artifact.id}`;
};

/**
 * Truncate text with ellipsis.
 */
const truncate = (text: string | null | undefined, maxLen: number): string => {
  if (!text) return '';
  return text.length > maxLen ? `${text.slice(0, maxLen)}...` : text;
};

const RTMMatrixViewer: React.FC<RTMMatrixViewerProps> = ({
  projectId,
  filters,
  onCoverageChange,
  initialPagination,
}) => {
  // Matrix data
  const [matrix, setMatrix] = useState<RTMMatrixResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Pagination state
  const [rowPage, setRowPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(DEFAULT_ROW_LIMIT);
  const [colPage, setColPage] = useState(0);
  const [colsPerPage, setColsPerPage] = useState(DEFAULT_COL_LIMIT);

  // Cell detail popover
  const [popoverAnchor, setPopoverAnchor] = useState<HTMLElement | null>(null);
  const [selectedCell, setSelectedCell] = useState<{
    rowId: number;
    colId: number;
    cell: RTMCell;
    row: ArtifactSummary;
    col: ArtifactSummary;
  } | null>(null);

  // Fetch matrix data
  const fetchMatrix = useCallback(async () => {
    setLoading(true);
    setError(null);

    const pagination: RTMPagination = {
      row_skip: rowPage * rowsPerPage,
      row_limit: rowsPerPage,
      col_skip: colPage * colsPerPage,
      col_limit: colsPerPage,
    };

    const effectiveFilters: RTMFilters = {
      ...filters,
      project_id: projectId,
    };

    try {
      // Request link details so cell popover can show link info
      const data = await queryRTMMatrix(effectiveFilters, pagination, projectId, true);
      setMatrix(data);
      onCoverageChange?.(data.coverage);
    } catch (err) {
      console.error('Failed to load RTM matrix', err);
      setError(getErrorMessage(err, 'Failed to load RTM matrix'));
    } finally {
      setLoading(false);
    }
  }, [projectId, filters, rowPage, rowsPerPage, colPage, colsPerPage, onCoverageChange]);

  // Fetch on mount and when dependencies change
  useEffect(() => {
    fetchMatrix();
  }, [fetchMatrix]);

  // Reset pagination when filters change
  useEffect(() => {
    setRowPage(0);
    setColPage(0);
  }, [filters, projectId]);

  // Apply initial pagination from saved config
  useEffect(() => {
    if (initialPagination) {
      // Guard against division by zero and negative values
      const rowLimit = Math.max(initialPagination.row_limit ?? DEFAULT_ROW_LIMIT, 1);
      const colLimit = Math.max(initialPagination.col_limit ?? DEFAULT_COL_LIMIT, 1);
      const rowSkip = Math.max(initialPagination.row_skip ?? 0, 0);
      const colSkip = Math.max(initialPagination.col_skip ?? 0, 0);
      setRowsPerPage(rowLimit);
      setColsPerPage(colLimit);
      setRowPage(Math.floor(rowSkip / rowLimit));
      setColPage(Math.floor(colSkip / colLimit));
    }
  }, [initialPagination]);

  // Handle row pagination
  const handleRowPageChange = (_: unknown, newPage: number) => {
    setRowPage(newPage);
  };

  const handleRowsPerPageChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setRowsPerPage(parseInt(event.target.value, 10));
    setRowPage(0);
  };

  // Handle column pagination
  const handleColPageChange = (_: unknown, newPage: number) => {
    setColPage(newPage);
  };

  const handleColsPerPageChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setColsPerPage(parseInt(event.target.value, 10));
    setColPage(0);
  };

  // Handle cell click
  const handleCellClick = (
    event: React.MouseEvent<HTMLTableCellElement>,
    rowArtifact: ArtifactSummary,
    colArtifact: ArtifactSummary
  ) => {
    const cellKey = `${rowArtifact.id}`;
    const colKey = `${colArtifact.id}`;
    const cell = matrix?.cells?.[cellKey]?.[colKey];

    if (cell?.has_link) {
      setSelectedCell({
        rowId: rowArtifact.id,
        colId: colArtifact.id,
        cell,
        row: rowArtifact,
        col: colArtifact,
      });
      setPopoverAnchor(event.currentTarget);
    }
  };

  const handlePopoverClose = () => {
    setPopoverAnchor(null);
    setSelectedCell(null);
  };

  // Memoized cell lookup
  const getCellData = useCallback(
    (rowId: number, colId: number): RTMCell | undefined => {
      return matrix?.cells?.[`${rowId}`]?.[`${colId}`];
    },
    [matrix]
  );

  // Loading skeleton
  if (loading && !matrix) {
    return (
      <Box>
        <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
          <CircularProgress size={20} />
          <Typography variant="body2" color="text.secondary">
            Loading matrix...
          </Typography>
        </Stack>
        <Skeleton variant="rectangular" height={400} />
      </Box>
    );
  }

  // Error state
  if (error && !matrix) {
    return (
      <Alert
        severity="error"
        action={
          <IconButton size="small" onClick={fetchMatrix}>
            <RefreshIcon fontSize="small" />
          </IconButton>
        }
      >
        {error}
      </Alert>
    );
  }

  // Empty state
  if (!matrix || (matrix.rows.length === 0 && matrix.columns.length === 0)) {
    return (
      <Box sx={{ textAlign: 'center', py: 4 }}>
        <Typography variant="body1" color="text.secondary" gutterBottom>
          No matrix data available with current filters.
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Try adjusting the filters, syncing source data, or running traceability repair for legacy projects.
        </Typography>
      </Box>
    );
  }

  return (
    <Box>
      {/* Header with refresh and stats */}
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        sx={{ mb: 1 }}
      >
        <Stack direction="row" spacing={2} alignItems="center">
          <Typography variant="subtitle2">
            {matrix.total_rows} rows × {matrix.total_columns} columns
          </Typography>
          {matrix.coverage && (() => {
            const coveragePct = matrix.coverage.row_coverage_pct ?? 0;
            return (
              <Chip
                size="small"
                label={`Coverage: ${coveragePct.toFixed(1)}%`}
                color={coveragePct >= 80 ? 'success' : coveragePct >= 50 ? 'warning' : 'error'}
                variant="outlined"
              />
            );
          })()}
          {loading && <CircularProgress size={16} />}
        </Stack>
        <Tooltip title="Refresh matrix">
          <IconButton size="small" onClick={fetchMatrix} disabled={loading}>
            <RefreshIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Stack>

      {/* Matrix table */}
      <TableContainer
        component={Paper}
        sx={{
          maxHeight: 600,
          overflow: 'auto',
          '& .MuiTableCell-root': {
            padding: '6px 8px',
          },
        }}
      >
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              {/* Corner cell */}
              <TableCell
                sx={{
                  position: 'sticky',
                  left: 0,
                  zIndex: 3,
                  backgroundColor: 'background.paper',
                  minWidth: 180,
                  fontWeight: 'bold',
                }}
              >
                Row / Column →
              </TableCell>
              {/* Column headers */}
              {matrix.columns.map((col) => (
                <TableCell
                  key={col.id}
                  align="center"
                  sx={{
                    minWidth: 100,
                    maxWidth: 140,
                    writingMode: 'vertical-lr',
                    textOrientation: 'mixed',
                    transform: 'rotate(180deg)',
                    height: 140,
                    verticalAlign: 'bottom',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  <Tooltip title={col.title || getArtifactLabel(col)} placement="top">
                    <Box component="span">
                      {truncate(getArtifactLabel(col), 20)}
                    </Box>
                  </Tooltip>
                </TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {matrix.rows.map((row) => (
              <TableRow key={row.id} hover>
                {/* Row header (sticky) */}
                <TableCell
                  component="th"
                  scope="row"
                  sx={{
                    position: 'sticky',
                    left: 0,
                    backgroundColor: 'background.paper',
                    zIndex: 1,
                    borderRight: '1px solid',
                    borderRightColor: 'divider',
                    minWidth: 180,
                    maxWidth: 220,
                  }}
                >
                  <Tooltip title={row.title || getArtifactLabel(row)} placement="right">
                    <Stack direction="row" spacing={0.5} alignItems="center">
                      <Chip
                        size="small"
                        label={row.type}
                        variant="outlined"
                        sx={{ fontSize: '0.7rem' }}
                      />
                      <Typography
                        variant="body2"
                        noWrap
                        sx={{ maxWidth: 120 }}
                      >
                        {getArtifactLabel(row)}
                      </Typography>
                      {row.url && (
                        <IconButton
                          size="small"
                          href={row.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          sx={{ p: 0.25 }}
                        >
                          <OpenInNewIcon sx={{ fontSize: 14 }} />
                        </IconButton>
                      )}
                    </Stack>
                  </Tooltip>
                </TableCell>
                {/* Data cells */}
                {matrix.columns.map((col) => {
                  const cell = getCellData(row.id, col.id);
                  const isLinked = cell?.has_link ?? false;
                  const linkCount = cell?.link_count ?? 0;

                  return (
                    <TableCell
                      key={`${row.id}-${col.id}`}
                      align="center"
                      onClick={(e) => handleCellClick(e, row, col)}
                      sx={{
                        backgroundColor: getCellColor(cell),
                        cursor: isLinked ? 'pointer' : 'default',
                        transition: 'background-color 0.2s',
                        '&:hover': isLinked
                          ? { backgroundColor: 'action.hover' }
                          : undefined,
                        minWidth: 50,
                      }}
                    >
                      {isLinked && (
                        <Tooltip title={`${linkCount} link(s)`}>
                          <Stack direction="row" spacing={0.25} justifyContent="center">
                            <LinkIcon
                              sx={{ fontSize: 14, color: 'success.main' }}
                            />
                            {linkCount > 1 && (
                              <Typography
                                variant="caption"
                                color="success.main"
                                fontWeight="bold"
                              >
                                {linkCount}
                              </Typography>
                            )}
                          </Stack>
                        </Tooltip>
                      )}
                    </TableCell>
                  );
                })}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Row pagination */}
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        justifyContent="space-between"
        alignItems="center"
        sx={{ mt: 1 }}
      >
        <TablePagination
          component="div"
          count={matrix.total_rows}
          page={rowPage}
          onPageChange={handleRowPageChange}
          rowsPerPage={rowsPerPage}
          onRowsPerPageChange={handleRowsPerPageChange}
          rowsPerPageOptions={[10, 25, 50, 100]}
          labelRowsPerPage="Rows:"
          sx={{ '& .MuiTablePagination-toolbar': { minHeight: 40 } }}
        />
        <TablePagination
          component="div"
          count={matrix.total_columns}
          page={colPage}
          onPageChange={handleColPageChange}
          rowsPerPage={colsPerPage}
          onRowsPerPageChange={handleColsPerPageChange}
          rowsPerPageOptions={[10, 20, 50]}
          labelRowsPerPage="Columns:"
          sx={{ '& .MuiTablePagination-toolbar': { minHeight: 40 } }}
        />
      </Stack>

      {/* Cell detail popover */}
      <Popover
        open={Boolean(popoverAnchor)}
        anchorEl={popoverAnchor}
        onClose={handlePopoverClose}
        anchorOrigin={{
          vertical: 'bottom',
          horizontal: 'center',
        }}
        transformOrigin={{
          vertical: 'top',
          horizontal: 'center',
        }}
      >
        {selectedCell && (
          <Box sx={{ p: 2, minWidth: 280, maxWidth: 400 }}>
            <Typography variant="subtitle2" gutterBottom>
              Link Details
            </Typography>

            {/* Row artifact */}
            <Box sx={{ mb: 1.5 }}>
              <Typography variant="caption" color="text.secondary">
                From (Row)
              </Typography>
              <Stack direction="row" spacing={1} alignItems="center">
                <Chip
                  size="small"
                  label={selectedCell.row.type}
                  variant="outlined"
                />
                <Typography variant="body2">
                  {getArtifactLabel(selectedCell.row)}
                </Typography>
              </Stack>
              {selectedCell.row.title && (
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ display: 'block', mt: 0.5 }}
                >
                  {truncate(selectedCell.row.title, 60)}
                </Typography>
              )}
            </Box>

            {/* Column artifact */}
            <Box sx={{ mb: 1.5 }}>
              <Typography variant="caption" color="text.secondary">
                To (Column)
              </Typography>
              <Stack direction="row" spacing={1} alignItems="center">
                <Chip
                  size="small"
                  label={selectedCell.col.type}
                  variant="outlined"
                />
                <Typography variant="body2">
                  {getArtifactLabel(selectedCell.col)}
                </Typography>
              </Stack>
              {selectedCell.col.title && (
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ display: 'block', mt: 0.5 }}
                >
                  {truncate(selectedCell.col.title, 60)}
                </Typography>
              )}
            </Box>

            {/* Links */}
            <Typography variant="caption" color="text.secondary">
              Links ({selectedCell.cell.link_count ?? 0})
            </Typography>
            <Stack spacing={1} sx={{ mt: 0.5 }}>
              {selectedCell.cell.links && selectedCell.cell.links.length > 0 ? (
                selectedCell.cell.links.map((link, idx) => (
                  <Paper key={idx} variant="outlined" sx={{ p: 1 }}>
                    <Stack
                      direction="row"
                      justifyContent="space-between"
                      alignItems="center"
                    >
                      <Chip
                        size="small"
                        label={link.link_type}
                        color="primary"
                        variant="outlined"
                      />
                      <Typography variant="caption">
                        Confidence: {formatConfidence(link.confidence)}
                      </Typography>
                    </Stack>
                  </Paper>
                ))
              ) : selectedCell.cell.link_count > 0 ? (
                <Typography variant="body2" color="text.secondary">
                  {selectedCell.cell.link_count} link(s) via:{' '}
                  {selectedCell.cell.link_types?.join(', ') || 'unknown'}
                </Typography>
              ) : null}
            </Stack>
          </Box>
        )}
      </Popover>
    </Box>
  );
};

export default RTMMatrixViewer;
