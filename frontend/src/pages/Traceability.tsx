import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Tab,
  Tabs,
  Typography,
} from '@mui/material';
import type { SelectChangeEvent } from '@mui/material/Select';
import DownloadIcon from '@mui/icons-material/Download';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import BubbleChartIcon from '@mui/icons-material/BubbleChart';
import HistoryIcon from '@mui/icons-material/History';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import MonitorHeartIcon from '@mui/icons-material/MonitorHeart';
import GridOnIcon from '@mui/icons-material/GridOn';
import DashboardIcon from '@mui/icons-material/Dashboard';
import { Link as RouterLink } from 'react-router-dom';
import MatrixExportDialog from '../components/traceability/MatrixExportDialog';
import RTMMatrixViewer from '../components/traceability/RTMMatrixViewer';
import RTMMatrixFilters from '../components/traceability/RTMMatrixFilters';
import MatrixConfigPanel from '../components/traceability/MatrixConfigPanel';
import type { RTMFilters, RTMPagination, RTMMatrixResponse } from '../services/api/types';
import CoverageSnapshot from '../components/traceability/CoverageSnapshot';
import FlowExplorer from '../components/traceability/FlowExplorer';
import ProjectScopePanel from '../components/traceability/ProjectScopePanel';
import { buildRepairMessage, buildTypeRows, parseProjectId } from '../components/traceability/traceabilityUtils';

import {
  Project,
  TraceabilityBackfillResult,
  TraceabilityMatrixSummary,
  getTraceabilityMatrix,
  runTraceabilityBackfill,
} from '../services/api';
import { useProjects } from '../services/api/hooks';
import { getErrorMessage, logError } from '../utils/errorUtils';

interface BackfillState {
  running: boolean;
  message?: string | null;
  error?: string | null;
  lastResult?: TraceabilityBackfillResult | null;
}


