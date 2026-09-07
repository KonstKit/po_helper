import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  Grid,
  LinearProgress,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import TravelExploreIcon from '@mui/icons-material/TravelExplore';
import AltRouteIcon from '@mui/icons-material/AltRoute';
import {
  TraceabilityFlowEdge,
  TraceabilityFlowNode,
  TraceabilityRequirementFlow,
  getTraceabilityRequirementFlow,
  getTraceabilityTaskArtifacts,
} from '../../services/api';
import { getErrorMessage, logError } from '../../utils/errorUtils';
import { formatConfidence } from './traceabilityUtils';

/**
 * Flow explorer extracted from pages/Traceability.tsx.
 * Self-contained: owns the requirement-flow state (artifact / Jira key /
 * depth inputs, loaded graph, selected node) and its column layout.
 */
const FlowExplorer: React.FC = () => {
  const [artifactInput, setArtifactInput] = useState('');
  const [jiraKeyInput, setJiraKeyInput] = useState('');
  const [flowDepth, setFlowDepth] = useState(3);
  const [flowData, setFlowData] = useState<TraceabilityRequirementFlow | null>(null);
  const [flowRootId, setFlowRootId] = useState<number | null>(null);
  const [flowLoading, setFlowLoading] = useState(false);
  const [flowError, setFlowError] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);

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
      } catch (err: unknown) {
        logError('Failed to load requirement flow', err);
        setFlowError(getErrorMessage(err, 'Failed to load requirement flow'));
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
        setFlowError(
          'No traceability artifact exists for that Jira key yet. Sync the project first, then run traceability repair for legacy data if needed.'
        );
        setFlowLoading(false);
        return;
      }
      setArtifactInput(String(artifactId));
      const data = await getTraceabilityRequirementFlow(artifactId, { depth: flowDepth });
      setFlowData(data);
      setFlowRootId(artifactId);
      setSelectedNodeId(artifactId);
    } catch (err: unknown) {
      logError('Failed to resolve Jira key', err);
      setFlowError(getErrorMessage(err, 'Failed to resolve Jira key'));
    } finally {
      setFlowLoading(false);
    }
  }, [flowDepth, jiraKeyInput]);

  useEffect(() => {
    if (flowRootId !== null) {
      loadFlowByArtifactId(flowRootId);
    }
  }, [flowDepth, flowRootId, loadFlowByArtifactId]);

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

  return (
    <Box sx={{ mt: 3 }}>
      <Paper sx={{ p: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
        <Box display="flex" alignItems="center" justifyContent="space-between">
          <Typography variant="h6">Flow explorer</Typography>
          {flowLoading && <LinearProgress sx={{ width: 180 }} />}
        </Box>
        <Typography variant="body2" color="text.secondary">
          Drill into a specific requirement or Jira issue to visualize downstream links. You can enter an artifact ID directly or resolve it via a Jira issue key after source sync or traceability repair.
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
    );
};

export default FlowExplorer;
