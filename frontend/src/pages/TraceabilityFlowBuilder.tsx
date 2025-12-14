import React, { useCallback, useState, useMemo } from 'react';
import { Box, Paper, Typography, Button, Stack, Alert, Snackbar, TextField } from '@mui/material';
import { CheckCircle as ValidateIcon, PlayArrow as ExecuteIcon, Save as SaveIcon } from '@mui/icons-material';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Node,
  Edge,
  Connection,
  addEdge,
  useNodesState,
  useEdgesState,
  NodeTypes,
} from 'reactflow';
import 'reactflow/dist/style.css';

import Toolbox from '../components/traceability/Toolbox';
import PropertiesPanelEditable from '../components/traceability/PropertiesPanelEditable';
import ImportExportDialog from '../components/traceability/ImportExportDialog';
import TemplateDialog from '../components/traceability/TemplateDialog';
import ValidationPanel from '../components/traceability/ValidationPanel';
import { validateRule, ValidationResult } from '../utils/ruleValidation';

// Import custom node components
import CommitSourceNode from '../components/traceability/nodes/CommitSourceNode';
import JiraIssueSourceNode from '../components/traceability/nodes/JiraIssueSourceNode';
import ConfluenceSourceNode from '../components/traceability/nodes/ConfluenceSourceNode';
import JiraKeyExtractorNode from '../components/traceability/nodes/JiraKeyExtractorNode';
import FilterNode from '../components/traceability/nodes/FilterNode';
import DecisionNode from '../components/traceability/nodes/DecisionNode';
import CreateLinkActionNode from '../components/traceability/nodes/CreateLinkActionNode';

// Define node types for React Flow
const nodeTypes: NodeTypes = {
  commitSource: CommitSourceNode,
  jiraIssueSource: JiraIssueSourceNode,
  confluenceSource: ConfluenceSourceNode,
  jiraKeyExtractor: JiraKeyExtractorNode,
  filterNode: FilterNode,
  decisionNode: DecisionNode,
  createLinkAction: CreateLinkActionNode,
};

