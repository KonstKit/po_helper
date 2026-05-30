import React, { useState, useCallback } from 'react';
import {
  Box,
  Paper,
  Typography,
  CircularProgress,
  Alert,
  Button,
  Stack,
  Chip,
  Card,
  CardContent,
  LinearProgress,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Switch,
  FormControlLabel,
  Tooltip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  Slider,
  FormGroup,
  IconButton,
  type AlertColor,
} from '@mui/material';
import {
  ExpandMore,
  CheckCircle,
  Warning,
  Error as ErrorIcon,
  LinkOff,
  Loop,
  ContentCopy,
  BugReport,
  AccessTime,
  Build,
  PlayArrow,
  Info,
  OpenInNew,
} from '@mui/icons-material';
import {
  runConsistencyCheck,
  fixConsistencyIssues,
  getDetailedCycles,
  ConsistencyCheckResponse,
  ConsistencyIssue,
  ConsistencyCheckRecommendation,
  FixConsistencyResult,
  DetailedCyclesResponse,
} from '../../services/api';
import { getErrorMessage } from '../../utils/errorUtils';

interface DataConsistencyPanelProps {
  projectId?: number;
  onArtifactClick?: (artifactId: number) => void;
}

const STATUS_COLORS: Record<string, string> = {
  healthy: '#4CAF50',
  warning: '#FF9800',
  critical: '#F44336',
};

const STATUS_ICONS: Record<string, React.ReactNode> = {
  healthy: <CheckCircle color="success" />,
  warning: <Warning color="warning" />,
  critical: <ErrorIcon color="error" />,
};

const PRIORITY_COLORS: Record<string, AlertColor> = {
  high: 'error',
  medium: 'warning',
  low: 'info',
};

