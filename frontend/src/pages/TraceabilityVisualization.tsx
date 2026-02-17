import React, { useState, useEffect, useMemo } from 'react';
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
  listProjects,
  Project,
  getConfidenceDistribution,
  ConfidenceDistribution,
  FullChainNode,
} from '../services/api';

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

  const parseProjectValue = (value: string): number | undefined => {
    if (value === '') return undefined;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  };
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<number | undefined>();
  const [artifactIdInput, setArtifactIdInput] = useState('');
  const [selectedArtifactId, setSelectedArtifactId] = useState<number | null>(null);
  const [selectedArtifact, setSelectedArtifact] = useState<FullChainNode | null>(null);
  const [confidenceData, setConfidenceData] = useState<ConfidenceDistribution | null>(null);
  const [confidenceLoading, setConfidenceLoading] = useState(false);
  const handleProjectChange = (event: SelectChangeEvent<string>) => {
    setProjectId(parseProjectValue(event.target.value));
  };

  // Load projects
  useEffect(() => {
    listProjects()
      .then((res) => setProjects(res.data))
      .catch(console.error);
  }, []);

  // Read artifact ID from URL
  useEffect(() => {
    const artifactParam = searchParams.get('artifact');
    if (artifactParam) {
      const id = parseInt(artifactParam, 10);
      if (!isNaN(id)) {
        setSelectedArtifactId(id);
        setArtifactIdInput(artifactParam);
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

  // Load confidence distribution
  useEffect(() => {
    const loadConfidence = async () => {
      setConfidenceLoading(true);
      try {
        const data = await getConfidenceDistribution({ projectId });
        setConfidenceData(data);
      } catch (err) {
        console.error('Failed to load confidence distribution', err);
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

  const handleArtifactSelect = () => {
    const id = parseInt(artifactIdInput, 10);
    if (!isNaN(id)) {
      setSelectedArtifactId(id);
      const params = new URLSearchParams(searchParams);
      params.set('artifact', String(id));
      setSearchParams(params);
    }
  };

  const handleNodeClick = (node: FullChainNode) => {
    setSelectedArtifact(node);
    setSelectedArtifactId(node.id);
    setArtifactIdInput(String(node.id));
    const params = new URLSearchParams(searchParams);
    params.set('artifact', String(node.id));
    setSearchParams(params);
  };

  const handleOrphanLink = (artifactId: number) => {
    setSelectedArtifactId(artifactId);
    setArtifactIdInput(String(artifactId));
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
            <Select
              value={projectId ?? ''}
              label="Project"
              onChange={handleProjectChange}
            >
              <MenuItem value="">All Projects</MenuItem>
              {projects.map((p) => (
                <MenuItem key={p.id} value={p.id}>
                  {p.name || p.jira_key}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <TextField
            size="small"
            label="Artifact ID"
            value={artifactIdInput}
            onChange={(e) => setArtifactIdInput(e.target.value)}
            placeholder="Enter artifact ID"
            sx={{ width: 150 }}
            onKeyDown={(e) => e.key === 'Enter' && handleArtifactSelect()}
          />

          <Button
            variant="contained"
            startIcon={<Search />}
            onClick={handleArtifactSelect}
            disabled={!artifactIdInput}
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
              setSelectedArtifactId(id);
              setArtifactIdInput(String(id));
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
          projectId={projectId}
          onCreateLink={handleOrphanLink}
        />
      </TabPanel>

      <TabPanel value={tabValue} index={3}>
        <Paper sx={{ p: 2 }}>
          <Typography variant="h6" gutterBottom>
            Confidence Score Distribution
          </Typography>

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
              No confidence data available. Run the traceability backfill first.
            </Alert>
          )}
        </Paper>
      </TabPanel>

      <TabPanel value={tabValue} index={4}>
        <SuggestedLinksPanel
          projectId={projectId}
          onLinkCreated={() => {
            // Refresh confidence data if we're viewing it
            if (confidenceData) {
              getConfidenceDistribution({ projectId }).then(setConfidenceData);
            }
          }}
        />
      </TabPanel>

      <TabPanel value={tabValue} index={5}>
        <SyncHealthDashboard
          projectId={projectId}
          onProjectSelect={(id) => setProjectId(id)}
        />
      </TabPanel>

      <TabPanel value={tabValue} index={6}>
        <DataConsistencyPanel
          projectId={projectId}
          onArtifactClick={(id) => {
            setSelectedArtifactId(id);
            setArtifactIdInput(String(id));
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
