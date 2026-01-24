import React, { useEffect, useRef, useState, useCallback } from 'react';
import * as d3 from 'd3';
import {
  Box,
  Paper,
  Typography,
  CircularProgress,
  Alert,
  Chip,
  Slider,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  IconButton,
  Tooltip,
  Stack,
  Divider,
} from '@mui/material';
import type { SelectChangeEvent } from '@mui/material/Select';
import {
  ZoomIn,
  ZoomOut,
  CenterFocusStrong,
  Refresh,
  OpenInNew,
} from '@mui/icons-material';
import {
  getFullTraceabilityChain,
  FullChainNode,
  FullChainResponse,
} from '../../services/api';
import { getErrorMessage } from '../../utils/errorUtils';

interface TraceabilityGraphProps {
  artifactId: number;
  /** Minimum height for the graph container (default: 500) */
  minHeight?: number;
  onNodeClick?: (node: FullChainNode) => void;
}

interface D3Node extends d3.SimulationNodeDatum {
  id: number;
  type: string;
  source: string;
  external_id: string;
  display_key?: string | null;
  title?: string | null;
  status?: string | null;
  url?: string | null;
  level: number;
}

interface D3Link extends d3.SimulationLinkDatum<D3Node> {
  source: D3Node;
  target: D3Node;
  link_type: string;
  confidence?: number | null;
  confidence_factors?: Record<string, unknown> | null;
}

interface D3LinkInput {
  sourceId: number;
  targetId: number;
  link_type: string;
  confidence?: number | null;
  confidence_factors?: Record<string, unknown> | null;
}

const TYPE_COLORS: Record<string, string> = {
  requirement: '#2196F3',
  jira_issue: '#FF9800',
  confluence_page: '#4CAF50',
  commit: '#9C27B0',
  pr: '#E91E63',
  pipeline: '#00BCD4',
  deployment: '#795548',
  test_case: '#8BC34A',
  test_run: '#CDDC39',
  default: '#9E9E9E',
};

const LINK_TYPE_STYLES: Record<string, { color: string; dasharray: string }> = {
  implements: { color: '#4CAF50', dasharray: '' },
  tests: { color: '#2196F3', dasharray: '' },
  deploys: { color: '#FF9800', dasharray: '5,5' },
  derives_from: { color: '#9C27B0', dasharray: '3,3' },
  relates_to: { color: '#9E9E9E', dasharray: '2,2' },
  blocks: { color: '#F44336', dasharray: '' },
};