const DataConsistencyPanel: React.FC<DataConsistencyPanelProps> = ({
  projectId,
  onArtifactClick,
}) => {
  const [loading, setLoading] = useState(false);
  const [checkResult, setCheckResult] = useState<ConsistencyCheckResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fixLoading, setFixLoading] = useState(false);
  const [fixResult, setFixResult] = useState<FixConsistencyResult | null>(null);
  const [detailedCycles, setDetailedCycles] = useState<DetailedCyclesResponse | null>(null);
  const [cyclesLoading, setCyclesLoading] = useState(false);
  const [confirmDialog, setConfirmDialog] = useState(false);

  // Check options
  const [checkOrphans, setCheckOrphans] = useState(true);
  const [checkCycles, setCheckCycles] = useState(true);
  const [checkDuplicates, setCheckDuplicates] = useState(true);
  const [checkBrokenRefs, setCheckBrokenRefs] = useState(true);
  const [checkStale, setCheckStale] = useState(true);
  const [staleDays, setStaleDays] = useState(90);

  const handleStaleDaysChange = (_: Event, value: number | number[]) => {
    if (!Array.isArray(value)) {
      setStaleDays(value);
    }
  };

  const runCheck = useCallback(async () => {
    setLoading(true);
    setError(null);
    setFixResult(null);
    setDetailedCycles(null);
    try {
      const result = await runConsistencyCheck({
        projectId,
        checkOrphans,
        checkCycles,
        checkDuplicates,
        checkBrokenRefs,
        checkStale,
        staleDays,
      });
      setCheckResult(result);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to run consistency check'));
    } finally {
      setLoading(false);
    }
  }, [projectId, checkOrphans, checkCycles, checkDuplicates, checkBrokenRefs, checkStale, staleDays]);

  const handleFix = async (dryRun: boolean) => {
    setFixLoading(true);
    try {
      const result = await fixConsistencyIssues({
        projectId,
        fixBrokenRefs: true,
        fixDuplicates: true,
        dryRun,
      });
      setFixResult(result);
      if (!dryRun) {
        // Re-run check after applying fixes
        await runCheck();
      }
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to fix consistency issues'));
    } finally {
      setFixLoading(false);
      setConfirmDialog(false);
    }
  };

  const loadDetailedCycles = async () => {
    setCyclesLoading(true);
    try {
      const result = await getDetailedCycles({ projectId });
      setDetailedCycles(result);
    } catch (err: unknown) {
      console.error('Failed to load detailed cycles:', err);
    } finally {
      setCyclesLoading(false);
    }
  };

  const getIssueCount = (issues: ConsistencyCheckResponse['issues']) => {
    return (
      (issues.orphan_count || 0) +
      (issues.cycle_count || 0) +
      (issues.broken_ref_count || 0) +
      (issues.duplicate_count || 0) +
      (issues.stale_count || 0)
    );
  };

  const renderHealthScore = () => {
    if (!checkResult) return null;

    const { health_score, status } = checkResult;
    const color = STATUS_COLORS[status] || STATUS_COLORS.warning;

    return (
      <Card
        sx={{
          mb: 3,
          bgcolor: `${color}15`,
          borderLeft: `4px solid ${color}`,
        }}
      >
        <CardContent>
          <Stack direction="row" spacing={3} alignItems="center">
            <Box
              sx={{
                width: 80,
                height: 80,
                borderRadius: '50%',
                bgcolor: `${color}20`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Typography variant="h4" sx={{ color, fontWeight: 700 }}>
                {Math.round(health_score * 100)}%
              </Typography>
            </Box>
            <Box flex={1}>
              <Stack direction="row" alignItems="center" spacing={1} mb={1}>
                {STATUS_ICONS[status]}
                <Typography variant="h5" fontWeight={600}>
                  Data Integrity: {status.charAt(0).toUpperCase() + status.slice(1)}
                </Typography>
              </Stack>
              <Typography variant="body2" color="text.secondary">
                {getIssueCount(checkResult.issues)} issues found
                {checkResult.project_filtered ? ' (filtered by project)' : ' (all projects)'}
                {' • '}Checked at {new Date(checkResult.checked_at).toLocaleString()}
              </Typography>
            </Box>
            <Box sx={{ width: 200 }}>
              <Typography variant="caption" color="text.secondary">
                Health Score
              </Typography>
              <LinearProgress
                variant="determinate"
                value={health_score * 100}
                sx={{
                  height: 12,
                  borderRadius: 1,
                  bgcolor: '#e0e0e0',
                  '& .MuiLinearProgress-bar': { bgcolor: color },
                }}
              />
            </Box>
          </Stack>
        </CardContent>
      </Card>
    );
  };

  const renderIssueSection = (
    title: string,
    icon: React.ReactNode,
    count: number | undefined,
    items: ConsistencyIssue[] | undefined,
    renderItem: (item: ConsistencyIssue, idx: number) => React.ReactNode
  ) => {
    if (!count) return null;

    return (
      <Accordion defaultExpanded={count < 10}>
        <AccordionSummary expandIcon={<ExpandMore />}>
          <Stack direction="row" alignItems="center" spacing={2}>
            {icon}
            <Typography fontWeight={500}>{title}</Typography>
            <Chip
              size="small"
              label={count}
              color={count > 10 ? 'error' : count > 0 ? 'warning' : 'default'}
            />
          </Stack>
        </AccordionSummary>
        <AccordionDetails>
          {items && items.length > 0 ? (
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>ID</TableCell>
                    <TableCell>Type</TableCell>
                    <TableCell>Details</TableCell>
                    <TableCell>Actions</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {items.slice(0, 50).map((item, idx) => renderItem(item, idx))}
                </TableBody>
              </Table>
              {items.length > 50 && (
                <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                  Showing 50 of {items.length} issues
                </Typography>
              )}
            </TableContainer>
          ) : (
            <Typography variant="body2" color="text.secondary">
              {count} issues found but details not expanded
            </Typography>
          )}
        </AccordionDetails>
      </Accordion>
    );
  };

  const renderOrphanRow = (item: ConsistencyIssue, idx: number) => (
    <TableRow key={idx}>
      <TableCell>
        <Tooltip title="Click to view artifact">
          <Button
            size="small"
            onClick={() => {
              if (typeof item.artifact_id === 'number') {
                onArtifactClick?.(item.artifact_id);
              }
            }}
          >
            #{item.artifact_id ?? '-'}
          </Button>
        </Tooltip>
      </TableCell>
      <TableCell>
        <Chip size="small" label={item.type || 'unknown'} variant="outlined" />
      </TableCell>
      <TableCell>
        <Typography variant="body2" noWrap sx={{ maxWidth: 300 }}>
          {item.title || item.display_key || '-'}
        </Typography>
      </TableCell>
      <TableCell>
        <IconButton
          size="small"
          onClick={() => {
            if (typeof item.artifact_id === 'number') {
              onArtifactClick?.(item.artifact_id);
            }
          }}
        >
          <OpenInNew fontSize="small" />
        </IconButton>
      </TableCell>
    </TableRow>
  );

  const renderCycleRow = (item: ConsistencyIssue, idx: number) => (
    <TableRow key={idx}>
      <TableCell>Cycle #{idx + 1}</TableCell>
      <TableCell>
        <Chip size="small" label={item.link_type} color="primary" variant="outlined" />
      </TableCell>
      <TableCell>
        <Stack direction="row" spacing={0.5} alignItems="center" flexWrap="wrap">
          {item.cycle_path?.map((id: number, i: number) => (
            <React.Fragment key={id}>
              <Chip
                size="small"
                label={`#${id}`}
                onClick={() => onArtifactClick?.(id)}
                sx={{ cursor: 'pointer' }}
              />
              {i < (item.cycle_path ?? []).length - 1 && <Typography variant="body2">→</Typography>}
            </React.Fragment>
          ))}
          <Typography variant="body2">→ #{item.cycle_path?.[0]}</Typography>
        </Stack>
      </TableCell>
      <TableCell>
        <Typography variant="caption">Length: {item.cycle_length}</Typography>
      </TableCell>
    </TableRow>
  );

  const renderBrokenRefRow = (item: ConsistencyIssue, idx: number) => (
    <TableRow key={idx}>
      <TableCell>
        <Typography variant="body2">Link #{item.link_id}</Typography>
      </TableCell>
      <TableCell>
        <Chip size="small" label={item.link_type} variant="outlined" />
      </TableCell>
      <TableCell>
        <Typography variant="body2">
          From #{item.from_artifact_id} → To #{item.to_artifact_id}
        </Typography>
      </TableCell>
      <TableCell>
        <Chip size="small" label="Orphan ref" color="error" />
      </TableCell>
    </TableRow>
  );

  const renderDuplicateRow = (item: ConsistencyIssue, idx: number) => (
    <TableRow key={idx}>
      <TableCell>
        <Typography variant="body2">#{item.from_artifact_id} → #{item.to_artifact_id}</Typography>
      </TableCell>
      <TableCell>
        <Chip size="small" label={item.link_type} variant="outlined" />
      </TableCell>
      <TableCell>
        <Chip size="small" label={`${item.count} duplicates`} color="warning" />
      </TableCell>
      <TableCell>-</TableCell>
    </TableRow>
  );

  const renderStaleRow = (item: ConsistencyIssue, idx: number) => {
    const staleDays = item.days_since_update;
    const staleLabel =
      typeof staleDays === 'number' ? `${staleDays}d ago` : 'Unknown';
    const staleColor =
      typeof staleDays !== 'number' ? 'default' : staleDays > 180 ? 'error' : 'warning';

    return (
      <TableRow key={idx}>
      <TableCell>
        <Button
          size="small"
          onClick={() => {
            if (typeof item.artifact_id === 'number') {
              onArtifactClick?.(item.artifact_id);
            }
          }}
        >
          #{item.artifact_id ?? '-'}
        </Button>
      </TableCell>
      <TableCell>
        <Chip size="small" label={item.type || 'unknown'} variant="outlined" />
      </TableCell>
      <TableCell>
        <Typography variant="body2" noWrap sx={{ maxWidth: 250 }}>
          {item.title || item.display_key || '-'}
        </Typography>
      </TableCell>
      <TableCell>
        <Chip
          size="small"
          icon={<AccessTime />}
          label={staleLabel}
          color={staleColor}
        />
      </TableCell>
      </TableRow>
    );
  };

  const renderRecommendations = (recommendations: ConsistencyCheckRecommendation[]) => {
    if (!recommendations?.length) return null;

    return (
      <Paper variant="outlined" sx={{ p: 2, mt: 2 }}>
        <Typography variant="subtitle1" fontWeight={600} gutterBottom>
          Recommendations
        </Typography>
        <Stack spacing={1}>
          {recommendations.map((rec, idx) => (
            <Alert
              key={idx}
              severity={PRIORITY_COLORS[rec.priority]}
              icon={<Info />}
            >
              <Typography variant="subtitle2" fontWeight={600}>
                {rec.category}: {rec.action}
              </Typography>
              <Typography variant="body2">{rec.reason}</Typography>
              {rec.fix && (
                <Typography variant="caption" color="text.secondary">
                  Fix: {rec.fix}
                </Typography>
              )}
            </Alert>
          ))}
        </Stack>
      </Paper>
    );
  };

  const renderDetailedCycles = () => {
    if (!detailedCycles) return null;

    return (
      <Paper variant="outlined" sx={{ p: 2, mt: 2 }}>
        <Typography variant="subtitle1" fontWeight={600} gutterBottom>
          Detailed Cycle Analysis
        </Typography>
        <Typography variant="body2" color="text.secondary" mb={2}>
          {detailedCycles.total_cycles} cycles detected in DAG-enforced link types:{' '}
          {detailedCycles.checked_link_types.join(', ')}
        </Typography>

        {detailedCycles.cycles.map((cycle, idx) => (
          <Card key={idx} variant="outlined" sx={{ mb: 1 }}>
            <CardContent sx={{ py: 1, '&:last-child': { pb: 1 } }}>
              <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
                <Chip
                  size="small"
                  label={`Cycle #${cycle.cycle_index + 1}`}
                  color="error"
                />
                <Chip
                  size="small"
                  label={cycle.link_type}
                  variant="outlined"
                />
                <Typography variant="body2" color="text.secondary">
                  Length: {cycle.cycle_length}
                </Typography>
              </Stack>
              <Stack direction="row" spacing={1} mt={1} flexWrap="wrap" useFlexGap>
                {cycle.artifacts.map((art, i) => (
                  <React.Fragment key={art.id}>
                    <Tooltip title={`${art.type}: ${art.title || art.external_id}`}>
                      <Chip
                        size="small"
                        label={art.display_key || `#${art.id}`}
                        onClick={() => onArtifactClick?.(art.id)}
                        sx={{ cursor: 'pointer' }}
                        color={art.position === 0 ? 'primary' : 'default'}
                      />
                    </Tooltip>
                    {i < cycle.artifacts.length - 1 && (
                      <Typography variant="body2" sx={{ alignSelf: 'center' }}>→</Typography>
                    )}
                  </React.Fragment>
                ))}
                <Typography variant="body2" sx={{ alignSelf: 'center' }}>
                  → {cycle.artifacts[0]?.display_key || `#${cycle.cycle_path[0]}`}
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        ))}
      </Paper>
    );
  };

  return (
    <Box>
      {/* Header */}
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h6">Data Consistency Checks</Typography>
        <Stack direction="row" spacing={1}>
          {checkResult && (checkResult.issues.broken_ref_count > 0 || checkResult.issues.duplicate_count > 0) && (
            <>
              <Button
                variant="outlined"
                startIcon={<Build />}
                onClick={() => handleFix(true)}
                disabled={fixLoading}
              >
                Preview Fixes
              </Button>
              <Button
                variant="contained"
                color="warning"
                startIcon={<Build />}
                onClick={() => setConfirmDialog(true)}
                disabled={fixLoading}
              >
                Apply Fixes
              </Button>
            </>
          )}
          <Button
            variant="contained"
            startIcon={loading ? <CircularProgress size={20} color="inherit" /> : <PlayArrow />}
            onClick={runCheck}
            disabled={loading}
          >
            Run Check
          </Button>
        </Stack>
      </Stack>

      {/* Check Options */}
      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Typography variant="subtitle2" gutterBottom>Check Options</Typography>
        <FormGroup row>
          <FormControlLabel
            control={<Switch checked={checkOrphans} onChange={(e) => setCheckOrphans(e.target.checked)} />}
            label="Orphaned Artifacts"
          />
          <FormControlLabel
            control={<Switch checked={checkCycles} onChange={(e) => setCheckCycles(e.target.checked)} />}
            label="Circular Dependencies"
          />
          <FormControlLabel
            control={<Switch checked={checkDuplicates} onChange={(e) => setCheckDuplicates(e.target.checked)} />}
            label="Duplicate Links"
          />
          <FormControlLabel
            control={<Switch checked={checkBrokenRefs} onChange={(e) => setCheckBrokenRefs(e.target.checked)} />}
            label="Broken References"
          />
          <FormControlLabel
            control={<Switch checked={checkStale} onChange={(e) => setCheckStale(e.target.checked)} />}
            label="Stale Artifacts"
          />
        </FormGroup>
        {checkStale && (
          <Box mt={2} maxWidth={400}>
            <Typography variant="caption" color="text.secondary">
              Stale threshold: {staleDays} days
            </Typography>
            <Slider
              value={staleDays}
              onChange={handleStaleDaysChange}
              min={7}
              max={365}
              marks={[
                { value: 30, label: '30d' },
                { value: 90, label: '90d' },
                { value: 180, label: '180d' },
                { value: 365, label: '1y' },
              ]}
            />
          </Box>
        )}
      </Paper>

      {/* Error Display */}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Fix Result */}
      {fixResult && (
        <Alert
          severity={fixResult.dry_run ? 'info' : 'success'}
          sx={{ mb: 2 }}
          onClose={() => setFixResult(null)}
        >
          {fixResult.dry_run ? 'Dry run preview: ' : 'Applied fixes: '}
          {fixResult.fixed_broken_refs} broken references,{' '}
          {fixResult.fixed_duplicates} duplicate links
          {fixResult.dry_run && ' would be fixed'}
        </Alert>
      )}

      {/* Loading State */}
      {loading && (
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <CircularProgress />
          <Typography variant="body2" color="text.secondary" mt={2}>
            Running consistency checks...
          </Typography>
        </Paper>
      )}

      {/* Results */}
      {checkResult && !loading && (
        <>
          {renderHealthScore()}

          {/* Issue Sections */}
          <Stack spacing={1}>
            {renderIssueSection(
              'Orphaned Artifacts',
              <LinkOff color="warning" />,
              checkResult.issues.orphan_count,
              checkResult.issues.orphans,
              renderOrphanRow
            )}

            {renderIssueSection(
              'Circular Dependencies',
              <Loop color="error" />,
              checkResult.issues.cycle_count,
              checkResult.issues.cycles,
              renderCycleRow
            )}

            {checkResult.issues.cycle_count > 0 && (
              <Box pl={2}>
                <Button
                  size="small"
                  startIcon={cyclesLoading ? <CircularProgress size={16} /> : <Info />}
                  onClick={loadDetailedCycles}
                  disabled={cyclesLoading}
                >
                  Load Detailed Cycle Analysis
                </Button>
              </Box>
            )}

            {renderIssueSection(
              'Broken References',
              <BugReport color="error" />,
              checkResult.issues.broken_ref_count,
              checkResult.issues.broken_references,
              renderBrokenRefRow
            )}

            {renderIssueSection(
              'Duplicate Links',
              <ContentCopy color="warning" />,
              checkResult.issues.duplicate_count,
              checkResult.issues.duplicates,
              renderDuplicateRow
            )}

            {renderIssueSection(
              'Stale Artifacts',
              <AccessTime sx={{ color: '#9E9E9E' }} />,
              checkResult.issues.stale_count,
              checkResult.issues.stale_artifacts,
              renderStaleRow
            )}
          </Stack>

          {/* Detailed Cycles */}
          {renderDetailedCycles()}

          {/* Recommendations */}
          {renderRecommendations(checkResult.recommendations)}
        </>
      )}

      {/* No Results Yet */}
      {!checkResult && !loading && (
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <BugReport sx={{ fontSize: 64, color: 'text.secondary', mb: 2 }} />
          <Typography variant="h6" gutterBottom>
            Run Consistency Check
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Click &quot;Run Check&quot; to analyze your traceability data for orphaned artifacts,
            circular dependencies, broken references, duplicate links, and stale data.
          </Typography>
        </Paper>
      )}

      {/* Confirm Dialog */}
      <Dialog open={confirmDialog} onClose={() => setConfirmDialog(false)}>
        <DialogTitle>Apply Fixes?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            This will permanently remove broken references and duplicate links from your database.
            It&apos;s recommended to run a preview first to see what will be changed.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmDialog(false)}>Cancel</Button>
          <Button onClick={() => handleFix(true)} disabled={fixLoading}>
            Preview First
          </Button>
          <Button
            onClick={() => handleFix(false)}
            color="warning"
            variant="contained"
            disabled={fixLoading}
          >
            {fixLoading ? <CircularProgress size={20} /> : 'Apply Fixes'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default DataConsistencyPanel;
