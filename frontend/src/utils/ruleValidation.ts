import { Edge, Node } from 'reactflow';

export interface ValidationResult {
  valid: boolean;
  errors: ValidationError[];
  warnings: ValidationWarning[];
}

export interface ValidationError {
  type: 'error';
  message: string;
  nodeId?: string;
  edgeId?: string;
}

export interface ValidationWarning {
  type: 'warning';
  message: string;
  nodeId?: string;
  edgeId?: string;
}

const SOURCE_NODE_TYPES = new Set([
  'commitSource',
  'jiraIssueSource',
  'confluenceSource',
  'testrailSource',
  'manualSource',
]);

const ACTION_NODE_TYPES = new Set([
  'createLinkAction',
  'queueReviewAction',
]);

const PROCESSOR_NODE_TYPES = new Set([
  'jiraKeyExtractor',
  'filterNode',
  'transformNode',
  'decisionNode',
]);

const DECISION_CONDITION_TYPES = new Set([
  'confidence_threshold',
  'count_threshold',
  'count_equals',
  'has_artifacts',
  'is_empty',
]);

export const SUPPORTED_TRANSFORM_TYPES: ReadonlySet<string> = new Set(['passthrough']);

const getNodeLabel = (node: Node): string =>
  String((node.data as Record<string, unknown>)?.label || node.id);

const getNodeConfig = (node: Node): Record<string, unknown> =>
  ((node.data as Record<string, unknown>)?.config as Record<string, unknown>) || {};

/**
 * Validates a traceability rule flow.
 */
export function validateRule(nodes: Node[], edges: Edge[]): ValidationResult {
  const errors: ValidationError[] = [];
  const warnings: ValidationWarning[] = [];

  const sourceNodes = nodes.filter((n) => SOURCE_NODE_TYPES.has(n.type || ''));
  if (sourceNodes.length === 0) {
    errors.push({
      type: 'error',
      message:
        'Rule must have at least one Source node (Commit, Jira Issue, Confluence, TestRail, or Manual)',
    });
  }

  const actionNodes = nodes.filter((n) => ACTION_NODE_TYPES.has(n.type || ''));
  if (actionNodes.length === 0) {
    errors.push({
      type: 'error',
      message: 'Rule must have at least one Action node (Create Link, Queue Review, etc.)',
    });
  }

  const connectedNodeIds = new Set<string>();
  edges.forEach((edge) => {
    connectedNodeIds.add(edge.source);
    connectedNodeIds.add(edge.target);
  });

  nodes.forEach((node) => {
    if (!connectedNodeIds.has(node.id) && nodes.length > 1) {
      warnings.push({
        type: 'warning',
        message: `Node "${getNodeLabel(node)}" is not connected to any other nodes`,
        nodeId: node.id,
      });
    }
  });

  const cycles = detectCycles(nodes, edges);
  if (cycles.length > 0) {
    errors.push({
      type: 'error',
      message: `Circular dependency detected: ${cycles.join(' -> ')}`,
    });
  }

  sourceNodes.forEach((node) => {
    const hasOutgoingEdge = edges.some((edge) => edge.source === node.id);
    if (!hasOutgoingEdge) {
      warnings.push({
        type: 'warning',
        message: `Source node "${getNodeLabel(node)}" has no outgoing connections`,
        nodeId: node.id,
      });
    }
  });

  actionNodes.forEach((node) => {
    const hasIncomingEdge = edges.some((edge) => edge.target === node.id);
    if (!hasIncomingEdge) {
      warnings.push({
        type: 'warning',
        message: `Action node "${getNodeLabel(node)}" has no incoming connections`,
        nodeId: node.id,
      });
    }
  });

  const processorNodes = nodes.filter((n) => PROCESSOR_NODE_TYPES.has(n.type || ''));
  processorNodes.forEach((node) => {
    const hasIncomingEdge = edges.some((edge) => edge.target === node.id);
    const hasOutgoingEdge = edges.some((edge) => edge.source === node.id);

    if (!hasIncomingEdge) {
      warnings.push({
        type: 'warning',
        message: `Processor node "${getNodeLabel(node)}" has no input`,
        nodeId: node.id,
      });
    }

    if (!hasOutgoingEdge) {
      warnings.push({
        type: 'warning',
        message: `Processor node "${getNodeLabel(node)}" has no output`,
        nodeId: node.id,
      });
    }
  });

  nodes.forEach((node) => {
    const { errors: nodeErrors, warnings: nodeWarnings } = validateNodeConfiguration(node);
    errors.push(...nodeErrors);
    warnings.push(...nodeWarnings);
  });

  return {
    valid: errors.length === 0,
    errors,
    warnings,
  };
}

