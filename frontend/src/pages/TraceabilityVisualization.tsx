import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Box,
  Typography,
  Paper,
  Grid,
  Tab,
  Tabs,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Autocomplete,
  TextField,
  Button,
  Stack,
  Alert,
  Chip,
  CircularProgress,
} from '@mui/material';
import type { SelectChangeEvent } from '@mui/material/Select';
import {
  AccountTree,
  TrendingUp,
  LinkOff,
  Speed,
  Search,
  AutoAwesome,
  MonitorHeart,
  BugReport,
} from '@mui/icons-material';
import { useSearchParams } from 'react-router-dom';

import TraceabilityGraph from '../components/traceability/TraceabilityGraph';
import ImpactAnalysisPanel from '../components/traceability/ImpactAnalysisPanel';
import OrphanedArtifactsPanel from '../components/traceability/OrphanedArtifactsPanel';
import SuggestedLinksPanel from '../components/SuggestedLinksPanel';
import SyncHealthDashboard from '../components/traceability/SyncHealthDashboard';
import DataConsistencyPanel from '../components/traceability/DataConsistencyPanel';
import {
  getConfidenceDistribution,
  getRTMMatrix,
  ConfidenceDistribution,
  FullChainNode,
  ArtifactSummary,
} from '../services/api';
import { useSelectedProject } from '../hooks/useSelectedProject';
import { getErrorMessage, logError } from '../utils/errorUtils';

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props;
  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={`traceability-tabpanel-${index}`}
      aria-labelledby={`traceability-tab-${index}`}
      {...other}
    >
      {value === index && <Box sx={{ pt: 2 }}>{children}</Box>}
    </div>
  );
}