const TraceabilityGraph: React.FC<TraceabilityGraphProps> = ({
  artifactId,
  minHeight = 500,
  onNodeClick,
}) => {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<FullChainResponse | null>(null);
  const [depth, setDepth] = useState(3);
  const [direction, setDirection] = useState<'both' | 'upstream' | 'downstream'>('both');
  const [minConfidence, setMinConfidence] = useState(0);
  const [hoveredNode, setHoveredNode] = useState<D3Node | null>(null);
  const [dimensions, setDimensions] = useState({ width: 900, height: 600 });

  // Responsive: observe container size changes
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const updateDimensions = () => {
      const rect = container.getBoundingClientRect();
      const newWidth = Math.max(rect.width, 400);
      const newHeight = Math.max(rect.height || minHeight, minHeight);
      setDimensions({ width: newWidth, height: newHeight });
    };

    // Initial measurement
    updateDimensions();

    // Observe resize
    const resizeObserver = new ResizeObserver(updateDimensions);
    resizeObserver.observe(container);

    return () => resizeObserver.disconnect();
  }, [minHeight]);

  const handleDirectionChange = (event: SelectChangeEvent) => {
    const value = event.target.value;
    if (value === 'both' || value === 'upstream' || value === 'downstream') {
      setDirection(value);
    }
  };

  const handleDepthChange = (_: Event, value: number | number[]) => {
    if (!Array.isArray(value)) {
      setDepth(value);
    }
  };

  const handleMinConfidenceChange = (_: Event, value: number | number[]) => {
    if (!Array.isArray(value)) {
      setMinConfidence(value);
    }
  };

  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await getFullTraceabilityChain(artifactId, {
        depth,
        direction,
        minConfidence,
        includeFactors: true,
      });
      setData(response);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to load traceability chain'));
    } finally {
      setLoading(false);
    }
  }, [artifactId, depth, direction, minConfidence]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (!data || !svgRef.current) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const nodes: D3Node[] = data.nodes.map((n) => ({ ...n }));
    const links: D3LinkInput[] = data.edges.map((e) => ({
      sourceId: e.from_id,
      targetId: e.to_id,
      link_type: e.link_type,
      confidence: e.confidence,
      confidence_factors: e.confidence_factors,
    }));

    const nodeById = new Map(nodes.map((n) => [n.id, n]));

    // Fix links to reference actual nodes
    const validLinks = links.reduce<D3Link[]>((acc, link) => {
      const source = nodeById.get(link.sourceId);
      const target = nodeById.get(link.targetId);
      if (source && target) {
        acc.push({ ...link, source, target });
      }
      return acc;
    }, []);

    // Create SVG groups
    const g = svg.append('g').attr('class', 'graph-container');

    // Zoom behavior
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 4])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });

    svg.call(zoom);
    zoomRef.current = zoom;

    // Arrow markers for links
    const defs = svg.append('defs');
    Object.entries(LINK_TYPE_STYLES).forEach(([type, style]) => {
      defs.append('marker')
        .attr('id', `arrow-${type}`)
        .attr('viewBox', '0 -5 10 10')
        .attr('refX', 20)
        .attr('refY', 0)
        .attr('markerWidth', 6)
        .attr('markerHeight', 6)
        .attr('orient', 'auto')
        .append('path')
        .attr('fill', style.color)
        .attr('d', 'M0,-5L10,0L0,5');
    });

    // Force simulation
    const { width, height } = dimensions;
    const simulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink<D3Node, D3Link>(validLinks)
        .id((d) => d.id)
        .distance(120)
        .strength(0.5))
      .force('charge', d3.forceManyBody().strength(-400))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('x', d3.forceX<D3Node>()
        .x((d) => width / 2 + d.level * 150)
        .strength(0.3))
      .force('y', d3.forceY(height / 2).strength(0.1))
      .force('collision', d3.forceCollide().radius(50));

    // Links
    const linkGroup = g.append('g').attr('class', 'links');
    const link = linkGroup.selectAll('line')
      .data(validLinks)
      .enter()
      .append('line')
      .attr('stroke', (d) => {
        const style = LINK_TYPE_STYLES[d.link_type] || LINK_TYPE_STYLES.relates_to;
        return style.color;
      })
      .attr('stroke-dasharray', (d) => {
        const style = LINK_TYPE_STYLES[d.link_type] || LINK_TYPE_STYLES.relates_to;
        return style.dasharray;
      })
      .attr('stroke-width', (d) => {
        const conf = d.confidence ?? 0.5;
        return 1 + conf * 3;
      })
      .attr('stroke-opacity', (d) => 0.4 + (d.confidence ?? 0.5) * 0.6)
      .attr('marker-end', (d) => `url(#arrow-${d.link_type})`);

    // Link labels (confidence)
    const linkLabelGroup = g.append('g').attr('class', 'link-labels');
    const linkLabel = linkLabelGroup.selectAll('text')
      .data(validLinks.filter((l) => l.confidence !== null && l.confidence !== undefined))
      .enter()
      .append('text')
      .attr('font-size', 10)
      .attr('fill', '#666')
      .attr('text-anchor', 'middle')
      .text((d) => `${Math.round((d.confidence ?? 0) * 100)}%`);

    // Node groups
    const nodeGroup = g.append('g').attr('class', 'nodes');
    const node = nodeGroup.selectAll('g')
      .data(nodes)
      .enter()
      .append('g')
      .attr('class', 'node')
      .style('cursor', 'pointer')
      .call(d3.drag<SVGGElement, D3Node>()
        .on('start', (event, d) => {
          if (!event.active) simulation.alphaTarget(0.3).restart();
          d.fx = d.x;
          d.fy = d.y;
        })
        .on('drag', (event, d) => {
          d.fx = event.x;
          d.fy = event.y;
        })
        .on('end', (event, d) => {
          if (!event.active) simulation.alphaTarget(0);
          d.fx = null;
          d.fy = null;
        }));

    // Node circles
    node.append('circle')
      .attr('r', (d) => d.id === artifactId ? 25 : 20)
      .attr('fill', (d) => TYPE_COLORS[d.type] || TYPE_COLORS.default)
      .attr('stroke', (d) => d.id === artifactId ? '#FFD700' : '#fff')
      .attr('stroke-width', (d) => d.id === artifactId ? 4 : 2)
      .attr('opacity', 0.9);

    // Type icon (first letter)
    node.append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', '0.35em')
      .attr('fill', '#fff')
      .attr('font-size', 12)
      .attr('font-weight', 'bold')
      .text((d) => d.type.charAt(0).toUpperCase());

    // Node labels
    node.append('text')
      .attr('dy', 35)
      .attr('text-anchor', 'middle')
      .attr('font-size', 11)
      .attr('fill', '#333')
      .text((d) => d.display_key || d.external_id || `#${d.id}`);

    // Title (truncated)
    node.append('text')
      .attr('dy', 48)
      .attr('text-anchor', 'middle')
      .attr('font-size', 9)
      .attr('fill', '#666')
      .text((d) => {
        const title = d.title || '';
        return title.length > 25 ? title.substring(0, 22) + '...' : title;
      });

    // Hover effects
    node
      .on('mouseenter', (event, d) => {
        setHoveredNode(d);
        d3.select(event.currentTarget).select('circle')
          .transition()
          .duration(200)
          .attr('r', d.id === artifactId ? 30 : 25);
      })
      .on('mouseleave', (event, d) => {
        setHoveredNode(null);
        d3.select(event.currentTarget).select('circle')
          .transition()
          .duration(200)
          .attr('r', d.id === artifactId ? 25 : 20);
      })
      .on('click', (event, d) => {
        onNodeClick?.(d);
      });

    // Simulation tick
    simulation.on('tick', () => {
      link
        .attr('x1', (d) => d.source.x!)
        .attr('y1', (d) => d.source.y!)
        .attr('x2', (d) => d.target.x!)
        .attr('y2', (d) => d.target.y!);

      linkLabel
        .attr('x', (d) => (d.source.x! + d.target.x!) / 2)
        .attr('y', (d) => (d.source.y! + d.target.y!) / 2);

      node.attr('transform', (d) => `translate(${d.x},${d.y})`);
    });

    // Initial zoom to fit
    setTimeout(() => {
      const groupNode = g.node();
      if (groupNode) {
        const bounds = groupNode.getBBox();
        const bWidth = bounds.width;
        const bHeight = bounds.height;
        const scale = Math.min(
          0.9 * width / bWidth,
          0.9 * height / bHeight,
          1.5
        );
        const tx = (width - bWidth * scale) / 2 - bounds.x * scale;
        const ty = (height - bHeight * scale) / 2 - bounds.y * scale;
        svg.transition()
          .duration(500)
          .call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
      }
    }, 500);

    return () => {
      simulation.stop();
    };
  }, [data, dimensions, artifactId, onNodeClick]);

  const handleZoomIn = () => {
    if (svgRef.current && zoomRef.current) {
      d3.select(svgRef.current)
        .transition()
        .call(zoomRef.current.scaleBy, 1.3);
    }
  };

  const handleZoomOut = () => {
    if (svgRef.current && zoomRef.current) {
      d3.select(svgRef.current)
        .transition()
        .call(zoomRef.current.scaleBy, 0.7);
    }
  };

  const handleResetZoom = () => {
    if (svgRef.current && zoomRef.current) {
      d3.select(svgRef.current)
        .transition()
        .call(zoomRef.current.transform, d3.zoomIdentity);
    }
  };

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" height={minHeight}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Alert severity="error" sx={{ m: 2 }}>
        {error}
      </Alert>
    );
  }

  return (
    <Box ref={containerRef} sx={{ width: '100%' }}>
      {/* Controls */}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Stack direction="row" spacing={3} alignItems="center" flexWrap="wrap">
          <FormControl size="small" sx={{ minWidth: 120 }}>
            <InputLabel>Direction</InputLabel>
            <Select
              value={direction}
              label="Direction"
              onChange={handleDirectionChange}
            >
              <MenuItem value="both">Both</MenuItem>
              <MenuItem value="upstream">Upstream</MenuItem>
              <MenuItem value="downstream">Downstream</MenuItem>
            </Select>
          </FormControl>

          <Box sx={{ width: 150 }}>
            <Typography variant="caption" color="text.secondary">
              Depth: {depth}
            </Typography>
            <Slider
              value={depth}
              onChange={handleDepthChange}
              min={1}
              max={10}
              step={1}
              size="small"
            />
          </Box>

          <Box sx={{ width: 180 }}>
            <Typography variant="caption" color="text.secondary">
              Min Confidence: {Math.round(minConfidence * 100)}%
            </Typography>
            <Slider
              value={minConfidence}
              onChange={handleMinConfidenceChange}
              min={0}
              max={1}
              step={0.1}
              size="small"
            />
          </Box>

          <Divider orientation="vertical" flexItem />

          <Stack direction="row" spacing={1}>
            <Tooltip title="Zoom In">
              <IconButton size="small" onClick={handleZoomIn}>
                <ZoomIn />
              </IconButton>
            </Tooltip>
            <Tooltip title="Zoom Out">
              <IconButton size="small" onClick={handleZoomOut}>
                <ZoomOut />
              </IconButton>
            </Tooltip>
            <Tooltip title="Reset View">
              <IconButton size="small" onClick={handleResetZoom}>
                <CenterFocusStrong />
              </IconButton>
            </Tooltip>
            <Tooltip title="Refresh">
              <IconButton size="small" onClick={fetchData}>
                <Refresh />
              </IconButton>
            </Tooltip>
          </Stack>

          {data && (
            <Stack direction="row" spacing={1}>
              <Chip
                size="small"
                label={`${data.stats.total_nodes} nodes`}
                variant="outlined"
              />
              <Chip
                size="small"
                label={`${data.stats.total_edges} links`}
                variant="outlined"
              />
            </Stack>
          )}
        </Stack>
      </Paper>

      {/* Graph */}
      <Paper sx={{ position: 'relative', overflow: 'hidden', minHeight }}>
        <svg
          ref={svgRef}
          width="100%"
          height={dimensions.height}
          viewBox={`0 0 ${dimensions.width} ${dimensions.height}`}
          preserveAspectRatio="xMidYMid meet"
          style={{ display: 'block', background: '#fafafa' }}
        />

        {/* Legend */}
        <Box
          sx={{
            position: 'absolute',
            bottom: 16,
            left: 16,
            bgcolor: 'rgba(255,255,255,0.95)',
            p: 1.5,
            borderRadius: 1,
            boxShadow: 1,
          }}
        >
          <Typography variant="caption" fontWeight="bold" display="block" mb={1}>
            Artifact Types
          </Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            {Object.entries(TYPE_COLORS)
              .filter(([k]) => k !== 'default')
              .slice(0, 6)
              .map(([type, color]) => (
                <Chip
                  key={type}
                  size="small"
                  label={type.replace('_', ' ')}
                  sx={{
                    bgcolor: color,
                    color: '#fff',
                    fontSize: 10,
                    height: 20,
                  }}
                />
              ))}
          </Stack>
        </Box>

        {/* Hovered Node Info */}
        {hoveredNode && (
          <Paper
            sx={{
              position: 'absolute',
              top: 16,
              right: 16,
              p: 2,
              maxWidth: 300,
              boxShadow: 3,
            }}
          >
            <Stack direction="row" alignItems="center" spacing={1} mb={1}>
              <Box
                sx={{
                  width: 12,
                  height: 12,
                  borderRadius: '50%',
                  bgcolor: TYPE_COLORS[hoveredNode.type] || TYPE_COLORS.default,
                }}
              />
              <Typography variant="subtitle2">
                {hoveredNode.display_key || hoveredNode.external_id}
              </Typography>
            </Stack>
            <Typography variant="body2" color="text.secondary" gutterBottom>
              {hoveredNode.title || 'No title'}
            </Typography>
            <Stack direction="row" spacing={1} mt={1}>
              <Chip size="small" label={hoveredNode.type} />
              {hoveredNode.status && (
                <Chip size="small" label={hoveredNode.status} variant="outlined" />
              )}
              <Chip
                size="small"
                label={`Level ${hoveredNode.level}`}
                variant="outlined"
              />
            </Stack>
            {hoveredNode.url && (
              <Box mt={1}>
                <IconButton
                  size="small"
                  href={hoveredNode.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <OpenInNew fontSize="small" />
                </IconButton>
              </Box>
            )}
          </Paper>
        )}
      </Paper>
    </Box>
  );
};

export default TraceabilityGraph;