/**
 * Validates individual node configuration.
 *
 * Returns both errors and warnings. The transform contract is advisory
 * here (warning only) so the frontend never disables Execute Rule for
 * legacy `transform_type` values during a rolling deploy where the
 * backend is running with `TRACEABILITY_TRANSFORM_STRICT=false`. The
 * backend remains the authoritative gate on save/execute in strict mode.
 */
function validateNodeConfiguration(
  node: Node,
): { errors: ValidationError[]; warnings: ValidationWarning[] } {
  const errors: ValidationError[] = [];
  const warnings: ValidationWarning[] = [];
  const config = getNodeConfig(node);
  const nodeLabel = getNodeLabel(node);

  switch (node.type) {
    case 'jiraKeyExtractor': {
      const searchIn = config.search_in;
      if (!Array.isArray(searchIn) || searchIn.length === 0) {
        errors.push({
          type: 'error',
          message: `Jira Key Extractor "${nodeLabel}" must have at least one search field selected`,
          nodeId: node.id,
        });
      }
      if (!config.pattern) {
        errors.push({
          type: 'error',
          message: `Jira Key Extractor "${nodeLabel}" must have a regex pattern`,
          nodeId: node.id,
        });
      }
      break;
    }

    case 'createLinkAction':
      if (!config.link_type) {
        errors.push({
          type: 'error',
          message: `Create Link action "${nodeLabel}" must have a link type`,
          nodeId: node.id,
        });
      }
      if (config.bidirectional && !config.reverse_link_type) {
        errors.push({
          type: 'error',
          message: `Create Link action "${nodeLabel}" with bidirectional enabled must specify reverse link type`,
          nodeId: node.id,
        });
      }
      break;

    case 'filterNode':
      if (!config.field) {
        errors.push({
          type: 'error',
          message: `Filter node "${nodeLabel}" must specify a field to filter on`,
          nodeId: node.id,
        });
      }
      if (!config.operator) {
        errors.push({
          type: 'error',
          message: `Filter node "${nodeLabel}" must specify an operator`,
          nodeId: node.id,
        });
      }
      break;

    case 'transformNode':
      if ('transform_type' in config) {
        const transformType = config.transform_type;
        if (typeof transformType !== 'string' || !SUPPORTED_TRANSFORM_TYPES.has(transformType)) {
          const supported = Array.from(SUPPORTED_TRANSFORM_TYPES).sort().join(', ');
          // Advisory only on the client. The backend is authoritative:
          // in strict mode it returns a 400 on save/execute, in non-strict
          // mode (rollout escape hatch) it warns and passes through. A
          // hard client error would let the FE disable Execute even when
          // the backend would have allowed the run.
          warnings.push({
            type: 'warning',
            message: `Transform node "${nodeLabel}" has unsupported transform_type "${String(transformType)}"; supported values: ${supported}. The backend rejects this in strict mode.`,
            nodeId: node.id,
          });
        }
      }
      break;

    case 'decisionNode': {
      const conditionType = String(config.condition_type || 'count_threshold');
      if (!DECISION_CONDITION_TYPES.has(conditionType)) {
        errors.push({
          type: 'error',
          message: `Decision node "${nodeLabel}" has unsupported condition type "${conditionType}"`,
          nodeId: node.id,
        });
        break;
      }

      if (
        conditionType === 'confidence_threshold' ||
        conditionType === 'count_threshold' ||
        conditionType === 'count_equals'
      ) {
        const threshold = Number(config.threshold);
        if (!Number.isFinite(threshold)) {
          errors.push({
            type: 'error',
            message: `Decision node "${nodeLabel}" must have a numeric threshold`,
            nodeId: node.id,
          });
          break;
        }

        if (conditionType === 'confidence_threshold' && (threshold < 0 || threshold > 100)) {
          errors.push({
            type: 'error',
            message: `Decision node "${nodeLabel}" confidence threshold must be between 0 and 100`,
            nodeId: node.id,
          });
        }
      }
      break;
    }

    default:
      break;
  }

  return { errors, warnings };
}