const TraceabilityVisualization: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [tabValue, setTabValue] = useState(0);

  // Global selected project (UX review C4 / M10): a single source of truth that
  // persists across pages. `projectId` is `null` until the list resolves.
  const { projectId, projects, selectProject } = useSelectedProject();

  // Searchable list of artifacts for the active project, used both to back the
  // artifact Autocomplete and to seed a sensible default graph on load.
  const [artifactOptions, setArtifactOptions] = useState<ArtifactSummary[]>([]);
  const [artifactOptionsLoading, setArtifactOptionsLoading] = useState(false);
  const [selectedArtifactId, setSelectedArtifactId] = useState<number | null>(null);
  const [selectedArtifact, setSelectedArtifact] = useState<FullChainNode | null>(null);
  const [confidenceData, setConfidenceData] = useState<ConfidenceDistribution | null>(null);
  const [confidenceLoading, setConfidenceLoading] = useState(false);
  const [confidenceError, setConfidenceError] = useState<string | null>(null);
  const handleProjectChange = (event: SelectChangeEvent<string>) => {
    const next = Number(event.target.value);
    if (!Number.isFinite(next)) return;
    selectProject(next);
    // Drop the previous project's artifact selection so the default graph for the
    // newly-selected project autoloads cleanly.
    setSelectedArtifactId(null);
    setSelectedArtifact(null);
    if (searchParams.get('artifact')) {
      const params = new URLSearchParams(searchParams);
      params.delete('artifact');
      setSearchParams(params);
    }
  };

  // Read artifact ID + tab from URL (URL takes priority over the autoloaded default).
  useEffect(() => {
    const artifactParam = searchParams.get('artifact');
    if (artifactParam) {
      const id = parseInt(artifactParam, 10);
      if (!isNaN(id)) {
        setSelectedArtifactId(id);
      }
    }
    const tabParam = searchParams.get('tab');
    if (tabParam) {
      const tabIndex = parseInt(tabParam, 10);
      if (!isNaN(tabIndex) && tabIndex >= 0 && tabIndex <= 6) {
        setTabValue(tabIndex);
      }
    }
  }, [searchParams]);

  // Load the project's linked artifacts (rows of the RTM matrix) to back the
  // artifact Autocomplete and seed a default graph. There is no dedicated
  // artifact-search API, so the matrix endpoint is the lightest existing source
  // of {id, key, title}. Orphans are excluded on purpose: graphing a link-less
  // artifact yields a single isolated node, so it makes a poor default and a
  // poor pick (the dedicated Orphaned Artifacts tab handles those).
  useEffect(() => {
    if (projectId == null) {
      setArtifactOptions([]);
      return;
    }
    let cancelled = false;
    setArtifactOptionsLoading(true);
    getRTMMatrix({ projectId, rowLimit: 200, colLimit: 1 })
      .then((res) => {
        if (cancelled) return;
        setArtifactOptions(Array.isArray(res?.rows) ? res.rows : []);
      })
      .catch((error) => {
        if (cancelled) return;
        logError('Failed to load artifacts for traceability picker', error);
        setArtifactOptions([]);
      })
      .finally(() => {
        if (!cancelled) setArtifactOptionsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // Auto-load a sensible default graph when a project is active and nothing has
  // been selected yet (no URL artifact, no prior pick). This removes the friction
  // of having to type an Artifact ID before anything renders. We seed with the
  // first artifact returned for the project.
  useEffect(() => {
    if (selectedArtifactId != null) return;
    if (searchParams.get('artifact')) return;
    const first = artifactOptions[0];
    if (first) {
      setSelectedArtifactId(first.id);
    }
  }, [artifactOptions, selectedArtifactId, searchParams]);

  // Load confidence distribution
  useEffect(() => {
    const loadConfidence = async () => {
      setConfidenceLoading(true);
      setConfidenceError(null);
      try {
        const data = await getConfidenceDistribution({ projectId: projectId ?? undefined });
        setConfidenceData(data);
      } catch (err) {
        logError('Failed to load confidence distribution', err);
        setConfidenceData(null);
        setConfidenceError(getErrorMessage(err, 'Failed to load confidence distribution'));
      } finally {
        setConfidenceLoading(false);
      }
    };
    if (tabValue === 3) {
      loadConfidence();
    }
  }, [tabValue, projectId]);

  const handleTabChange = (_: React.SyntheticEvent, newValue: number) => {
    setTabValue(newValue);
    const params = new URLSearchParams(searchParams);
    params.set('tab', String(newValue));
    setSearchParams(params);
  };

  const loadArtifactGraph = useCallback(
    (artifactId: number) => {
      setSelectedArtifactId(artifactId);
      const params = new URLSearchParams(searchParams);
      params.set('artifact', String(artifactId));
      setSearchParams(params);
    },
    [searchParams, setSearchParams]
  );

  // Pick an artifact from the Autocomplete. Loads its graph immediately.
  const handleArtifactPick = (artifact: ArtifactSummary | null) => {
    if (artifact) {
      loadArtifactGraph(artifact.id);
    } else {
      setSelectedArtifactId(null);
      setSelectedArtifact(null);
    }
  };

  // "Load Graph" now works without manual typing: it (re)loads the currently
  // picked artifact, or falls back to the first available artifact for the project.
  const handleArtifactSelect = () => {
    const target = selectedArtifactId ?? artifactOptions[0]?.id ?? null;
    if (target != null) {
      loadArtifactGraph(target);
    }
  };

  const handleNodeClick = (node: FullChainNode) => {
    setSelectedArtifact(node);
    loadArtifactGraph(node.id);
  };

  const handleOrphanLink = (artifactId: number) => {
    setSelectedArtifactId(artifactId);
    setTabValue(0); // Switch to graph view
    const params = new URLSearchParams(searchParams);
    params.set('artifact', String(artifactId));
    params.set('tab', '0');
    setSearchParams(params);
  };

  const confidenceHistogramData = useMemo(() => {
    if (!confidenceData?.histogram) return [];
    return confidenceData.histogram;
  }, [confidenceData]);

  const confidenceStats = useMemo(
    () =>
      confidenceData?.stats || {
        total_links: 0,
        avg_confidence: 0,
        median_confidence: 0,
        min_confidence: 0,
        max_confidence: 0,
      },
    [confidenceData]
  );

  // The Autocomplete value: map the selected id back to a loaded option. A
  // deep-linked id that is not in the first page of options stays `null` (the
  // graph still renders by id; the picker just shows no chip for it).
  const selectedOption = useMemo(
    () => artifactOptions.find((a) => a.id === selectedArtifactId) ?? null,
    [artifactOptions, selectedArtifactId]
  );

  const artifactOptionLabel = (a: ArtifactSummary) =>
    `${a.display_key || a.external_id}${a.title ? ` — ${a.title}` : ''}`;

  // Child panels and APIs expect `number | undefined`; the global hook yields
  // `number | null`. Normalize once for all downstream call sites.
  const projectIdForChildren = projectId ?? undefined;

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Traceability Visualization
      </Typography>
      <Typography variant="body1" color="text.secondary" paragraph>
        Interactive dependency graph, impact analysis, and orphaned artifact detection for comprehensive traceability insights.
      </Typography>

      {/* Project & Artifact Selection */}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems="center">
          <FormControl size="small" sx={{ minWidth: 200 }}>
            <InputLabel>Project</InputLabel>
            <Select<string>
              value={projectId != null ? String(projectId) : ''}
              label="Project"
              onChange={handleProjectChange}
            >
              {projects.map((p) => (
                <MenuItem key={p.id} value={String(p.id)}>
                  {p.name || p.jira_key}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <Autocomplete<ArtifactSummary>
            size="small"
            sx={{ minWidth: 320, flexGrow: 1 }}
            options={artifactOptions}
            loading={artifactOptionsLoading}
            value={selectedOption}
            onChange={(_, value) => handleArtifactPick(value)}
            getOptionLabel={artifactOptionLabel}
            isOptionEqualToValue={(option, value) => option.id === value.id}
            noOptionsText={
              projectId == null ? 'Select a project first' : 'No artifacts found'
            }
            renderInput={(params) => (
              <TextField
                {...params}
                label="Artifact"
                placeholder="Search by key or title"
                InputProps={{
                  ...params.InputProps,
                  endAdornment: (
                    <>
                      {artifactOptionsLoading ? (
                        <CircularProgress color="inherit" size={18} />
                      ) : null}
                      {params.InputProps.endAdornment}
                    </>
                  ),
                }}
              />
            )}
          />

          <Button
            variant="contained"
            startIcon={<Search />}
            onClick={handleArtifactSelect}
            disabled={projectId == null || (selectedArtifactId == null && artifactOptions.length === 0)}
          >
            Load Graph
          </Button>

          {selectedArtifact && (
            <Chip
              label={`Selected: ${selectedArtifact.display_key || selectedArtifact.external_id}`}
              onDelete={() => {
                setSelectedArtifact(null);
                setSelectedArtifactId(null);
              }}
              color="primary"
            />
          )}
        </Stack>
      </Paper>

      {/* Tabs */}
      <Paper sx={{ mb: 2 }}>
        <Tabs
          value={tabValue}
          onChange={handleTabChange}
          variant="scrollable"
          scrollButtons="auto"
        >
          <Tab icon={<AccountTree />} label="Dependency Graph" iconPosition="start" />
          <Tab icon={<TrendingUp />} label="Impact Analysis" iconPosition="start" />
          <Tab icon={<LinkOff />} label="Orphaned Artifacts" iconPosition="start" />
          <Tab icon={<Speed />} label="Confidence Stats" iconPosition="start" />
          <Tab icon={<AutoAwesome />} label="Suggested Links" iconPosition="start" />
          <Tab icon={<MonitorHeart />} label="Sync Health" iconPosition="start" />
          <Tab icon={<BugReport />} label="Data Consistency" iconPosition="start" />
        </Tabs>
      </Paper>

      {/* Tab Panels */}
      <TabPanel value={tabValue} index={0}>
        {selectedArtifactId ? (
          <TraceabilityGraph
            artifactId={selectedArtifactId}
            minHeight={650}
            onNodeClick={handleNodeClick}
          />
        ) : (
          <Paper sx={{ p: 4, textAlign: 'center' }}>
            <AccountTree sx={{ fontSize: 64, color: 'text.secondary', mb: 2 }} />
            <Typography variant="h6" gutterBottom>
              Select an Artifact to Visualize
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Enter an artifact ID above to see its full traceability chain as an interactive graph.
              You can also click on nodes in the graph to explore further.
            </Typography>
          </Paper>
        )}
      </TabPanel>

      <TabPanel value={tabValue} index={1}>
        {selectedArtifactId ? (
          <ImpactAnalysisPanel
            artifactId={selectedArtifactId}
            artifactTitle={selectedArtifact?.title || undefined}
            onArtifactClick={(id) => {
              loadArtifactGraph(id);
              setTabValue(0);
            }}
          />
        ) : (
          <Paper sx={{ p: 4, textAlign: 'center' }}>
            <TrendingUp sx={{ fontSize: 64, color: 'text.secondary', mb: 2 }} />
            <Typography variant="h6" gutterBottom>
              Select an Artifact for Impact Analysis
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Enter an artifact ID above to analyze the potential impact of changes to that artifact.
            </Typography>
          </Paper>
        )}
      </TabPanel>

      <TabPanel value={tabValue} index={2}>
        <OrphanedArtifactsPanel
          projectId={projectIdForChildren}
          onCreateLink={handleOrphanLink}
        />
      </TabPanel>

      <TabPanel value={tabValue} index={3}>
        <Paper sx={{ p: 2 }}>
          <Typography variant="h6" gutterBottom>
            Confidence Score Distribution
          </Typography>

          {confidenceError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {confidenceError}
            </Alert>
          )}

          {confidenceLoading && (
            <Box display="flex" justifyContent="center" py={4}>
              <CircularProgress />
            </Box>
          )}

          {confidenceData && !confidenceLoading && (
            <Grid container spacing={3}>
              {/* Stats Cards */}
              <Grid item xs={12} md={4}>
                <Paper variant="outlined" sx={{ p: 2 }}>
                  <Typography variant="subtitle2" color="text.secondary">
                    Total Links
                  </Typography>
                  <Typography variant="h4">
                    {confidenceStats.total_links.toLocaleString()}
                  </Typography>
                </Paper>
              </Grid>
              <Grid item xs={12} md={4}>
                <Paper variant="outlined" sx={{ p: 2 }}>
                  <Typography variant="subtitle2" color="text.secondary">
                    Average Confidence
                  </Typography>
                  <Typography variant="h4">
                    {Math.round(confidenceStats.avg_confidence * 100)}%
                  </Typography>
                </Paper>
              </Grid>
              <Grid item xs={12} md={4}>
                <Paper variant="outlined" sx={{ p: 2 }}>
                  <Typography variant="subtitle2" color="text.secondary">
                    Median Confidence
                  </Typography>
                  <Typography variant="h4">
                    {Math.round(confidenceStats.median_confidence * 100)}%
                  </Typography>
                </Paper>
              </Grid>

              {/* Histogram */}
              <Grid item xs={12}>
                <Typography variant="subtitle2" gutterBottom>
                  Distribution Histogram
                </Typography>
                <Stack direction="row" spacing={0.5} alignItems="flex-end" sx={{ height: 150 }}>
                  {confidenceHistogramData.map((bucket, idx) => {
                    const maxCount = confidenceHistogramData.length > 0
                      ? Math.max(...confidenceHistogramData.map((b) => b.count))
                      : 0;
                    const heightPct = maxCount > 0 ? (bucket.count / maxCount) * 100 : 0;
                    return (
                      <Box
                        key={idx}
                        sx={{
                          flex: 1,
                          display: 'flex',
                          flexDirection: 'column',
                          alignItems: 'center',
                        }}
                      >
                        <Typography variant="caption" sx={{ mb: 0.5 }}>
                          {bucket.count}
                        </Typography>
                        <Box
                          sx={{
                            width: '100%',
                            height: `${heightPct}%`,
                            minHeight: bucket.count > 0 ? 4 : 0,
                            bgcolor: 'primary.main',
                            borderRadius: '4px 4px 0 0',
                          }}
                        />
                        <Typography
                          variant="caption"
                          color="text.secondary"
                          sx={{ mt: 0.5, fontSize: 10 }}
                        >
                          {bucket.range}
                        </Typography>
                      </Box>
                    );
                  })}
                </Stack>
              </Grid>

              {/* By Link Type */}
              <Grid item xs={12}>
                <Typography variant="subtitle2" gutterBottom>
                  By Link Type
                </Typography>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  {Object.entries(confidenceData.by_link_type).map(([type, data]) => (
                    <Chip
                      key={type}
                      label={`${type}: ${data.count} links (avg ${Math.round(data.avg_confidence * 100)}%)`}
                      variant="outlined"
                    />
                  ))}
                </Stack>
              </Grid>
            </Grid>
          )}

          {!confidenceData && !confidenceLoading && (
            <Alert severity="info">
              No confidence data available. Sync source data first, then run traceability repair if this project predates automatic artifact ingestion.
            </Alert>
          )}
        </Paper>
      </TabPanel>

      <TabPanel value={tabValue} index={4}>
        <SuggestedLinksPanel
          projectId={projectIdForChildren}
          onLinkCreated={() => {
            if (confidenceData) {
              void getConfidenceDistribution({ projectId: projectId ?? undefined })
                .then(setConfidenceData)
                .catch((error) => logError('Failed to refresh confidence distribution', error));
            }
          }}
        />
      </TabPanel>

      <TabPanel value={tabValue} index={5}>
        <SyncHealthDashboard
          projectId={projectIdForChildren}
          onProjectSelect={(id) => selectProject(id ?? null)}
        />
      </TabPanel>

      <TabPanel value={tabValue} index={6}>
        <DataConsistencyPanel
          projectId={projectIdForChildren}
          onArtifactClick={(id) => {
            setSelectedArtifactId(id);
            setTabValue(0); // Switch to graph view
            const params = new URLSearchParams(searchParams);
            params.set('artifact', String(id));
            params.set('tab', '0');
            setSearchParams(params);
          }}
        />
      </TabPanel>
    </Box>
  );
};

export default TraceabilityVisualization;
