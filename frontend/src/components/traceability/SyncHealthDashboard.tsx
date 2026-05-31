import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Paper,
  Typography,
  CircularProgress,
  Alert,
  Chip,
  Button,
  Grid,
  Card,
  CardContent,
  LinearProgress,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Collapse,
  IconButton,
  Tooltip,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
} from '@mui/material';
import type { SelectChangeEvent } from '@mui/material/Select';
import {
  CheckCircle,
  Warning,
  Error as ErrorIcon,
  Cloud,
  CloudOff,
  ExpandMore,
  ExpandLess,
  Refresh,
  Storage,
  GitHub,
  Article,
  BugReport,
  Code,
} from '@mui/icons-material';
import {
  getSyncHealth,
  getDetailedSyncHealth,
  SyncHealthResponse,
  SyncSourceHealth,
  SyncProjectHealth,
  DetailedSyncHealthResponse,
  listProjects,
  Project,
} from '../../services/api';
import { getErrorMessage, logError } from '../../utils/errorUtils';

interface SyncHealthDashboardProps {
  projectId?: number;
  onProjectSelect?: (projectId: number | undefined) => void;
  /** When false, hides the "All Projects" option — used where the page is scoped
   * to the single global project, so an "all" selection would be a no-op (codex P2). */
  allowAllProjects?: boolean;
}

const HEALTH_COLORS: Record<string, string> = {
  healthy: '#4CAF50',
  warning: '#FF9800',
  critical: '#F44336',
  stale: '#9E9E9E',
  unknown: '#9E9E9E',
};

const HEALTH_ICONS: Record<string, React.ReactNode> = {
  healthy: <CheckCircle color="success" />,
  warning: <Warning color="warning" />,
  critical: <ErrorIcon color="error" />,
  stale: <Warning sx={{ color: '#9E9E9E' }} />,
  unknown: <Warning sx={{ color: '#9E9E9E' }} />,
};

const SOURCE_ICONS: Record<string, React.ReactNode> = {
  jira: <BugReport />,
  confluence: <Article />,
  github: <GitHub />,
  gitlab: <Code />,
  git: <Code />,
};

const formatRelativeTime = (dateString?: string | null): string => {
  if (!dateString) return 'Never';
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
};

const healthSummaryText = (healthData: SyncHealthResponse): string =>
  [
    `${healthData.summary.reachable_sources} of ${healthData.summary.total_sources} sources reachable`,
    `${healthData.summary.total_artifacts.toLocaleString()} total artifacts`,
    healthData.summary.last_sync
      ? `Last sync: ${formatRelativeTime(healthData.summary.last_sync)}`
      : undefined,
    `Checked: ${formatRelativeTime(healthData.summary.checked_at)}`,
  ]
    .filter(Boolean)
    .join(' - ');