const TraceabilityFlowBuilder: React.FC = () => {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [importExportOpen, setImportExportOpen] = useState(false);
  const [templateDialogOpen, setTemplateDialogOpen] = useState(false);
  const [showValidation, setShowValidation] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [executionResult, setExecutionResult] = useState<any>(null);
  const [snackbarOpen, setSnackbarOpen] = useState(false);
  const [currentRuleId, setCurrentRuleId] = useState<number | null>(null);
  const [ruleName, setRuleName] = useState('Untitled Rule');

  // Auto-validate when nodes or edges change
  const validation = useMemo(() => {
    if (nodes.length === 0) return null;
    return validateRule(nodes, edges);
  }, [nodes, edges]);

  // Handle new connections between nodes
  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge(params, eds)),
    [setEdges]
  );

  // Handle node selection for properties panel
  const onNodeClick = useCallback((_event: React.MouseEvent, node: Node) => {
    setSelectedNode(node);
  }, []);

  // Handle node update from properties panel
  const onUpdateNode = useCallback((nodeId: string, newData: any) => {
    setNodes((nds) =>
      nds.map((node) =>
        node.id === nodeId
          ? { ...node, data: newData }
          : node
      )
    );
  }, [setNodes]);

  // Save or update rule
  const handleSaveRule = useCallback(async () => {
    const flowData = {
      nodes,
      edges,
      version: '1.0',
    };

    try {
      const url = currentRuleId
        ? `/api/v1/traceability/rules/${currentRuleId}`
        : '/api/v1/traceability/rules';

      const method = currentRuleId ? 'PUT' : 'POST';

      const response = await fetch(url, {
        method,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('token')}`,
        },
        body: JSON.stringify({
          name: ruleName,
          description: 'Auto-saved rule from flow builder',
          flow_json: flowData,
          enabled: true,
          category: 'custom',
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to save rule');
      }

      const savedRule = await response.json();
      setCurrentRuleId(savedRule.id);
      return savedRule.id;
    } catch (error: any) {
      throw new Error(`Save failed: ${error.message}`);
    }
  }, [nodes, edges, ruleName, currentRuleId]);

  // Handle rule execution
  const handleExecute = useCallback(async () => {
    if (!validation?.valid) {
      setSnackbarOpen(true);
      setExecutionResult({ error: 'Rule validation failed. Fix errors first.' });
      return;
    }

    setExecuting(true);
    setExecutionResult(null);

    try {
      // Save rule first (or update if exists)
      const ruleId = await handleSaveRule();

      // Execute the rule
      const response = await fetch(`/api/v1/traceability/rules/${ruleId}/execute`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('token')}`,
        },
      });

      if (!response.ok) {
        throw new Error('Execution failed');
      }

      const result = await response.json();
      setExecutionResult(result);
      setSnackbarOpen(true);
    } catch (error: any) {
      setExecutionResult({ error: error.message });
      setSnackbarOpen(true);
    } finally {
      setExecuting(false);
    }
  }, [validation, handleSaveRule]);

  // Handle drag over for toolbox items
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  // Handle drop from toolbox
  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();

      const type = event.dataTransfer.getData('application/reactflow');
      const nodeData = JSON.parse(event.dataTransfer.getData('application/nodedata'));

      if (!type) return;

      const position = {
        x: event.clientX - 250, // Offset for toolbox width
        y: event.clientY - 50,
      };

      const newNode: Node = {
        id: `${type}_${Date.now()}`,
        type,
        position,
        data: nodeData,
      };

      setNodes((nds) => nds.concat(newNode));
    },
    [setNodes]
  );

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 64px)', bgcolor: 'background.default' }}>
      {/* Top Toolbar */}
      <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper' }}>
        <Stack direction="row" spacing={2} alignItems="center">
          <Typography variant="h6">Traceability Rule Builder</Typography>
          <TextField
            size="small"
            value={ruleName}
            onChange={(e) => setRuleName(e.target.value)}
            placeholder="Rule Name"
            sx={{ minWidth: 200 }}
          />
          <Box sx={{ flexGrow: 1 }} />
          <Button
            variant="outlined"
            startIcon={<ValidateIcon />}
            onClick={() => setShowValidation(!showValidation)}
            color={validation?.valid ? 'success' : validation?.errors.length ? 'error' : 'warning'}
          >
            {validation?.valid ? 'Valid' : 'Validate'}
          </Button>
          <Button
            variant="outlined"
            startIcon={<SaveIcon />}
            onClick={handleSaveRule}
          >
            {currentRuleId ? 'Update' : 'Save'}
          </Button>
          <Button
            variant="contained"
            startIcon={<ExecuteIcon />}
            onClick={handleExecute}
            disabled={!validation?.valid || executing}
            color="primary"
          >
            {executing ? 'Executing...' : 'Execute Rule'}
          </Button>
        </Stack>
      </Box>

      <Box sx={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* Toolbox */}
        <Toolbox
          onImportExportClick={() => setImportExportOpen(true)}
          onTemplateClick={() => setTemplateDialogOpen(true)}
        />

        {/* Main Canvas */}
        <Box sx={{ flex: 1, position: 'relative', display: 'flex', flexDirection: 'column' }}>
          {/* Validation Panel */}
          {showValidation && validation && (
            <ValidationPanel
              validation={validation}
              onNodeClick={(nodeId) => {
                const node = nodes.find((n) => n.id === nodeId);
                if (node) setSelectedNode(node);
              }}
            />
          )}

          <Box sx={{ flex: 1 }}>
            <Paper sx={{ height: '100%', borderRadius: 0 }}>
              <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onDrop={onDrop}
            onDragOver={onDragOver}
            nodeTypes={nodeTypes}
            fitView
          >
            <Background />
            <Controls />
            <MiniMap />
          </ReactFlow>
            </Paper>
          </Box>
        </Box>

        {/* Properties Panel */}
        <PropertiesPanelEditable
          selectedNode={selectedNode}
          onClose={() => setSelectedNode(null)}
          onUpdateNode={onUpdateNode}
        />
      </Box>

      {/* Import/Export Dialog */}
      <ImportExportDialog
        open={importExportOpen}
        onClose={() => setImportExportOpen(false)}
        nodes={nodes}
        edges={edges}
        onImport={(importedNodes, importedEdges) => {
          setNodes(importedNodes);
          setEdges(importedEdges);
        }}
      />

      {/* Template Dialog */}
      <TemplateDialog
        open={templateDialogOpen}
        onClose={() => setTemplateDialogOpen(false)}
        onApplyTemplate={(templateNodes, templateEdges) => {
          setNodes(templateNodes);
          setEdges(templateEdges);
        }}
      />

      {/* Execution Result Snackbar */}
      <Snackbar
        open={snackbarOpen}
        autoHideDuration={6000}
        onClose={() => setSnackbarOpen(false)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert
          onClose={() => setSnackbarOpen(false)}
          severity={executionResult?.error ? 'error' : 'success'}
          sx={{ width: '100%' }}
        >
          {executionResult?.error ||
            `Rule executed successfully! Created ${executionResult?.links_created || 0} links.`}
        </Alert>
      </Snackbar>
    </Box>
  );
};

export default TraceabilityFlowBuilder;