/**
 * Detects circular dependencies in the flow.
 */
function detectCycles(nodes: Node[], edges: Edge[]): string[] {
  const adjacencyList = new Map<string, string[]>();

  nodes.forEach((node) => adjacencyList.set(node.id, []));
  edges.forEach((edge) => {
    const targets = adjacencyList.get(edge.source) || [];
    targets.push(edge.target);
    adjacencyList.set(edge.source, targets);
  });

  const visited = new Set<string>();
  const recursionStack = new Set<string>();
  let cycle: string[] = [];

  function dfs(nodeId: string, path: string[]): boolean {
    visited.add(nodeId);
    recursionStack.add(nodeId);
    path.push(nodeId);

    const neighbors = adjacencyList.get(nodeId) || [];
    for (const neighbor of neighbors) {
      if (!visited.has(neighbor)) {
        if (dfs(neighbor, path)) {
          return true;
        }
      } else if (recursionStack.has(neighbor)) {
        const cycleStartIndex = path.indexOf(neighbor);
        cycle = path.slice(cycleStartIndex);
        cycle.push(neighbor);
        return true;
      }
    }

    recursionStack.delete(nodeId);
    path.pop();
    return false;
  }

  for (const node of nodes) {
    if (!visited.has(node.id) && dfs(node.id, [])) {
      return cycle.map((nodeId) => {
        const match = nodes.find((candidate) => candidate.id === nodeId);
        return getNodeLabel(match || node);
      });
    }
  }

  return [];
}

/**
 * Gets all source nodes in the flow.
 */
export function getSourceNodes(nodes: Node[]): Node[] {
  return nodes.filter((n) => SOURCE_NODE_TYPES.has(n.type || ''));
}

/**
 * Gets all action nodes in the flow.
 */
export function getActionNodes(nodes: Node[]): Node[] {
  return nodes.filter((n) => ACTION_NODE_TYPES.has(n.type || ''));
}

/**
 * Checks if the flow has a complete path from source to action.
 */
export function hasCompletePath(nodes: Node[], edges: Edge[]): boolean {
  const sourceNodes = getSourceNodes(nodes);
  const actionNodes = getActionNodes(nodes);

  if (sourceNodes.length === 0 || actionNodes.length === 0) {
    return false;
  }

  const adjacencyList = new Map<string, string[]>();
  nodes.forEach((node) => adjacencyList.set(node.id, []));
  edges.forEach((edge) => {
    const targets = adjacencyList.get(edge.source) || [];
    targets.push(edge.target);
    adjacencyList.set(edge.source, targets);
  });

  for (const source of sourceNodes) {
    const reachable = getReachableNodes(source.id, adjacencyList);
    for (const action of actionNodes) {
      if (reachable.has(action.id)) {
        return true;
      }
    }
  }

  return false;
}

/**
 * Gets all nodes reachable from a starting node.
 */
function getReachableNodes(startId: string, adjacencyList: Map<string, string[]>): Set<string> {
  const reachable = new Set<string>();
  const queue = [startId];

  while (queue.length > 0) {
    const current = queue.shift();
    if (!current || reachable.has(current)) {
      continue;
    }

    reachable.add(current);
    const neighbors = adjacencyList.get(current) || [];
    queue.push(...neighbors);
  }

  return reachable;
}