const Traceability: React.FC = () => {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<number | 'all'>('all');
  const [projectsLoading, setProjectsLoading] = useState(false);
  const [projectsError, setProjectsError] = useState<string | null>(null);

  const [matrix, setMatrix] = useState<TraceabilityMatrixSummary | null>(null);
  const [matrixLoading, setMatrixLoading] = useState(false);
  const [matrixError, setMatrixError] = useState<string | null>(null);

  const [includeConfluence, setIncludeConfluence] = useState(true);
  const [includeGit, setIncludeGit] = useState(true);
  const [backfillState, setBackfillState] = useState<BackfillState>({ running: false });


  const handleProjectChange = (event: SelectChangeEvent<string>) => {
    setProjectId(parseProjectId(event.target.value));
  };
  const [exportDialogOpen, setExportDialogOpen] = useState(false);

  // Tab state: 0 = Overview, 1 = RTM Matrix
  const [activeTab, setActiveTab] = useState(0);

  // RTM Matrix state
  const [rtmFilters, setRtmFilters] = useState<RTMFilters>({});
  const [rtmCoverage, setRtmCoverage] = useState<RTMMatrixResponse['coverage'] | null>(null);
  const [rtmInitialPagination, setRtmInitialPagination] = useState<RTMPagination | undefined>();

  const handleTabChange = (_: React.SyntheticEvent, newValue: number) => {
    setActiveTab(newValue);
  };

  const handleRtmFiltersChange = useCallback((newFilters: RTMFilters) => {
    setRtmFilters(newFilters);
  }, []);

  const handleRtmFiltersReset = useCallback(() => {
    setRtmFilters({});
  }, []);

  const handleLoadConfig = useCallback((filters: RTMFilters, pagination?: RTMPagination) => {
    setRtmFilters(filters);
    setRtmInitialPagination(pagination);
  }, []);

  const handleRtmCoverageChange = useCallback((coverage: RTMMatrixResponse['coverage']) => {
    setRtmCoverage(coverage);
  }, []);

  const projectsQuery = useProjects(); // shared ['projects'] cache (E1)
  useEffect(() => {
    setProjectsLoading(projectsQuery.isLoading);
    setProjectsError(projectsQuery.error ? getErrorMessage(projectsQuery.error, 'Failed to load projects') : null);
    const data = projectsQuery.data;
    if (!data) return;
    setProjects(data);
    setProjectId(prev => {
      if (!data.length) {
        return 'all';
      }
      if (typeof prev === 'number' && data.some(p => p.id === prev)) {
        return prev;
      }
      return data[0].id;
    });
  }, [projectsQuery.data, projectsQuery.error, projectsQuery.isLoading]);

  const fetchMatrix = useCallback(async (opts?: { force?: boolean }) => {
    setMatrixLoading(true);
    setMatrixError(null);
    try {
      const data = await getTraceabilityMatrix({
        projectId: typeof projectId === 'number' ? projectId : undefined,
        force: opts?.force,
      });
      setMatrix(data);
    } catch (err: unknown) {
      logError('Failed to load traceability matrix', err);
      setMatrixError(getErrorMessage(err, 'Failed to load traceability data'));
    } finally {
      setMatrixLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    fetchMatrix();
  }, [fetchMatrix]);

  const selectedProject = useMemo(
    () => (typeof projectId === 'number' ? projects.find(p => p.id === projectId) : undefined),
    [projectId, projects]
  );

  const typeRows = useMemo(() => buildTypeRows(matrix), [matrix]);

  const matrixHasData = Boolean(matrix && matrix.total > 0);

  const coveragePct = useMemo(() => {
    if (!matrix) return 0;
    const value = matrix.coverage?.coverage_pct ?? 0;
    return Math.round(value * 10) / 10;
  }, [matrix]);

  const linkedCount = matrix?.coverage?.linked_artifacts ?? 0;
  const unlinkedCount = matrix ? Math.max(matrix.total - linkedCount, 0) : 0;

  const handleRefresh = useCallback(() => {
    fetchMatrix({ force: true });
  }, [fetchMatrix]);

  const handleBackfill = useCallback(async () => {
    if (typeof projectId !== 'number') {
      setBackfillState({ running: false, error: 'Select a project before running traceability repair.' });
      return;
    }
    setBackfillState({
      running: true,
      message: 'Traceability repair is running...',
      error: null,
      lastResult: null,
    });

    try {
      const result = await runTraceabilityBackfill(projectId, { includeConfluence, includeGit });

      setBackfillState({
        running: false,
        message: buildRepairMessage(result),
        error: null,
        lastResult: result,
      });
      await fetchMatrix({ force: true });
    } catch (err: unknown) {
      logError('Traceability repair failed', err);
      setBackfillState({
        running: false,
        error: getErrorMessage(err, 'Traceability repair failed'),
      });
    }
  }, [fetchMatrix, includeConfluence, includeGit, projectId]);


  const hasAlerts = Boolean(projectsError || matrixError || backfillState.error || backfillState.message);
  const showEmptyState = !matrixLoading && !matrixHasData;
  const selectedProjectIssuesCount = Number(selectedProject?.meta?.issues_count ?? 0);
  const selectedProjectLastSync = typeof selectedProject?.meta?.last_sync_at === 'string'
    ? selectedProject.meta.last_sync_at
    : null;
  const hasSourceSyncSignal = Boolean(selectedProjectLastSync || selectedProjectIssuesCount > 0);
  const showSyncSetupState = typeof projectId === 'number' && showEmptyState && !hasSourceSyncSignal;
  const backfillWarnings = backfillState.lastResult?.warnings ?? [];

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Traceability
      </Typography>
      <Typography variant="body1" color="text.secondary">
        Monitor end-to-end linkage between requirements, delivery work, and validations. Source sync now creates most artifacts automatically; use traceability repair to reconcile legacy projects or incomplete runs.
      </Typography>

      {/* Quick navigation to related pages */}
      <Stack direction="row" spacing={1} sx={{ mt: 2 }} flexWrap="wrap" useFlexGap>
        <Button
          component={RouterLink}
          to="/traceability/visualization"
          variant="outlined"
          startIcon={<BubbleChartIcon />}
          size="small"
        >
          D3 Visualization
        </Button>
        <Button
          component={RouterLink}
          to="/traceability/flow-builder"
          variant="outlined"
          startIcon={<AccountTreeIcon />}
          size="small"
        >
          Flow Builder
        </Button>
        <Button
          component={RouterLink}
          to="/traceability/history"
          variant="outlined"
          startIcon={<HistoryIcon />}
          size="small"
        >
          Execution History
        </Button>
        <Button
          component={RouterLink}
          to="/traceability/visualization?tab=4"
          variant="outlined"
          startIcon={<AutoAwesomeIcon />}
          size="small"
        >
          Suggested Links
        </Button>
        <Button
          component={RouterLink}
          to="/traceability/visualization?tab=5"
          variant="outlined"
          startIcon={<MonitorHeartIcon />}
          size="small"
        >
          Sync Health
        </Button>
      </Stack>

      {hasAlerts && (
        <Stack spacing={1} sx={{ mt: 2 }}>
          {projectsError && <Alert severity="error">{projectsError}</Alert>}
          {matrixError && <Alert severity="error">{matrixError}</Alert>}
          {backfillState.error && <Alert severity="error">{backfillState.error}</Alert>}
          {backfillState.message && !backfillState.error && <Alert severity="success">{backfillState.message}</Alert>}
          {backfillWarnings.map((warning) => (
            <Alert key={warning} severity="warning">
              {warning}
            </Alert>
          ))}
        </Stack>
      )}

      {/* Tab Navigation */}
      <Box sx={{ borderBottom: 1, borderColor: 'divider', mt: 3 }}>
        <Tabs value={activeTab} onChange={handleTabChange} aria-label="Traceability tabs">
          <Tab
            icon={<DashboardIcon />}
            iconPosition="start"
            label="Overview"
            id="traceability-tab-0"
            aria-controls="traceability-tabpanel-0"
          />
          <Tab
            icon={<GridOnIcon />}
            iconPosition="start"
            label="RTM Matrix"
            id="traceability-tab-1"
            aria-controls="traceability-tabpanel-1"
          />
        </Tabs>
      </Box>

      {/* Tab Panel: Overview */}
      <Box
        role="tabpanel"
        hidden={activeTab !== 0}
        id="traceability-tabpanel-0"
        aria-labelledby="traceability-tab-0"
      >
        {activeTab === 0 && (
          <>
          <Grid container spacing={2} sx={{ mt: 2 }}>
        <Grid item xs={12} md={4}>
          <ProjectScopePanel
            projects={projects}
            projectId={projectId}
            projectsLoading={projectsLoading}
            includeConfluence={includeConfluence}
            includeGit={includeGit}
            backfillRunning={backfillState.running}
            matrixLoading={matrixLoading}
            selectedProject={selectedProject}
            onProjectChange={handleProjectChange}
            onIncludeConfluenceChange={checked => setIncludeConfluence(checked)}
            onIncludeGitChange={checked => setIncludeGit(checked)}
            onBackfill={handleBackfill}
            onRefresh={handleRefresh}
            onExport={() => setExportDialogOpen(true)}
          />
        </Grid>

        <Grid item xs={12} md={8}>
          <CoverageSnapshot
            projectId={projectId}
            matrix={matrix}
            matrixLoading={matrixLoading}
            matrixHasData={matrixHasData}
            coveragePct={coveragePct}
            linkedCount={linkedCount}
            unlinkedCount={unlinkedCount}
            typeRows={typeRows}
            showEmptyState={showEmptyState}
            showSyncSetupState={showSyncSetupState}
            selectedProject={selectedProject}
            onRefresh={handleRefresh}
            onBackfill={handleBackfill}
          />
        </Grid>
      </Grid>

      <FlowExplorer />
          </>
        )}
      </Box>

      {/* Tab Panel: RTM Matrix */}
      <Box
        role="tabpanel"
        hidden={activeTab !== 1}
        id="traceability-tabpanel-1"
        aria-labelledby="traceability-tab-1"
      >
        {activeTab === 1 && (
          <Grid container spacing={2} sx={{ mt: 2 }}>
            {/* Left column: Filters and Saved Projections */}
            <Grid item xs={12} md={3}>
              <Stack spacing={2}>
                {/* Project selector for RTM Matrix */}
                <Paper sx={{ p: 2 }}>
                  <Typography variant="subtitle2" gutterBottom>
                    Project
                  </Typography>
                  <FormControl size="small" fullWidth disabled={projectsLoading || projects.length === 0}>
                    <InputLabel id="rtm-project-label">Project</InputLabel>
                    <Select
                      labelId="rtm-project-label"
                      label="Project"
                      value={projects.length === 0 ? 'all' : String(projectId)}
                      onChange={handleProjectChange}
                    >
                      <MenuItem value="all">All projects</MenuItem>
                      {projects.map(project => (
                        <MenuItem key={project.id} value={String(project.id)}>
                          {project.name || project.jira_key || `Project ${project.id}`}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                </Paper>

                {/* Filters */}
                <RTMMatrixFilters
                  filters={rtmFilters}
                  onChange={handleRtmFiltersChange}
                  onReset={handleRtmFiltersReset}
                  disabled={projectsLoading}
                />

                {/* Saved Projections */}
                <MatrixConfigPanel
                  projectId={typeof projectId === 'number' ? projectId : undefined}
                  currentFilters={rtmFilters}
                  onLoadConfig={handleLoadConfig}
                />
              </Stack>
            </Grid>

            {/* Right column: Matrix Viewer */}
            <Grid item xs={12} md={9}>
              <Paper sx={{ p: 2 }}>
                <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
                  <Typography variant="h6">Requirements Traceability Matrix</Typography>
                  <Stack direction="row" spacing={1}>
                    {rtmCoverage && (
                      <Chip
                        size="small"
                        label={`${rtmCoverage.total_links ?? 0} links`}
                        variant="outlined"
                      />
                    )}
                    <Button
                      variant="outlined"
                      size="small"
                      startIcon={<DownloadIcon />}
                      onClick={() => setExportDialogOpen(true)}
                      disabled={typeof projectId !== 'number'}
                    >
                      Export
                    </Button>
                  </Stack>
                </Stack>

                {typeof projectId !== 'number' ? (
                  <Alert severity="info">
                    Please select a specific project to view the RTM Matrix.
                  </Alert>
                ) : (
                  <RTMMatrixViewer
                    projectId={projectId}
                    filters={rtmFilters}
                    onCoverageChange={handleRtmCoverageChange}
                    initialPagination={rtmInitialPagination}
                  />
                )}
              </Paper>
            </Grid>
          </Grid>
        )}
      </Box>

      {/* Matrix Export Dialog */}
      {typeof projectId === 'number' && (
        <MatrixExportDialog
          open={exportDialogOpen}
          onClose={() => setExportDialogOpen(false)}
          projectId={projectId}
          projectName={selectedProject?.name}
          filters={rtmFilters}
        />
      )}
    </Box>
  );
};

export default Traceability;
