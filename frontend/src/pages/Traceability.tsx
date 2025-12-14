import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  FormControl,
  FormControlLabel,
  Grid,
  InputLabel,
  LinearProgress,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import SyncIcon from '@mui/icons-material/Sync';
import TravelExploreIcon from '@mui/icons-material/TravelExplore';
import AltRouteIcon from '@mui/icons-material/AltRoute';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import EmptyState from '../components/EmptyState';
import BackfillProgressDialog, { BackfillStep } from '../components/BackfillProgressDialog';

import {
  Project,
  TraceabilityBackfillResult,
  TraceabilityFlowEdge,
  TraceabilityFlowNode,
  TraceabilityMatrixSummary,
  TraceabilityRequirementFlow,
  getTraceabilityMatrix,
  getTraceabilityRequirementFlow,
  getTraceabilityTaskArtifacts,
  listProjects,
  runTraceabilityBackfill,
} from '../services/api';

interface BackfillState {
  running: boolean;
  message?: string | null;
  error?: string | null;
  lastResult?: TraceabilityBackfillResult | null;
}

const CORE_LINK_TYPES = ['implements', 'tests', 'deploys', 'derives_from'] as const;
const CORE_LINK_TYPES_SET = new Set<string>(CORE_LINK_TYPES);

interface LinkTypeBreakdown {
  key: string;
  totalLinks: number;
  artifactCount: number;
  coverageRatio: number;
  isCore: boolean;
}

interface TypeRow {
  type: string;
  total: number;
  sharePct: number;
  linked: number;
  unlinked: number;
  coveragePct: number;
  avgLinks: number | null;
  totalLinks: number | null;
  linkTypes: LinkTypeBreakdown[];
  hasCoverageGap: boolean;
  coreMissingCount: number;
}

interface FlowColumn {
  depth: number;
  nodes: TraceabilityFlowNode[];
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
  const [backfillSteps, setBackfillSteps] = useState<BackfillStep[]>([]);

  const [artifactInput, setArtifactInput] = useState('');
  const [jiraKeyInput, setJiraKeyInput] = useState('');
  const [flowDepth, setFlowDepth] = useState(3);
  const [flowData, setFlowData] = useState<TraceabilityRequirementFlow | null>(null);
  const [flowRootId, setFlowRootId] = useState<number | null>(null);
  const [flowLoading, setFlowLoading] = useState(false);
  const [flowError, setFlowError] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    const loadProjects = async () => {
      setProjectsLoading(true);
      setProjectsError(null);
      try {
        const data = await listProjects({ timeout: 45000 });
        if (cancelled) return;
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
      } catch (err: any) {
        if (cancelled) return;
        console.error('Failed to load projects', err);
        setProjectsError(err?.message ?? 'Failed to load projects');
      } finally {
        if (!cancelled) {
          setProjectsLoading(false);
        }
      }
    };

