import React from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Chip,
  CircularProgress,
  Grid,
  LinearProgress,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import EmptyState from '../EmptyState';
import type { Project, TraceabilityMatrixSummary } from '../../services/api';
import { TypeRow, coverageChipColor } from './traceabilityUtils';

interface CoverageSnapshotProps {
  projectId: number | 'all';
  matrix: TraceabilityMatrixSummary | null;
  matrixLoading: boolean;
  matrixHasData: boolean;
  coveragePct: number;
  linkedCount: number;
  unlinkedCount: number;
  typeRows: TypeRow[];
  showEmptyState: boolean;
  showSyncSetupState: boolean;
  selectedProject?: Project;
  onRefresh: () => void;
  onBackfill: () => void;
}

/**
 * Coverage snapshot card (totals, linked-coverage bar, artifact
 * distribution table, empty-state guidance) extracted from
 * pages/Traceability.tsx.
 */
const CoverageSnapshot: React.FC<CoverageSnapshotProps> = ({
  projectId,
  matrix,
  matrixLoading,
  matrixHasData,
  coveragePct,
  linkedCount,
  unlinkedCount,
  typeRows,
  showEmptyState,
  showSyncSetupState,
  selectedProject,
  onRefresh,
  onBackfill,
}) => {
  const navigate = useNavigate();

  return (
  <Paper sx={{ p: 2, height: '100%', display: 'flex', flexDirection: 'column', gap: 2 }}>
    <Box>
      <Box display="flex" alignItems="center" justifyContent="space-between" gap={2}>
        <Typography variant="h6">Coverage snapshot</Typography>
        {matrixLoading && <LinearProgress sx={{ width: 120 }} />}
      </Box>
      {matrixHasData && !matrixLoading && (
        <Grid container spacing={2} sx={{ mt: 1 }} alignItems="center">
          <Grid item xs={12} sm={4}>
            <Typography variant="subtitle2" color="text.secondary">
              Total artifacts
            </Typography>
            <Typography variant="h3">{matrix?.total.toLocaleString()}</Typography>
          </Grid>
          <Grid item xs={12} sm={8}>
            <Typography variant="subtitle2" color="text.secondary">
              Linked coverage
            </Typography>
            <LinearProgress
              variant="determinate"
              value={Math.min(Math.max(coveragePct, 0), 100)}
              sx={{ height: 10, borderRadius: 5, mt: 1 }}
            />
            <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
              <Chip label={`${linkedCount} linked`} color="success" variant="outlined" />
              <Chip label={`${unlinkedCount} missing`} color={unlinkedCount > 0 ? 'warning' : 'default'} variant="outlined" />
              <Chip label={`${coveragePct.toFixed(1)}% coverage`} color="primary" variant="outlined" />
            </Stack>
          </Grid>
        </Grid>
      )}
      {matrixLoading && !matrixHasData && (
        <Box display="flex" justifyContent="center" alignItems="center" sx={{ minHeight: 160 }}>
          <CircularProgress />
        </Box>
      )}
      {showEmptyState && (
        <Box sx={{ mt: 2 }}>
          <EmptyState
            icon={<AccountTreeIcon sx={{ fontSize: 60 }} />}
            title={
              typeof projectId !== 'number'
                ? 'Select a Project'
                : showSyncSetupState
                  ? 'Sync Source Data First'
                  : 'Repair Traceability Artifacts'
            }
            description={
              <Box>
                <Typography variant="body1" paragraph>
                  {typeof projectId !== 'number'
                    ? 'Choose a single project to inspect sync signals and repair traceability artifacts.'
                    : showSyncSetupState
                      ? 'This project does not show any recent Jira or Confluence ingest signal yet.'
                      : 'Source data exists for this project, but traceability artifacts are still missing or incomplete.'}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {typeof projectId !== 'number'
                    ? 'Project-scoped sync and repair actions are only available after you narrow the scope.'
                    : showSyncSetupState
                      ? 'Start with source sync so tasks and pages are imported automatically. Repair is only needed for legacy data or incomplete ingestion runs.'
                      : 'Run repair to reconcile Jira tasks, Confluence pages, and optional Git data into the artifact graph, then refresh coverage.'}
                </Typography>
              </Box>
            }
            primaryAction={{
              label:
                typeof projectId !== 'number'
                  ? 'Open Projects'
                  : showSyncSetupState
                    ? 'Open Project Sync'
                    : 'Run Traceability Repair',
              onClick:
                typeof projectId !== 'number'
                  ? () => navigate('/projects')
                  : showSyncSetupState
                    ? () =>
                        navigate(selectedProject ? `/projects/${selectedProject.id}` : '/projects')
                    : onBackfill,
            }}
            secondaryAction={
              typeof projectId !== 'number'
                ? undefined
                : showSyncSetupState
                  ? {
                      label: 'Open Knowledge Sync',
                      onClick: () => navigate('/knowledge'),
                      variant: 'outlined',
                    }
                  : {
                      label: 'Refresh Snapshot',
                      onClick: onRefresh,
                      variant: 'outlined',
                    }
            }
            benefits={[
              'Jira and Confluence ingestion can populate artifacts automatically',
              'Confluence → Jira ticket references',
              'Git commits → Pull requests → Tests',
              'Repair reconciles legacy or failed traceability runs',
            ]}
            setupSteps={[
              'Run project or knowledge sync if source data is missing',
              'Run traceability repair when artifacts need reconciliation',
              'Refresh the matrix and flow explorer after ingestion completes',
            ]}
          />
        </Box>
      )}
    </Box>

    <Box>
      <Typography variant="subtitle1" gutterBottom>
        Artifact distribution
      </Typography>
      <TableContainer sx={{ maxHeight: 320 }}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              <TableCell>Type</TableCell>
              <TableCell align="right">Artifacts</TableCell>
              <TableCell align="right">Linked</TableCell>
              <TableCell align="right">Unlinked</TableCell>
              <TableCell align="right">Coverage</TableCell>
              <TableCell>Link coverage</TableCell>
              <TableCell align="right">Avg links</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {typeRows.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} align="center">
                  <Typography variant="body2" color="text.secondary">
                    No artifacts yet. Start with source sync, then use traceability repair only if this project predates automatic artifact ingestion.
                  </Typography>
                </TableCell>
              </TableRow>
            )}
            {typeRows.map(row => (
              <TableRow
                key={row.type}
                hover
                sx={row.hasCoverageGap ? { backgroundColor: 'rgba(255, 193, 7, 0.08)' } : undefined}
              >
                <TableCell>
                  <Stack direction="row" spacing={0.5} alignItems="center">
                    {row.hasCoverageGap && (
                      <Tooltip
                        title={`${row.coreMissingCount} core link type${row.coreMissingCount > 1 ? 's' : ''} missing`}
                      >
                        <WarningAmberIcon fontSize="small" color="warning" />
                      </Tooltip>
                    )}
                    <Typography variant="body2" sx={{ textTransform: 'capitalize' }}>
                      {row.type.replace(/_/g, ' ')}
                    </Typography>
                  </Stack>
                </TableCell>
                <TableCell align="right">
                  <Stack spacing={0.5} alignItems="flex-end">
                    <Typography variant="body2">{row.total.toLocaleString()}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {row.sharePct.toFixed(1)}%
                    </Typography>
                  </Stack>
                </TableCell>
                <TableCell align="right">{row.linked.toLocaleString()}</TableCell>
                <TableCell align="right">
                  <Typography color={row.unlinked > 0 ? 'warning.main' : 'text.secondary'}>
                    {row.unlinked.toLocaleString()}
                  </Typography>
                </TableCell>
                <TableCell align="right">
                  <Tooltip title={`Total links: ${row.totalLinks ?? 0}`} placement="top">
                    <Chip
                      size="small"
                      label={`${row.coveragePct.toFixed(1)}%`}
                      color={coverageChipColor(row.coveragePct)}
                      variant="outlined"
                    />
                  </Tooltip>
                </TableCell>
                <TableCell>
                  {row.linkTypes.length === 0 ? (
                    <Typography variant="caption" color="text.secondary">
                      No outgoing links
                    </Typography>
                  ) : (
                    <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                      {row.linkTypes.map(linkType => {
                        const coveragePercent = Math.round(linkType.coverageRatio * 100);
                        const missing = linkType.totalLinks === 0;
                        const partiallyCovered = !missing && linkType.isCore && coveragePercent < 75;
                        let chipColor: 'default' | 'primary' | 'secondary' | 'success' | 'error' | 'info' | 'warning' = 'default';
                        if (missing) {
                          chipColor = 'warning';
                        } else if (linkType.isCore && coveragePercent >= 90) {
                          chipColor = 'success';
                        } else if (partiallyCovered) {
                          chipColor = 'info';
                        }
                        const label = `${linkType.key.replace(/_/g, ' ')}: ${linkType.totalLinks}`;
                        const tooltip = `${linkType.totalLinks} ${linkType.totalLinks === 1 ? 'link' : 'links'} - ${linkType.artifactCount}/${row.total} artifacts`;
                        return (
                          <Tooltip key={`${row.type}-${linkType.key}`} title={tooltip}>
                            <Chip size="small" label={label} color={chipColor} variant="outlined" />
                          </Tooltip>
                        );
                      })}
                    </Stack>
                  )}
                </TableCell>
                <TableCell align="right">
                  {row.avgLinks !== null ? row.avgLinks.toFixed(2) : 'N/A'}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  </Paper>
  );
};

export default CoverageSnapshot;
