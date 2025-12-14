import { Node, Edge } from 'reactflow';

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

/**
 * Validates a traceability rule flow
 */
export function validateRule(nodes: Node[], edges: Edge[]): ValidationResult {
  const errors: ValidationError[] = [];
  const warnings: ValidationWarning[] = [];

  // Rule 1: Must have at least one source node
  const sourceNodes = nodes.filter((n) =>
    ['commitSource', 'jiraIssueSource', 'confluenceSource'].includes(n.type || '')
  );
  if (sourceNodes.length === 0) {
    errors.push({
      type: 'error',
      message: 'Rule must have at least one Source node (Commit, Jira Issue, or Confluence)',
    });
  }

  // Rule 2: Must have at least one action node
  const actionNodes = nodes.filter((n) =>
    ['createLinkAction', 'queueReviewAction'].includes(n.type || '')
  );
  if (actionNodes.length === 0) {
    errors.push({
      type: 'error',
      message: 'Rule must have at least one Action node (Create Link, Queue Review, etc.)',
    });
  }

  // Rule 3: Check for disconnected nodes
  const connectedNodeIds = new Set<string>();
  edges.forEach((edge) => {
    connectedNodeIds.add(edge.source);
    connectedNodeIds.add(edge.target);
  });

  nodes.forEach((node) => {
    if (!connectedNodeIds.has(node.id) && nodes.length > 1) {
      warnings.push({
        type: 'warning',
        message: `Node "${node.data.label || node.id}" is not connected to any other nodes`,
        nodeId: node.id,
      });
    }
  });

  // Rule 4: Check for circular dependencies
  const cycles = detectCycles(nodes, edges);
  if (cycles.length > 0) {
    errors.push({
      type: 'error',
      message: `Circular dependency detected: ${cycles.join(' → ')}`,
    });
  }

  // Rule 5: Validate source nodes have outputs
  sourceNodes.forEach((node) => {
    const hasOutgoingEdge = edges.some((e) => e.source === node.id);
    if (!hasOutgoingEdge) {
      warnings.push({
        type: 'warning',
        message: `Source node "${node.data.label || node.id}" has no outgoing connections`,
        nodeId: node.id,
      });
    }
  });

  // Rule 6: Validate action nodes have inputs
  actionNodes.forEach((node) => {
    const hasIncomingEdge = edges.some((e) => e.target === node.id);
    if (!hasIncomingEdge) {
      warnings.push({
        type: 'warning',
        message: `Action node "${node.data.label || node.id}" has no incoming connections`,
        nodeId: node.id,
      });
    }
  });

  // Rule 7: Validate processor nodes have both inputs and outputs
  const processorNodes = nodes.filter((n) =>
    ['jiraKeyExtractor', 'filterNode', 'transformNode'].includes(n.type || '')
  );
  processorNodes.forEach((node) => {
    const hasIncomingEdge = edges.some((e) => e.target === node.id);
    const hasOutgoingEdge = edges.some((e) => e.source === node.id);

    if (!hasIncomingEdge) {
      warnings.push({
        type: 'warning',
        message: `Processor node "${node.data.label || node.id}" has no input`,
        nodeId: node.id,
      });
    }
    if (!hasOutgoingEdge) {
      warnings.push({
        type: 'warning',
        message: `Processor node "${node.data.label || node.id}" has no output`,
        nodeId: node.id,
      });
    }
  });

  // Rule 8: Validate node-specific configurations
  nodes.forEach((node) => {
    const nodeErrors = validateNodeConfiguration(node);
    errors.push(...nodeErrors);
  });

  return {
    valid: errors.length === 0,
    errors,
    warnings,
  };
}

/**
 * Validates individual node configuration
 */
function validateNodeConfiguration(node: Node): ValidationError[] {
  const errors: ValidationError[] = [];

  switch (node.type) {
    case 'jiraKeyExtractor':
      if (!node.data.config?.search_in || node.data.config.search_in.length === 0) {
        errors.push({
          type: 'error',
          message: `Jira Key Extractor "${node.data.label || node.id}" must have at least one search field selected`,
          nodeId: node.id,
        });
      }
      if (!node.data.config?.pattern) {
        errors.push({
          type: 'error',
          message: `Jira Key Extractor "${node.data.label || node.id}" must have a regex pattern`,
          nodeId: node.id,
        });
      }
      break;

    case 'createLinkAction':
      if (!node.data.config?.link_type) {
        errors.push({
          type: 'error',
          message: `Create Link action "${node.data.label || node.id}" must have a link type`,
          nodeId: node.id,
        });
      }
      if (node.data.config?.bidirectional && !node.data.config?.reverse_link_type) {
        errors.push({
          type: 'error',
          message: `Create Link action "${node.data.label || node.id}" with bidirectional enabled must specify reverse link type`,
          nodeId: node.id,
        });
      }
      break;

    case 'commitSource':
    case 'jiraIssueSource':
    case 'confluenceSource':
      // Source nodes are optional to configure (can match all)
      break;

    default:
      break;
  }

  return errors;
}

/**
 * Detects circular dependencies in the flow
 */
function detectCycles(nodes: Node[], edges: Edge[]): string[] {
  const adjacencyList = new Map<string, string[]>();

  // Build adjacency list
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
        // Cycle detected
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
    if (!visited.has(node.id)) {
      if (dfs(node.id, [])) {
        // Get node labels for better error message
        return cycle.map((nodeId) => {
          const node = nodes.find((n) => n.id === nodeId);
          return node?.data.label || nodeId;
        });
      }
    }
  }

  return [];
}

/**
 * Gets all source nodes in the flow
 */
export function getSourceNodes(nodes: Node[]): Node[] {
  return nodes.filter((n) =>
    ['commitSource', 'jiraIssueSource', 'confluenceSource'].includes(n.type || '')
  );
}

/**
 * Gets all action nodes in the flow
 */
export function getActionNodes(nodes: Node[]): Node[] {
  return nodes.filter((n) =>
    ['createLinkAction', 'queueReviewAction'].includes(n.type || '')
  );
}

/**
 * Checks if the flow has a complete path from source to action
 */
export function hasCompletePath(nodes: Node[], edges: Edge[]): boolean {
  const sourceNodes = getSourceNodes(nodes);
  const actionNodes = getActionNodes(nodes);

  if (sourceNodes.length === 0 || actionNodes.length === 0) {
    return false;
  }

  // Build adjacency list
  const adjacencyList = new Map<string, string[]>();
  nodes.forEach((node) => adjacencyList.set(node.id, []));
  edges.forEach((edge) => {
    const targets = adjacencyList.get(edge.source) || [];
    targets.push(edge.target);
    adjacencyList.set(edge.source, targets);
  });

  // Check if any source can reach any action
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
 * Gets all nodes reachable from a starting node
 */
function getReachableNodes(startId: string, adjacencyList: Map<string, string[]>): Set<string> {
  const reachable = new Set<string>();
  const queue = [startId];

  while (queue.length > 0) {
    const current = queue.shift()!;
    if (reachable.has(current)) continue;

    reachable.add(current);
    const neighbors = adjacencyList.get(current) || [];
    queue.push(...neighbors);
  }

  return reachable;
}