    loadProjects();
    return () => {
      cancelled = true;
    };
  }, []);

  const fetchMatrix = useCallback(async (opts?: { force?: boolean }) => {
    setMatrixLoading(true);
    setMatrixError(null);
    try {
      const data = await getTraceabilityMatrix({
        projectId: typeof projectId === 'number' ? projectId : undefined,
        force: opts?.force,
      });
      setMatrix(data);
    } catch (err: any) {
      console.error('Failed to load traceability matrix', err);
      const detail = err?.response?.data?.detail ?? err?.message ?? 'Failed to load traceability data';
      setMatrixError(detail);
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

    const typeRows = useMemo(() => {
    if (!matrix) return [];
    const keys = new Set<string>();
    Object.keys(matrix.by_type || {}).forEach(key => keys.add(key));
    Object.keys(matrix.per_type || {}).forEach(key => keys.add(key));
    return Array.from(keys)
      .map<TypeRow>(type => {
        const stats = matrix.per_type?.[type];
        const total = stats?.total ?? matrix.by_type?.[type] ?? 0;
        const linked = stats?.linked ?? 0;
        const unlinked = stats?.unlinked ?? Math.max(total - linked, 0);
        const coveragePct = stats?.coverage_pct ?? (total > 0 ? (linked / total) * 100 : 0);
        const avgLinks = stats?.avg_links_per_artifact ?? null;
        const totalLinks = stats?.link_count ?? null;
        const sharePct = matrix.total > 0 ? (total / matrix.total) * 100 : 0;

        const linkTypeCounts = stats?.link_type_counts ?? {};
        const linkTypeArtifactCounts = stats?.link_type_artifact_counts ?? {};
        const dynamicTypes = Object.keys(linkTypeCounts).filter(linkType => !CORE_LINK_TYPES_SET.has(linkType));
        const orderedTypes = [...CORE_LINK_TYPES, ...dynamicTypes];
        const seen = new Set<string>();
        const linkTypes = orderedTypes.reduce<LinkTypeBreakdown[]>((acc, linkType) => {
          const key = String(linkType);
          if (seen.has(key)) {
            return acc;
          }
          seen.add(key);
          const totalForType = linkTypeCounts[key] ?? 0;
          if (!CORE_LINK_TYPES_SET.has(key) && totalForType === 0) {
            return acc;
          }
          const artifactCountForType = linkTypeArtifactCounts[key] ?? 0;
          const coverageRatio = total > 0 ? artifactCountForType / total : 0;
          acc.push({
            key,
            totalLinks: totalForType,
            artifactCount: artifactCountForType,
            coverageRatio,
            isCore: CORE_LINK_TYPES_SET.has(key),
          });
          return acc;
        }, []);

        const coreMissingCount = linkTypes.filter(item => item.isCore && item.totalLinks === 0).length;
        const hasCoverageGap = coreMissingCount > 0;

        return {
          type,
          total,
          sharePct,
          linked,
          unlinked,
          coveragePct,
          avgLinks,
          totalLinks,
          linkTypes,
          hasCoverageGap,
          coreMissingCount,
        };
      })
      .sort((a, b) => b.sharePct - a.sharePct);
  }, [matrix]);

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
      setBackfillState({ running: false, error: 'Select a project before running backfill.' });
      return;
    }

    // Initialize progress steps
    const initialSteps: BackfillStep[] = [
      { id: 'jira', label: 'Parsing Jira issues', status: 'pending' },
      { id: 'confluence', label: 'Parsing Confluence pages', status: 'pending' },
      { id: 'git', label: 'Analyzing Git commits', status: 'pending' },
      { id: 'links', label: 'Building traceability links', status: 'pending' },
      { id: 'finalize', label: 'Finalizing results', status: 'pending' },
    ];

    // Filter steps based on options
    const steps = initialSteps.filter(
      (step) =>
        (step.id !== 'confluence' || includeConfluence) &&
        (step.id !== 'git' || includeGit)
    );

    setBackfillSteps(steps);
    setBackfillState({ running: true, message: 'Backfill in progress...', error: null, lastResult: null });

    // Simulate progress through steps (since backend doesn't provide real-time progress)
    const simulateProgress = async () => {
      const stepDuration = 800; // ms per step
      for (let i = 0; i < steps.length; i++) {
        await new Promise((resolve) => setTimeout(resolve, stepDuration));
        setBackfillSteps((prev) =>
          prev.map((step, idx) =>
            idx === i
              ? { ...step, status: 'in_progress' }
              : idx < i
              ? { ...step, status: 'completed' }
              : step
          )
        );
      }
    };

    // Start simulated progress
    const progressPromise = simulateProgress();

    try {
      const result = await runTraceabilityBackfill(projectId, { includeConfluence, includeGit });

      // Wait for progress animation to complete
      await progressPromise;

      // Mark all steps as completed
      setBackfillSteps((prev) =>
        prev.map((step) => ({ ...step, status: 'completed', total: step.id === 'links' ? result.created + result.updated : undefined }))
      );

      const gitSummary = result.git;
      let gitMessage = '';
      if (gitSummary) {
        if (gitSummary.error) {
          gitMessage = ` Git import error: ${gitSummary.error}`;
        } else {
          const repositories = gitSummary.repositories ?? [];
          const repoCount = repositories.length;
          if (repoCount > 0) {
            const commitLinks = repositories.reduce((sum, repo) => sum + (repo.commits?.links_created ?? 0), 0);
            const prLinks = repositories.reduce((sum, repo) => sum + (repo.pull_requests?.links_created ?? 0), 0);
            const totalLinks = commitLinks + prLinks;
            gitMessage = ` Git: ${repoCount} repo${repoCount === 1 ? '' : 's'}, ${totalLinks} link${totalLinks === 1 ? '' : 's'}.`;
          } else {
            gitMessage = ' Git repositories synced with no new links.';
          }
        }
      }

      // Close dialog after 1 second
      await new Promise((resolve) => setTimeout(resolve, 1000));

      setBackfillState({
        running: false,
        message: `Backfill complete: created ${result.created}, updated ${result.updated}.` + gitMessage,
        error: null,
        lastResult: result,
      });
      setBackfillSteps([]);
      await fetchMatrix({ force: true });
    } catch (err: any) {
      console.error('Traceability backfill failed', err);
      const detail = err?.response?.data?.detail ?? err?.message ?? 'Traceability backfill failed';
      setBackfillState({ running: false, error: detail });
      setBackfillSteps([]);
    }
  }, [fetchMatrix, includeConfluence, includeGit, projectId]);

  const nodeLookup = useMemo(() => {
    const map = new Map<number, TraceabilityFlowNode>();
    flowData?.nodes.forEach(node => {
      map.set(node.id, node);
    });
    return map;
  }, [flowData]);

  const outgoingEdgesMap = useMemo(() => {
    const map = new Map<number, TraceabilityFlowEdge[]>();
    flowData?.edges.forEach(edge => {
      const list = map.get(edge.from) ?? [];
      list.push(edge);
      map.set(edge.from, list);
    });
    return map;
  }, [flowData]);

  const incomingEdgesMap = useMemo(() => {
    const map = new Map<number, TraceabilityFlowEdge[]>();
    flowData?.edges.forEach(edge => {
      const list = map.get(edge.to) ?? [];
      list.push(edge);
      map.set(edge.to, list);
    });
    return map;
  }, [flowData]);

  const groupedFlowColumns = useMemo(() => {
    if (!flowData || flowRootId === null) return [];
    const depthMap = new Map<number, number>();
    const queue: number[] = [];
    depthMap.set(flowRootId, 0);
    queue.push(flowRootId);
    while (queue.length) {
      const current = queue.shift()!;
      const depth = depthMap.get(current) ?? 0;
      const edges = outgoingEdgesMap.get(current) ?? [];
      edges.forEach(edge => {
        if (!depthMap.has(edge.to)) {
          depthMap.set(edge.to, depth + 1);
          queue.push(edge.to);
        }
      });
    }
    flowData.nodes.forEach(node => {
      if (!depthMap.has(node.id)) {
        depthMap.set(node.id, 0);
      }
    });
    const columns = new Map<number, TraceabilityFlowNode[]>();
    depthMap.forEach((depth, nodeId) => {
      const node = nodeLookup.get(nodeId);
      if (!node) return;
      const list = columns.get(depth) ?? [];
      list.push(node);
      columns.set(depth, list);
    });
    return Array.from(columns.entries())
      .sort((a, b) => a[0] - b[0])
      .map(([depth, nodes]) => ({
        depth,
        nodes: nodes.sort((a, b) => (a.title || `Artifact ${a.id}`).localeCompare(b.title || `Artifact ${b.id}`)),
      }));
  }, [flowData, flowRootId, nodeLookup, outgoingEdgesMap]);

  const getNodeLabel = useCallback(
    (node?: TraceabilityFlowNode | null) => {
      if (!node) return 'Unknown artifact';
      return node.title || node.type || `Artifact ${node.id}`;
    },
    []
  );

  const loadFlowByArtifactId = useCallback(
    async (artifactId: number) => {
      if (!artifactId || Number.isNaN(artifactId)) {
        setFlowError('Provide a valid artifact ID.');
        return;
      }
      setFlowLoading(true);
      setFlowError(null);
      try {
        const data = await getTraceabilityRequirementFlow(artifactId, { depth: flowDepth });
        setFlowData(data);
        setFlowRootId(artifactId);
        setSelectedNodeId(artifactId);
      } catch (err: any) {
        console.error('Failed to load requirement flow', err);
        const detail = err?.response?.data?.detail ?? err?.message ?? 'Failed to load requirement flow';
        setFlowError(detail);
      } finally {
        setFlowLoading(false);
      }
    },
    [flowDepth]
  );

  const handleLoadByArtifact = useCallback(() => {
    if (!artifactInput.trim()) {
      setFlowError('Enter an artifact ID to explore the graph.');
      return;
    }
    const parsed = Number(artifactInput);
    loadFlowByArtifactId(parsed);
  }, [artifactInput, loadFlowByArtifactId]);

  const handleLoadByJiraKey = useCallback(async () => {
    const key = jiraKeyInput.trim();
    if (!key) {
      setFlowError('Enter a Jira issue key to resolve the artifact.');
      return;
    }
    setFlowLoading(true);
    setFlowError(null);
    try {
      const neighbors = await getTraceabilityTaskArtifacts(key);
      const artifactId = neighbors.task_artifact?.id;
      if (!artifactId) {
        setFlowError('No artifact found for the provided Jira key. Run the backfill first.');
        setFlowLoading(false);
        return;
      }
      setArtifactInput(String(artifactId));
      const data = await getTraceabilityRequirementFlow(artifactId, { depth: flowDepth });
      setFlowData(data);
      setFlowRootId(artifactId);
      setSelectedNodeId(artifactId);
    } catch (err: any) {
      console.error('Failed to resolve Jira key', err);
      const detail = err?.response?.data?.detail ?? err?.message ?? 'Failed to resolve Jira key';
      setFlowError(detail);
    } finally {
      setFlowLoading(false);
    }
  }, [flowDepth, jiraKeyInput]);

  useEffect(() => {
    if (flowRootId !== null) {
      loadFlowByArtifactId(flowRootId);
    }
    // eslint-disable-next-line react-hooks-exhaustive-deps
  }, [flowDepth]);

  const selectedNode = useMemo(() => {
    if (!flowData || selectedNodeId === null) return null;
    return flowData.nodes.find(node => node.id === selectedNodeId) ?? null;
  }, [flowData, selectedNodeId]);

  const selectedOutgoing = useMemo(() => {
    if (!flowData || selectedNodeId === null) return [];
    return flowData.edges.filter(edge => edge.from === selectedNodeId);
  }, [flowData, selectedNodeId]);

  const selectedIncoming = useMemo(() => {
    if (!flowData || selectedNodeId === null) return [];
    return flowData.edges.filter(edge => edge.to === selectedNodeId);
  }, [flowData, selectedNodeId]);

  const formatConfidence = (value?: number | null) => {
    if (value === undefined || value === null) return 'N/A';
    const pct = Math.round(value * 100);
    return `${pct}%`;
  };

  const coverageChipColor = (pct: number): 'success' | 'warning' | 'error' => {
    if (pct >= 80) return 'success';
    if (pct >= 50) return 'warning';
    return 'error';
  };

  const hasAlerts = Boolean(projectsError || matrixError || backfillState.error || backfillState.message);
  const showEmptyState = !matrixLoading && !matrixHasData;

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Traceability
      </Typography>
      <Typography variant="body1" color="text.secondary">
        Monitor end-to-end linkage between requirements, delivery work, and validations. Run a backfill to populate artifacts, then track coverage and gaps by artifact type.
      </Typography>

      {hasAlerts && (
        <Stack spacing={1} sx={{ mt: 2 }}>
          {projectsError && <Alert severity="error">{projectsError}</Alert>}
          {matrixError && <Alert severity="error">{matrixError}</Alert>}
          {backfillState.error && <Alert severity="error">{backfillState.error}</Alert>}
          {backfillState.message && !backfillState.error && <Alert severity="success">{backfillState.message}</Alert>}
        </Stack>
      )}

      <Grid container spacing={2} sx={{ mt: 2 }}>
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 2, display: 'flex', flexDirection: 'column', gap: 2, height: '100%' }}>
            <Box>
              <Typography variant="h6" gutterBottom>
                Project scope
              </Typography>
              <FormControl size="small" fullWidth disabled={projectsLoading || projects.length === 0}>
                <InputLabel id="traceability-project-label">Project</InputLabel>
                <Select
                  labelId="traceability-project-label"
                  label="Project"
                  value={projects.length === 0 ? 'all' : projectId}
                  onChange={event => setProjectId(event.target.value as number | 'all')}
                >
                  <MenuItem value="all">All projects</MenuItem>
                  {projects.map(project => (
                    <MenuItem key={project.id} value={project.id}>
                      {project.name || project.jira_key || `Project ${project.id}`}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              {projectsLoading && <LinearProgress sx={{ mt: 2 }} />}
            </Box>

            <FormControlLabel
              control={
                <Switch
                  size="small"
                  checked={includeConfluence}
                  onChange={event => setIncludeConfluence(event.target.checked)}
                  disabled={backfillState.running}
                />
              }
              label="Include Confluence pages"
            />
            <FormControlLabel
              control={
                <Switch
                  size="small"
                  checked={includeGit}
                  onChange={event => setIncludeGit(event.target.checked)}
                  disabled={backfillState.running}
                />
              }
              label="Include Git repositories"
            />

            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
              <Button
                variant="contained"
                color="primary"
                fullWidth
                startIcon={backfillState.running ? <CircularProgress size={18} color="inherit" /> : <SyncIcon />}
                onClick={handleBackfill}
                disabled={backfillState.running || typeof projectId !== 'number'}
              >
                Run backfill
              </Button>
              <Button
                variant="outlined"
                fullWidth
                startIcon={<RefreshIcon />}
                onClick={handleRefresh}
                disabled={matrixLoading}
              >
                Refresh
              </Button>
            </Stack>

            {selectedProject && (
              <Typography variant="caption" color="text.secondary">
                Jira key: {selectedProject.jira_key}
              </Typography>
            )}
            {typeof projectId !== 'number' && (
              <Typography variant="caption" color="text.secondary">
                Select a project to enable backfill and deeper analysis.
              </Typography>
            )}
          </Paper>
        </Grid>

        <Grid item xs={12} md={8}>
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
                    title="Traceability Requires Setup"
                    description={
                      <Box>
                        <Typography variant="body1" paragraph>
                          You have {matrix?.total || 0} artifacts but no links detected yet.
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                          Click "Run Backfill" to analyze smart-commit parsing, Confluence references, and Git relationships.
                        </Typography>
                      </Box>
                    }
                    primaryAction={{
                      label: 'Run Backfill Analysis',
                      onClick: handleBackfill,
                    }}
                    benefits={[
                      'Smart-commit parsing (JIRA-123 in commits)',
                      'Confluence → Jira ticket references',
                      'Git commits → Pull requests → Tests',
                      'Expected result: 40-60% automatic coverage',
                    ]}
                    setupSteps={[
                      'Ensure Jira sync has completed',
                      'Click "Run Backfill Analysis" button',
                      'Wait ~5-10 minutes for analysis to complete',
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
                            No artifacts yet. Backfill will populate Jira issues, commits, and documentation references.
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
        </Grid>
      </Grid>

      <Box sx={{ mt: 3 }}>
        <Paper sx={{ p: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
          <Box display="flex" alignItems="center" justifyContent="space-between">
            <Typography variant="h6">Flow explorer</Typography>
            {flowLoading && <LinearProgress sx={{ width: 180 }} />}
          </Box>
          <Typography variant="body2" color="text.secondary">
            Drill into a specific requirement or Jira issue to visualize its downstream links. You can enter an artifact ID directly or resolve it via a Jira issue key after running the backfill.
          </Typography>

          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ xs: 'stretch', sm: 'flex-end' }}>
            <TextField
              fullWidth
              label="Artifact ID"
              size="small"
              value={artifactInput}
              onChange={event => setArtifactInput(event.target.value)}
              placeholder="e.g. 101"
              disabled={flowLoading}
            />
            <Button
              variant="contained"
              startIcon={<TravelExploreIcon />}
              onClick={handleLoadByArtifact}
              disabled={flowLoading}
            >
              Load by ID
            </Button>
          </Stack>

          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ xs: 'stretch', sm: 'flex-end' }}>
            <TextField
              fullWidth
              label="Jira issue key"
              size="small"
              value={jiraKeyInput}
              onChange={event => setJiraKeyInput(event.target.value)}
              placeholder="e.g. TEAM-123"
              disabled={flowLoading}
            />
            <Button
              variant="outlined"
              onClick={handleLoadByJiraKey}
              disabled={flowLoading}
            >
              Resolve & load
            </Button>
          </Stack>

          <Stack direction="row" spacing={2} alignItems="center">
            <TextField
              label="Depth"
              type="number"
              size="small"
              value={flowDepth}
              onChange={event => {
                const value = Number(event.target.value);
                if (Number.isNaN(value)) return;
                const clamped = Math.min(Math.max(Math.floor(value), 1), 8);
                setFlowDepth(clamped);
              }}
              inputProps={{ min: 1, max: 8 }}
              sx={{ width: 120 }}
              disabled={flowLoading}
            />
            {flowRootId !== null && (
              <Typography variant="caption" color="text.secondary">
                Currently exploring artifact {flowRootId}
              </Typography>
            )}
          </Stack>

          {flowError && <Alert severity="error">{flowError}</Alert>}

          {!flowData && !flowLoading && (
            <Typography variant="body2" color="text.secondary">
              Select an artifact to render the flow graph.
            </Typography>
          )}

          {flowData && groupedFlowColumns.length > 0 && (
            <>
              <Divider />
              <Grid container spacing={2}>
                {groupedFlowColumns.map(column => {
                  const columnSpan = Math.max(Math.floor(12 / Math.max(groupedFlowColumns.length, 1)), 3);
                  return (
                    <Grid item xs={12} md={columnSpan} key={column.depth}>
                      <Stack spacing={1.5}>
                        <Typography variant="subtitle2" color="text.secondary">
                          Depth {column.depth}
                        </Typography>
                        {column.nodes.map(node => {
                          const outgoing = outgoingEdgesMap.get(node.id) ?? [];
                          const isSelected = selectedNodeId === node.id;
                          return (
                            <Paper
                              key={node.id}
                              variant={isSelected ? 'outlined' : 'elevation'}
                              onClick={() => setSelectedNodeId(node.id)}
                              sx={{
                                p: 1.5,
                                borderColor: isSelected ? 'primary.main' : undefined,
                                cursor: 'pointer',
                                transition: 'border-color 0.2s ease',
                              }}
                            >
                              <Stack spacing={0.5}>
                                <Typography variant="subtitle2">{getNodeLabel(node)}</Typography>
                                <Stack direction="row" spacing={1}>
                                  {node.type && <Chip size="small" label={node.type} variant="outlined" />}
                                  {node.status && <Chip size="small" label={node.status} color="info" variant="outlined" />}
                                </Stack>
                                {outgoing.length > 0 ? (
                                  <Stack direction="row" spacing={0.5} flexWrap="wrap">
                                    {outgoing.slice(0, 3).map(edge => (
                                      <Chip
                                        key={`${node.id}-${edge.to}-${edge.type}`}
                                        size="small"
                                        variant="outlined"
                                        label={`${edge.type} > ${getNodeLabel(nodeLookup.get(edge.to))}`}
                                      />
                                    ))}
                                    {outgoing.length > 3 && (
                                      <Chip size="small" variant="outlined" label={`+${outgoing.length - 3} more`} />
                                    )}
                                  </Stack>
                                ) : (
                                  <Typography variant="caption" color="text.secondary">
                                    No outgoing links at this depth
                                  </Typography>
                                )}
                              </Stack>
                            </Paper>
                          );
                        })}
                      </Stack>
                    </Grid>
                  );
                })}
              </Grid>

              <Divider sx={{ my: 2 }} />

              {selectedNode ? (
                <Box>
                  <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', sm: 'center' }} spacing={1}>
                    <Box>
                      <Typography variant="h6">Drilldown</Typography>
                      <Typography variant="subtitle1">{getNodeLabel(selectedNode)}</Typography>
                      <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                        {selectedNode.type && <Chip size="small" label={selectedNode.type} variant="outlined" />}
                        {selectedNode.status && <Chip size="small" label={selectedNode.status} color="info" variant="outlined" />}
                      </Stack>
                    </Box>
                    <Button
                      startIcon={<AltRouteIcon />}
                      variant="outlined"
                      onClick={() => loadFlowByArtifactId(selectedNode.id)}
                    >
                      Explore from this node
                    </Button>
                  </Stack>

                  <Grid container spacing={2} sx={{ mt: 1 }}>
                    <Grid item xs={12} md={6}>
                      <Typography variant="subtitle2">Outgoing links</Typography>
                      {selectedOutgoing.length === 0 ? (
                        <Typography variant="body2" color="text.secondary">
                          No outgoing links within the selected depth.
                        </Typography>
                      ) : (
                        <Stack spacing={1} sx={{ mt: 1 }}>
                          {selectedOutgoing.map(edge => {
                            const target = nodeLookup.get(edge.to);
                            return (
                              <Paper key={`${edge.from}-${edge.to}-${edge.type}`} variant="outlined" sx={{ p: 1.5 }}>
                                <Stack spacing={0.5}>
                                  <Stack direction="row" spacing={1} alignItems="center">
                                    <Chip size="small" label={edge.type} color="primary" variant="outlined" />
                                    <Typography variant="body2">{getNodeLabel(target)}</Typography>
                                  </Stack>
                                  <Typography variant="caption" color="text.secondary">
                                    Confidence: {formatConfidence(edge.confidence)}
                                  </Typography>
                                </Stack>
                              </Paper>
                            );
                          })}
                        </Stack>
                      )}
                    </Grid>
                    <Grid item xs={12} md={6}>
                      <Typography variant="subtitle2">Incoming links (within depth)</Typography>
                      {selectedIncoming.length === 0 ? (
                        <Typography variant="body2" color="text.secondary">
                          No incoming links captured for this branch.
                        </Typography>
                      ) : (
                        <Stack spacing={1} sx={{ mt: 1 }}>
                          {selectedIncoming.map(edge => {
                            const source = nodeLookup.get(edge.from);
                            return (
                              <Paper key={`${edge.from}-${edge.to}-${edge.type}-incoming`} variant="outlined" sx={{ p: 1.5 }}>
                                <Stack spacing={0.5}>
                                  <Stack direction="row" spacing={1} alignItems="center">
                                    <Chip size="small" label={edge.type} color="secondary" variant="outlined" />
                                    <Typography variant="body2">{getNodeLabel(source)}</Typography>
                                  </Stack>
                                  <Typography variant="caption" color="text.secondary">
                                    Confidence: {formatConfidence(edge.confidence)}
                                  </Typography>
                                </Stack>
                              </Paper>
                            );
                          })}
                        </Stack>
                      )}
                    </Grid>
                  </Grid>
                </Box>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  Select a node to inspect link details and drill further.
                </Typography>
              )}
            </>
          )}
        </Paper>
      </Box>

      {/* Backfill Progress Dialog */}
      <BackfillProgressDialog
        open={backfillState.running && backfillSteps.length > 0}
        steps={backfillSteps}
      />
    </Box>
  );
};

export default Traceability;