const SyncHealthDashboard: React.FC<SyncHealthDashboardProps> = ({
  projectId: initialProjectId,
  onProjectSelect,
  allowAllProjects = true,
}) => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [healthData, setHealthData] = useState<SyncHealthResponse | null>(null);
  const [detailedData, setDetailedData] = useState<DetailedSyncHealthResponse | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<number | undefined>(initialProjectId);
  const [expandedProject, setExpandedProject] = useState<number | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    setSelectedProjectId(initialProjectId);
  }, [initialProjectId]);

  const parseProjectValue = (value: string): number | undefined => {
    if (value === '') return undefined;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  };

  const loadHealthData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [health, projectList] = await Promise.all([
        getSyncHealth({ projectId: selectedProjectId }),
        listProjects(),
      ]);
      setHealthData(health);
      setProjects(projectList.data);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to load sync health data'));
    } finally {
      setLoading(false);
    }
  }, [selectedProjectId]);

  useEffect(() => {
    loadHealthData();
  }, [loadHealthData]);

  const loadDetailedHealth = async (projectId: number) => {
    if (expandedProject === projectId) {
      setExpandedProject(null);
      setDetailedData(null);
      return;
    }

    setExpandedProject(projectId);
    setDetailLoading(true);
    try {
      const detail = await getDetailedSyncHealth(projectId);
      setDetailedData(detail);
    } catch (err: unknown) {
      logError('Failed to load detailed health', err);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleProjectChange = (projectId: number | undefined) => {
    setSelectedProjectId(projectId);
    onProjectSelect?.(projectId);
  };

  const renderSourceCard = (source: SyncSourceHealth) => (
    <Card
      key={source.source}
      variant="outlined"
      sx={{
        flex: 1,
        minWidth: 180,
        bgcolor:
          source.status === 'reachable'
            ? 'success.50'
            : source.status === 'degraded'
              ? 'warning.50'
              : 'grey.50',
        borderColor:
          source.status === 'reachable'
            ? 'success.main'
            : source.status === 'degraded'
              ? 'warning.main'
              : 'grey.400',
      }}
    >
      <CardContent sx={{ py: 1.5, '&:last-child': { pb: 1.5 } }}>
        <Stack direction="row" alignItems="center" spacing={1} mb={1}>
          {SOURCE_ICONS[source.source.toLowerCase()] || <Storage />}
          <Typography variant="subtitle2">{source.label}</Typography>
          {source.status === 'reachable' ? (
            <Cloud color="success" fontSize="small" />
          ) : source.status === 'degraded' ? (
            <Warning color="warning" fontSize="small" />
          ) : (
            <CloudOff color="disabled" fontSize="small" />
          )}
        </Stack>
        <Typography variant="body2" color="text.secondary">
          {source.artifact_count.toLocaleString()} artifacts
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {source.status === 'reachable'
            ? `Last sync: ${formatRelativeTime(source.last_sync)}`
            : source.status === 'degraded'
              ? `Last check: ${formatRelativeTime(source.checked_at)}`
              : 'Not configured'}
        </Typography>
        <Typography variant="caption" color="text.secondary" display="block">
          Source: {source.effective_connector_source}
        </Typography>
        {source.error && (
          <Typography
            variant="caption"
            color={source.status === 'degraded' ? 'warning.main' : 'text.secondary'}
            display="block"
          >
            {source.error}
          </Typography>
        )}
      </CardContent>
    </Card>
  );

  const renderProjectRow = (project: SyncProjectHealth) => {
    const isExpanded = expandedProject === project.project_id;

    return (
      <React.Fragment key={project.project_id}>
        <TableRow hover sx={{ cursor: 'pointer' }} onClick={() => loadDetailedHealth(project.project_id)}>
          <TableCell>
            <IconButton size="small">
              {isExpanded ? <ExpandLess /> : <ExpandMore />}
            </IconButton>
          </TableCell>
          <TableCell>
            <Stack direction="row" alignItems="center" spacing={1}>
              {HEALTH_ICONS[project.health_status] || HEALTH_ICONS.unknown}
              <Typography variant="body2" fontWeight={500}>
                {project.project_name || project.jira_key}
              </Typography>
            </Stack>
          </TableCell>
          <TableCell>
            <Chip size="small" label={project.jira_key} variant="outlined" />
          </TableCell>
          <TableCell align="right">{project.artifact_count.toLocaleString()}</TableCell>
          <TableCell>
            <Tooltip title={project.last_sync || 'Never synced'}>
              <Typography variant="body2" color="text.secondary">
                {formatRelativeTime(project.last_sync)}
              </Typography>
            </Tooltip>
          </TableCell>
          <TableCell>
            <Chip
              size="small"
              label={project.health_status}
              sx={{
                bgcolor: `${HEALTH_COLORS[project.health_status]}25`,
                color: HEALTH_COLORS[project.health_status],
                fontWeight: 500,
              }}
            />
          </TableCell>
        </TableRow>
        <TableRow>
          <TableCell colSpan={6} sx={{ py: 0, borderBottom: isExpanded ? undefined : 'none' }}>
            <Collapse in={isExpanded}>
              {detailLoading ? (
                <Box py={2} display="flex" justifyContent="center">
                  <CircularProgress size={24} />
                </Box>
              ) : detailedData && detailedData.project_id === project.project_id ? (
                <Box py={2} px={2}>
                  <Grid container spacing={2}>
                    <Grid item xs={12} md={4}>
                      <Typography variant="subtitle2" gutterBottom>
                        Artifacts by Type
                      </Typography>
                      <Stack spacing={0.5}>
                        {Object.entries(detailedData.by_type).map(([type, count]) => (
                          <Stack key={type} direction="row" justifyContent="space-between">
                            <Typography variant="body2" color="text.secondary">
                              {type}
                            </Typography>
                            <Typography variant="body2">{count.toLocaleString()}</Typography>
                          </Stack>
                        ))}
                      </Stack>
                    </Grid>

                    <Grid item xs={12} md={4}>
                      <Typography variant="subtitle2" gutterBottom>
                        Artifacts by Source
                      </Typography>
                      <Stack spacing={0.5}>
                        {Object.entries(detailedData.by_source).map(([source, count]) => (
                          <Stack key={source} direction="row" justifyContent="space-between">
                            <Typography variant="body2" color="text.secondary">
                              {source}
                            </Typography>
                            <Typography variant="body2">{count.toLocaleString()}</Typography>
                          </Stack>
                        ))}
                      </Stack>
                    </Grid>

                    <Grid item xs={12} md={4}>
                      <Typography variant="subtitle2" gutterBottom>
                        Link Coverage
                      </Typography>
                      <Box mb={1}>
                        <Stack direction="row" justifyContent="space-between" mb={0.5}>
                          <Typography variant="body2" color="text.secondary">
                            Coverage
                          </Typography>
                          <Typography variant="body2">
                            {(detailedData.link_coverage.coverage_pct ?? 0).toFixed(1)}%
                          </Typography>
                        </Stack>
                        <LinearProgress
                          variant="determinate"
                          value={detailedData.link_coverage.coverage_pct}
                          sx={{ height: 8, borderRadius: 1 }}
                        />
                      </Box>
                      <Typography variant="body2" color="text.secondary">
                        {detailedData.link_coverage.linked_artifacts} / {detailedData.link_coverage.total_artifacts} linked
                      </Typography>
                      {detailedData.link_coverage.orphaned_artifacts > 0 && (
                        <Chip
                          size="small"
                          label={`${detailedData.link_coverage.orphaned_artifacts} orphaned`}
                          color="warning"
                          sx={{ mt: 1 }}
                        />
                      )}
                    </Grid>

                    {detailedData.repositories.length > 0 && (
                      <Grid item xs={12}>
                        <Typography variant="subtitle2" gutterBottom>
                          Linked Repositories
                        </Typography>
                        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                          {detailedData.repositories.map((repo) => (
                            <Chip
                              key={repo.id}
                              size="small"
                              icon={repo.provider === 'github' ? <GitHub /> : <Code />}
                              label={`${repo.repo_slug} (${repo.default_branch || 'main'})`}
                              variant="outlined"
                            />
                          ))}
                        </Stack>
                      </Grid>
                    )}
                  </Grid>
                </Box>
              ) : null}
            </Collapse>
          </TableCell>
        </TableRow>
      </React.Fragment>
    );
  };

  if (loading) {
    return (
      <Paper sx={{ p: 4, textAlign: 'center' }}>
        <CircularProgress />
        <Typography variant="body2" color="text.secondary" mt={2}>
          Loading sync health data...
        </Typography>
      </Paper>
    );
  }

  if (error) {
    return (
      <Alert
        severity="error"
        action={
          <Button color="inherit" size="small" onClick={loadHealthData}>
            Retry
          </Button>
        }
      >
        {error}
      </Alert>
    );
  }

  if (!healthData) {
    return <Alert severity="info">No sync health data available.</Alert>;
  }

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h6">Sync Health Dashboard</Typography>
        <Stack direction="row" spacing={2}>
          <FormControl size="small" sx={{ minWidth: 200 }}>
            <InputLabel>Filter by Project</InputLabel>
            <Select<string>
              value={selectedProjectId !== undefined ? String(selectedProjectId) : ''}
              label="Filter by Project"
              onChange={(e: SelectChangeEvent) => handleProjectChange(parseProjectValue(e.target.value))}
            >
              {allowAllProjects && <MenuItem value="">All Projects</MenuItem>}
              {projects.map((p) => (
                <MenuItem key={p.id} value={String(p.id)}>
                  {p.name || p.jira_key}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Button variant="outlined" startIcon={<Refresh />} onClick={loadHealthData}>
            Refresh
          </Button>
        </Stack>
      </Stack>

      <Card
        sx={{
          mb: 3,
          bgcolor: `${HEALTH_COLORS[String(healthData.health.status || 'unknown')]}15`,
          borderLeft: `4px solid ${HEALTH_COLORS[String(healthData.health.status || 'unknown')]}`,
        }}
      >
        <CardContent>
          <Grid container spacing={3} alignItems="center">
            <Grid item>
              <Box
                sx={{
                  width: 80,
                  height: 80,
                  borderRadius: '50%',
                  bgcolor: `${HEALTH_COLORS[String(healthData.health.status || 'unknown')]}20`,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <Typography
                  variant="h4"
                  sx={{ color: HEALTH_COLORS[String(healthData.health.status || 'unknown')], fontWeight: 700 }}
                >
                  {Math.round(healthData.health.score)}%
                </Typography>
              </Box>
            </Grid>
            <Grid item xs>
              <Stack direction="row" alignItems="center" spacing={1} mb={1}>
                {HEALTH_ICONS[String(healthData.health.status || 'unknown')]}
                <Typography variant="h5" fontWeight={600}>
                  {(() => {
                    const status = healthData.health.status || 'unknown';
                    return `System ${status.charAt(0).toUpperCase()}${status.slice(1)}`;
                  })()}
                </Typography>
              </Stack>
              <Typography variant="body2" color="text.secondary">
                {healthSummaryText(healthData)}
              </Typography>
            </Grid>
            <Grid item>
              <Box sx={{ width: 200 }}>
                <Typography variant="caption" color="text.secondary">
                  Health Score
                </Typography>
                <LinearProgress
                  variant="determinate"
                  value={healthData.health.score}
                  sx={{
                    height: 12,
                    borderRadius: 1,
                    bgcolor: '#e0e0e0',
                    '& .MuiLinearProgress-bar': {
                      bgcolor: HEALTH_COLORS[healthData.health.status],
                    },
                  }}
                />
              </Box>
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      <Typography variant="subtitle1" fontWeight={600} mb={1}>
        Data Sources
      </Typography>
      <Stack direction="row" spacing={2} mb={3} flexWrap="wrap" useFlexGap>
        {healthData.sources.map(renderSourceCard)}
      </Stack>

      <Typography variant="subtitle1" fontWeight={600} mb={1}>
        Project Health ({healthData.projects.length})
      </Typography>
      <TableContainer component={Paper} variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell width={50} />
              <TableCell>Project</TableCell>
              <TableCell>Key</TableCell>
              <TableCell align="right">Artifacts</TableCell>
              <TableCell>Last Sync</TableCell>
              <TableCell>Status</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {healthData.projects.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} align="center">
                  <Typography variant="body2" color="text.secondary" py={2}>
                    No projects found
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              healthData.projects.map(renderProjectRow)
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
};

export default SyncHealthDashboard;
