import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Divider,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Snackbar,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import {
  Add as AddIcon,
  CheckCircle as ValidateIcon,
  PlayArrow as ExecuteIcon,
  Save as SaveIcon,
  Settings as AutomationIcon,
} from '@mui/icons-material';
import ReactFlow, {
  addEdge,
  Background,
  Connection,
  Controls,
  Edge,
  MiniMap,
  Node,
  NodeTypes,
  useEdgesState,
  useNodesState,
} from 'reactflow';
import 'reactflow/dist/style.css';

import Toolbox from '../components/traceability/Toolbox';
import PropertiesPanelEditable from '../components/traceability/PropertiesPanelEditable';
import ImportExportDialog from '../components/traceability/ImportExportDialog';
import TemplateDialog from '../components/traceability/TemplateDialog';
import ValidationPanel from '../components/traceability/ValidationPanel';
import {
  createRule,
  disableRuleWebhook,
  enableRuleWebhook,
  executeRule,
  getRule,
  getRuleSchedule,
  getRules,
  getRuleWebhook,
  updateRule,
  updateRuleSchedule,
  validateRuleFlow,
} from '../services/api';
import type {
  FlowJSON,
  FlowValidationResult,
  TraceabilityRule,
  TraceabilityRuleCreate,
  TraceabilityRuleUpdate,
} from '../services/api';
import { getErrorMessage } from '../utils/errorUtils';
import {
  validateRule,
  type ValidationError,
  type ValidationResult,
  type ValidationWarning,
} from '../utils/ruleValidation';

import CommitSourceNode from '../components/traceability/nodes/CommitSourceNode';
import JiraIssueSourceNode from '../components/traceability/nodes/JiraIssueSourceNode';
import ConfluenceSourceNode from '../components/traceability/nodes/ConfluenceSourceNode';
import TestRailSourceNode from '../components/traceability/nodes/TestRailSourceNode';
import ManualSourceNode from '../components/traceability/nodes/ManualSourceNode';
import JiraKeyExtractorNode from '../components/traceability/nodes/JiraKeyExtractorNode';
import FilterNode from '../components/traceability/nodes/FilterNode';
import TransformNode from '../components/traceability/nodes/TransformNode';
import DecisionNode from '../components/traceability/nodes/DecisionNode';
import CreateLinkActionNode from '../components/traceability/nodes/CreateLinkActionNode';
import QueueReviewActionNode from '../components/traceability/nodes/QueueReviewActionNode';

const nodeTypes: NodeTypes = {
  commitSource: CommitSourceNode,
  jiraIssueSource: JiraIssueSourceNode,
  confluenceSource: ConfluenceSourceNode,
  testrailSource: TestRailSourceNode,
  manualSource: ManualSourceNode,
  jiraKeyExtractor: JiraKeyExtractorNode,
  filterNode: FilterNode,
  transformNode: TransformNode,
  decisionNode: DecisionNode,
  createLinkAction: CreateLinkActionNode,
  queueReviewAction: QueueReviewActionNode,
};

type TraceabilityNodeData = Record<string, unknown>;
type TraceabilityEdgeData = Record<string, unknown>;
type TraceabilityNode = Node<TraceabilityNodeData>;
type TraceabilityEdge = Edge<TraceabilityEdgeData>;

const DEFAULT_RULE_NAME = 'Untitled Rule';
const EMPTY_FLOW: FlowJSON = {
  nodes: [],
  edges: [],
  version: '1.0',
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const getValidationIssueFields = (issue: unknown) => {
  const normalized = isRecord(issue) ? issue : {};
  return {
    message: String(normalized.message || 'Validation issue'),
    nodeId: typeof normalized.node_id === 'string' ? normalized.node_id : undefined,
    edgeId: typeof normalized.edge_id === 'string' ? normalized.edge_id : undefined,
  };
};

const mapServerValidationError = (issue: unknown): ValidationError => ({
  type: 'error',
  ...getValidationIssueFields(issue),
});

const mapServerValidationWarning = (issue: unknown): ValidationWarning => ({
  type: 'warning',
  ...getValidationIssueFields(issue),
});

const mapServerValidation = (result: FlowValidationResult): ValidationResult => ({
  valid: result.valid,
  errors: result.errors.map((error) => mapServerValidationError(error)),
  warnings: result.warnings.map((warning) => mapServerValidationWarning(warning)),
});

const extractServerValidationFromError = (error: unknown): ValidationResult | null => {
  if (!isRecord(error)) {
    return null;
  }

  const response = error.response;
  if (!isRecord(response)) {
    return null;
  }

  const responseData = response.data;
  if (!isRecord(responseData)) {
    return null;
  }

  const detail = responseData.detail;
  if (!isRecord(detail)) {
    return null;
  }

  const errorsRaw = Array.isArray(detail.errors) ? detail.errors : [];
  const warningsRaw = Array.isArray(detail.warnings) ? detail.warnings : [];

  return {
    valid: false,
    errors: errorsRaw.map((item) => mapServerValidationError(item)),
    warnings: warningsRaw.map((item) => mapServerValidationWarning(item)),
  };
};

const normalizeNode = (node: FlowJSON['nodes'][number]): TraceabilityNode => ({
  id: String(node.id),
  type: node.type,
  position: node.position || { x: 0, y: 0 },
  data: isRecord(node.data) ? node.data : {},
});

const normalizeEdge = (edge: FlowJSON['edges'][number], index: number): TraceabilityEdge => ({
  id: edge.id || `edge_${index}_${Date.now()}`,
  source: edge.source,
  target: edge.target,
  sourceHandle: edge.sourceHandle ?? null,
  targetHandle: edge.targetHandle ?? null,
});

const normalizeImportedNode = (node: Node): TraceabilityNode => ({
  ...node,
  data: isRecord(node.data) ? node.data : {},
});

const normalizeImportedEdge = (edge: Edge): TraceabilityEdge => ({
  ...edge,
  data: isRecord(edge.data) ? edge.data : {},
});

const buildFlowData = (nodes: TraceabilityNode[], edges: TraceabilityEdge[]): FlowJSON => ({
  nodes: nodes.map((node) => ({
    id: node.id,
    type: node.type || 'default',
    position: node.position,
    data: node.data,
  })),
  edges: edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.sourceHandle ?? null,
    targetHandle: edge.targetHandle ?? null,
  })),
  version: '1.0',
});

const buildRuleSnapshot = (name: string, flow: FlowJSON): string =>
  JSON.stringify({ name: name.trim(), flow });

const buildAutomationSnapshot = (
  executeOnSyncComplete = false,
  scheduleEnabled = false,
  scheduleCron = ''
): string =>
  JSON.stringify({
    execute_on_sync_complete: executeOnSyncComplete,
    schedule_enabled: scheduleEnabled,
    schedule_cron: scheduleCron.trim(),
  });

const TraceabilityFlowBuilder: React.FC = () => {
  const [nodes, setNodes, onNodesChange] = useNodesState<TraceabilityNodeData>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<TraceabilityEdgeData>([]);
  const [selectedNode, setSelectedNode] = useState<TraceabilityNode | null>(null);

  const [importExportOpen, setImportExportOpen] = useState(false);
  const [templateDialogOpen, setTemplateDialogOpen] = useState(false);
  const [showValidation, setShowValidation] = useState(false);
  const [serverValidation, setServerValidation] = useState<ValidationResult | null>(null);

  const [saving, setSaving] = useState(false);
  const [executing, setExecuting] = useState(false);

  const [rulesLoading, setRulesLoading] = useState(false);
  const [rules, setRules] = useState<TraceabilityRule[]>([]);
  const [currentRuleId, setCurrentRuleId] = useState<number | null>(null);
  const [ruleName, setRuleName] = useState(DEFAULT_RULE_NAME);
  const [lastSavedRuleSnapshot, setLastSavedRuleSnapshot] = useState(
    buildRuleSnapshot(DEFAULT_RULE_NAME, EMPTY_FLOW)
  );
  const [lastSavedAutomationSnapshot, setLastSavedAutomationSnapshot] = useState(
    buildAutomationSnapshot()
  );

  const [scheduleEnabled, setScheduleEnabled] = useState(false);
  const [scheduleCron, setScheduleCron] = useState('');
  const [nextScheduledRun, setNextScheduledRun] = useState<string | null>(null);
  const [automationBusy, setAutomationBusy] = useState(false);
  const [webhookEnabled, setWebhookEnabled] = useState(false);
  const [webhookUrl, setWebhookUrl] = useState<string | null>(null);
  const [generatedWebhookToken, setGeneratedWebhookToken] = useState<string | null>(null);
  const [executeOnSyncComplete, setExecuteOnSyncComplete] = useState(false);
  const [automationStateReady, setAutomationStateReady] = useState(false);
  const [automationLoadError, setAutomationLoadError] = useState<string | null>(null);

  const [snackbar, setSnackbar] = useState<{
    open: boolean;
    severity: 'success' | 'error' | 'warning' | 'info';
    message: string;
  }>({
    open: false,
    severity: 'info',
    message: '',
  });

  const localValidation = useMemo(() => {
    if (nodes.length === 0) {
      return null;
    }
    return validateRule(nodes, edges);
  }, [nodes, edges]);

  const activeValidation = serverValidation || localValidation;
  const currentFlow = useMemo(() => buildFlowData(nodes, edges), [nodes, edges]);
  const currentRuleSnapshot = useMemo(
    () => buildRuleSnapshot(ruleName, currentFlow),
    [ruleName, currentFlow]
  );
  const currentAutomationSnapshot = useMemo(
    () => buildAutomationSnapshot(executeOnSyncComplete, scheduleEnabled, scheduleCron),
    [executeOnSyncComplete, scheduleEnabled, scheduleCron]
  );
  const hasUnsavedRuleChanges = currentRuleSnapshot !== lastSavedRuleSnapshot;
  const hasUnsavedAutomationChanges = currentAutomationSnapshot !== lastSavedAutomationSnapshot;
  const hasUnsavedChanges = hasUnsavedRuleChanges || hasUnsavedAutomationChanges;
  const automationControlsDisabled = automationBusy || !automationStateReady;

  const notify = useCallback(
    (severity: 'success' | 'error' | 'warning' | 'info', message: string) =>
      setSnackbar({ open: true, severity, message }),
    []
  );

  const loadRules = useCallback(async () => {
    setRulesLoading(true);
    try {
      const response = await getRules({ skip: 0, limit: 200 });
      setRules(response.data);
    } catch (error: unknown) {
      notify('error', getErrorMessage(error, 'Failed to load rules'));
    } finally {
      setRulesLoading(false);
    }
  }, [notify]);

  const resetAutomationState = useCallback(() => {
    setScheduleEnabled(false);
    setScheduleCron('');
    setNextScheduledRun(null);
    setWebhookEnabled(false);
    setWebhookUrl(null);
    setGeneratedWebhookToken(null);
    setExecuteOnSyncComplete(false);
    setAutomationStateReady(false);
    setAutomationLoadError(null);
  }, []);

  const loadAutomationState = useCallback(
    async (ruleId: number, syncCompleteEnabled: boolean) => {
      setAutomationStateReady(false);
      setAutomationLoadError(null);
      try {
        const [schedule, webhook] = await Promise.all([
          getRuleSchedule(ruleId),
          getRuleWebhook(ruleId),
        ]);
        setScheduleEnabled(Boolean(schedule.schedule_enabled));
        setScheduleCron(schedule.schedule_cron || '');
        setNextScheduledRun(schedule.next_scheduled_run || null);
        setWebhookEnabled(Boolean(webhook.trigger_on_webhook));
        setWebhookUrl(webhook.webhook_url || null);
        setGeneratedWebhookToken(null);
        setLastSavedAutomationSnapshot(
          buildAutomationSnapshot(
            syncCompleteEnabled,
            Boolean(schedule.schedule_enabled),
            schedule.schedule_cron || ''
          )
        );
        setAutomationStateReady(true);
      } catch (error: unknown) {
        setScheduleEnabled(false);
        setScheduleCron('');
        setNextScheduledRun(null);
        setWebhookEnabled(false);
        setWebhookUrl(null);
        setGeneratedWebhookToken(null);
        setAutomationLoadError(getErrorMessage(error, 'Failed to load automation settings'));
        notify('error', getErrorMessage(error, 'Failed to load automation settings'));
      }
    },
    [notify]
  );

  const handleReloadAutomationState = useCallback(async () => {
    if (!currentRuleId) {
      return;
    }

    try {
      const rule = await getRule(currentRuleId);
      setExecuteOnSyncComplete(Boolean(rule.execute_on_sync_complete));
      await loadAutomationState(rule.id, Boolean(rule.execute_on_sync_complete));
    } catch (error: unknown) {
      notify('error', getErrorMessage(error, 'Failed to reload automation settings'));
    }
  }, [currentRuleId, loadAutomationState, notify]);

  const applyRuleToCanvas = useCallback(
    (rule: TraceabilityRule) => {
      const flow = rule.flow_json || EMPTY_FLOW;
      const loadedNodes = Array.isArray(flow.nodes) ? flow.nodes.map(normalizeNode) : [];
      const loadedEdges = Array.isArray(flow.edges)
        ? flow.edges.map((edge, index) => normalizeEdge(edge, index))
        : [];

      setNodes(loadedNodes);
      setEdges(loadedEdges);
      setSelectedNode(null);
      setServerValidation(null);
      setCurrentRuleId(rule.id);
      setRuleName(rule.name || DEFAULT_RULE_NAME);
      setScheduleEnabled(false);
      setScheduleCron('');
      setNextScheduledRun(null);
      setWebhookEnabled(false);
      setWebhookUrl(null);
      setGeneratedWebhookToken(null);
      setAutomationStateReady(false);
      setAutomationLoadError(null);
      setExecuteOnSyncComplete(Boolean(rule.execute_on_sync_complete));

      setLastSavedRuleSnapshot(buildRuleSnapshot(rule.name || DEFAULT_RULE_NAME, buildFlowData(loadedNodes, loadedEdges)));
      setLastSavedAutomationSnapshot(
        buildAutomationSnapshot(Boolean(rule.execute_on_sync_complete))
      );
    },
    [setEdges, setNodes]
  );

  const canDiscardChanges = useCallback((): boolean => {
    if (!hasUnsavedChanges) {
      return true;
    }

    return window.confirm('You have unsaved changes. Discard them and continue?');
  }, [hasUnsavedChanges]);

  const openRule = useCallback(
    async (ruleId: number) => {
      if (currentRuleId === ruleId) {
        return;
      }
      if (!canDiscardChanges()) {
        return;
      }

      setRulesLoading(true);
      try {
        const rule = await getRule(ruleId);
        applyRuleToCanvas(rule);
        await loadAutomationState(rule.id, Boolean(rule.execute_on_sync_complete));
      } catch (error: unknown) {
        notify('error', getErrorMessage(error, 'Failed to load selected rule'));
      } finally {
        setRulesLoading(false);
      }
    },
    [applyRuleToCanvas, canDiscardChanges, currentRuleId, loadAutomationState, notify]
  );

  const createNewRule = useCallback(() => {
    if (!canDiscardChanges()) {
      return;
    }

    setNodes([]);
    setEdges([]);
    setSelectedNode(null);
    setServerValidation(null);
    setCurrentRuleId(null);
    setRuleName(DEFAULT_RULE_NAME);
    setLastSavedRuleSnapshot(buildRuleSnapshot(DEFAULT_RULE_NAME, EMPTY_FLOW));
    setLastSavedAutomationSnapshot(buildAutomationSnapshot());
    resetAutomationState();
  }, [canDiscardChanges, resetAutomationState, setEdges, setNodes]);

  const runServerValidation = useCallback(
    async (flow: FlowJSON): Promise<ValidationResult> => {
      const result = await validateRuleFlow(flow);
      const mapped = mapServerValidation(result);
      setServerValidation(mapped);
      return mapped;
    },
    []
  );

  const persistRule = useCallback(
    async (opts?: { showSuccessToast?: boolean }): Promise<number> => {
      const normalizedRuleName = ruleName.trim();
      if (!normalizedRuleName) {
        throw new Error('Rule name is required');
      }

      const flowData = buildFlowData(nodes, edges);
      const validation = await runServerValidation(flowData);
      setShowValidation(true);

      if (!validation.valid) {
        throw new Error('Server validation failed. Fix errors before saving.');
      }

      if (currentRuleId && !hasUnsavedRuleChanges) {
        if (opts?.showSuccessToast !== false) {
          notify('success', 'Rule is up to date');
        }
        return currentRuleId;
      }

      setSaving(true);
      try {
        if (currentRuleId) {
          const updateData: TraceabilityRuleUpdate = {
            name: normalizedRuleName,
            description: 'Auto-saved rule from flow builder',
            flow_json: flowData,
            enabled: true,
            category: 'custom',
          };
          await updateRule(currentRuleId, updateData);
          setRuleName(normalizedRuleName);
          setLastSavedRuleSnapshot(buildRuleSnapshot(normalizedRuleName, flowData));
          if (opts?.showSuccessToast !== false) {
            notify('success', 'Rule updated');
          }
          await loadRules();
          return currentRuleId;
        }

        const createData: TraceabilityRuleCreate = {
          name: normalizedRuleName,
          description: 'Auto-saved rule from flow builder',
          flow_json: flowData,
          enabled: true,
          category: 'custom',
        };
        const savedRule = await createRule(createData);
        setCurrentRuleId(savedRule.id);
        setRuleName(normalizedRuleName);
        setLastSavedRuleSnapshot(buildRuleSnapshot(normalizedRuleName, flowData));
        await loadRules();
        await loadAutomationState(savedRule.id, Boolean(savedRule.execute_on_sync_complete));
        if (opts?.showSuccessToast !== false) {
          notify('success', 'Rule saved');
        }
        return savedRule.id;
      } catch (error: unknown) {
        const validationFromError = extractServerValidationFromError(error);
        if (validationFromError) {
          setServerValidation(validationFromError);
          setShowValidation(true);
        }
        throw error;
      } finally {
        setSaving(false);
      }
    },
    [
      currentRuleId,
      edges,
      hasUnsavedRuleChanges,
      loadAutomationState,
      loadRules,
      nodes,
      notify,
      ruleName,
      runServerValidation,
      executeOnSyncComplete,
    ]
  );

  const handleSaveRule = useCallback(async () => {
    try {
      await persistRule();
    } catch (error: unknown) {
      notify('error', getErrorMessage(error, 'Save failed'));
    }
  }, [notify, persistRule]);

  const handleExecute = useCallback(async () => {
    if (nodes.length === 0) {
      notify('error', 'Add nodes before executing the rule');
      return;
    }

    setExecuting(true);

    try {
      const ruleId = await persistRule({ showSuccessToast: false });
      const result = await executeRule(ruleId);
      notify(
        result.status === 'success' ? 'success' : 'warning',
        `Execution finished: links_created=${result.links_created}, links_updated=${result.links_updated}, artifacts_processed=${result.artifacts_processed}`
      );
    } catch (error: unknown) {
      const validationFromError = extractServerValidationFromError(error);
      if (validationFromError) {
        setServerValidation(validationFromError);
        setShowValidation(true);
      }
      notify('error', getErrorMessage(error, 'Execution failed'));
    } finally {
      setExecuting(false);
    }
  }, [nodes.length, notify, persistRule]);

  const handleValidate = useCallback(async () => {
    if (nodes.length === 0) {
      notify('warning', 'Canvas is empty');
      return;
    }

    setShowValidation(true);
    try {
      const validation = await runServerValidation(buildFlowData(nodes, edges));
      if (validation.valid) {
        notify('success', 'Validation passed');
      } else {
        notify('warning', 'Validation completed with errors/warnings');
      }
    } catch (error: unknown) {
      notify('error', getErrorMessage(error, 'Validation request failed'));
    }
  }, [edges, nodes, notify, runServerValidation]);

  const handleSaveAutomation = useCallback(async () => {
    if (!currentRuleId) {
      notify('warning', 'Save the rule first to configure automation');
      return;
    }

    setAutomationBusy(true);
    try {
      if (!automationStateReady) {
        notify('warning', 'Reload automation settings before saving changes');
        return;
      }
      await updateRule(currentRuleId, {
        execute_on_sync_complete: executeOnSyncComplete,
      });
      const schedule = await updateRuleSchedule(currentRuleId, {
        schedule_enabled: scheduleEnabled,
        schedule_cron: scheduleCron.trim() || null,
      });
      const normalizedScheduleEnabled = Boolean(schedule.schedule_enabled);
      const normalizedScheduleCron = schedule.schedule_cron || '';
      setScheduleEnabled(normalizedScheduleEnabled);
      setScheduleCron(normalizedScheduleCron);
      setNextScheduledRun(schedule.next_scheduled_run || null);
      setLastSavedAutomationSnapshot(
        buildAutomationSnapshot(
          executeOnSyncComplete,
          normalizedScheduleEnabled,
          normalizedScheduleCron
        )
      );
      notify('success', 'Automation updated');
    } catch (error: unknown) {
      notify('error', getErrorMessage(error, 'Failed to update automation settings'));
    } finally {
      setAutomationBusy(false);
    }
  }, [
    currentRuleId,
    automationStateReady,
    executeOnSyncComplete,
    notify,
    scheduleCron,
    scheduleEnabled,
  ]);

  const handleEnableWebhook = useCallback(async () => {
    if (!currentRuleId) {
      notify('warning', 'Save the rule first to configure webhook');
      return;
    }

    setAutomationBusy(true);
    try {
      const webhook = await enableRuleWebhook(currentRuleId);
      setWebhookEnabled(Boolean(webhook.trigger_on_webhook));
      setWebhookUrl(webhook.webhook_url || null);
      setGeneratedWebhookToken(webhook.webhook_token || null);
      notify('success', 'Webhook enabled');
    } catch (error: unknown) {
      notify('error', getErrorMessage(error, 'Failed to enable webhook'));
    } finally {
      setAutomationBusy(false);
    }
  }, [currentRuleId, notify]);

  const handleDisableWebhook = useCallback(async () => {
    if (!currentRuleId) {
      return;
    }

    setAutomationBusy(true);
    try {
      const webhook = await disableRuleWebhook(currentRuleId);
      setWebhookEnabled(Boolean(webhook.trigger_on_webhook));
      setWebhookUrl(webhook.webhook_url || null);
      setGeneratedWebhookToken(null);
      notify('success', 'Webhook disabled');
    } catch (error: unknown) {
      notify('error', getErrorMessage(error, 'Failed to disable webhook'));
    } finally {
      setAutomationBusy(false);
    }
  }, [currentRuleId, notify]);

  const onConnect = useCallback(
    (params: Connection) => setEdges((existing) => addEdge(params, existing)),
    [setEdges]
  );

  const onNodeClick = useCallback((_event: React.MouseEvent, node: TraceabilityNode) => {
    setSelectedNode(node);
  }, []);

  const onUpdateNode = useCallback(
    (nodeId: string, newData: TraceabilityNodeData) => {
      setNodes((existing) =>
        existing.map((node) => (node.id === nodeId ? { ...node, data: newData } : node))
      );
      setSelectedNode((previous) =>
        previous?.id === nodeId ? { ...previous, data: newData } : previous
      );
    },
    [setNodes]
  );

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();

      const type = event.dataTransfer.getData('application/reactflow');
      if (!type) {
        return;
      }

      const rawData = event.dataTransfer.getData('application/nodedata');
      let nodeData: TraceabilityNodeData = {};
      try {
        const parsed = rawData ? JSON.parse(rawData) : {};
        nodeData = isRecord(parsed) ? parsed : {};
      } catch {
        nodeData = {};
      }

      const newNode: TraceabilityNode = {
        id: `${type}_${Date.now()}`,
        type,
        position: {
          x: event.clientX - 270,
          y: event.clientY - 90,
        },
        data: nodeData,
      };

      setNodes((existing) => existing.concat(newNode));
    },
    [setNodes]
  );

  useEffect(() => {
    loadRules();
  }, [loadRules]);

  useEffect(() => {
    setServerValidation(null);
  }, [currentRuleSnapshot]);

  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => {
      if (!hasUnsavedChanges) {
        return;
      }
      event.preventDefault();
      event.returnValue = '';
    };

    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [hasUnsavedChanges]);

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        height: 'calc(100vh - 64px)',
        bgcolor: 'background.default',
      }}
    >
      <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper' }}>
        <Stack spacing={2}>
          <Stack direction={{ xs: 'column', lg: 'row' }} spacing={2} alignItems={{ lg: 'center' }}>
            <Typography variant="h6">Traceability Rule Builder</Typography>

            <TextField
              size="small"
              label="Rule Name"
              value={ruleName}
              onChange={(event) => setRuleName(event.target.value)}
              sx={{ minWidth: 220 }}
            />

            <Button variant="outlined" startIcon={<AddIcon />} onClick={createNewRule}>
              New Rule
            </Button>

            <FormControl size="small" sx={{ minWidth: 260 }}>
              <InputLabel id="rule-select-label">Open Existing Rule</InputLabel>
              <Select
                labelId="rule-select-label"
                label="Open Existing Rule"
                value={currentRuleId ? String(currentRuleId) : ''}
                onChange={(event) => {
                  const value = event.target.value;
                  if (!value) {
                    return;
                  }
                  void openRule(Number(value));
                }}
              >
                <MenuItem value="">Current New Rule</MenuItem>
                {rules.map((rule) => (
                  <MenuItem key={rule.id} value={String(rule.id)}>
                    {rule.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            {rulesLoading && <CircularProgress size={20} />}

            {hasUnsavedChanges && (
              <Typography variant="caption" color="warning.main">
                Unsaved changes
              </Typography>
            )}

            <Box sx={{ flexGrow: 1 }} />

            <Button variant="outlined" startIcon={<ValidateIcon />} onClick={handleValidate}>
              Validate
            </Button>
            <Button
              variant="outlined"
              startIcon={<SaveIcon />}
              onClick={handleSaveRule}
              disabled={saving || executing}
            >
              {saving ? 'Saving...' : currentRuleId ? 'Update' : 'Save'}
            </Button>
            <Button
              variant="contained"
              startIcon={<ExecuteIcon />}
              onClick={handleExecute}
              disabled={!localValidation?.valid || saving || executing}
            >
              {executing ? 'Executing...' : 'Execute Rule'}
            </Button>
          </Stack>

          {currentRuleId && (
            <Paper sx={{ p: 1.5 }}>
              <Stack spacing={1.5}>
                <Stack direction="row" spacing={1} alignItems="center">
                  <AutomationIcon fontSize="small" />
                  <Typography variant="subtitle2">Automation</Typography>
                </Stack>

                {automationLoadError && (
                  <Alert
                    severity="warning"
                    action={
                      <Button color="inherit" size="small" onClick={() => void handleReloadAutomationState()}>
                        Retry
                      </Button>
                    }
                  >
                    {automationLoadError}. Automation controls are disabled until the current backend
                    state is loaded.
                  </Alert>
                )}

                <Stack direction={{ xs: 'column', lg: 'row' }} spacing={2} alignItems={{ lg: 'center' }}>
                  <FormControlLabel
                    control={
                      <Switch
                        checked={executeOnSyncComplete}
                        onChange={(event) => setExecuteOnSyncComplete(event.target.checked)}
                        disabled={automationControlsDisabled}
                      />
                    }
                    label="Run After Sync"
                  />

                  <FormControlLabel
                    control={
                      <Switch
                        checked={scheduleEnabled}
                        onChange={(event) => setScheduleEnabled(event.target.checked)}
                        disabled={automationControlsDisabled}
                      />
                    }
                    label="Schedule Enabled"
                  />

                  <TextField
                    size="small"
                    label="Cron"
                    placeholder="*/5 * * * *"
                    value={scheduleCron}
                    onChange={(event) => setScheduleCron(event.target.value)}
                    sx={{ minWidth: 200 }}
                    disabled={automationControlsDisabled}
                  />

                  <TextField
                    size="small"
                    label="Next Scheduled Run"
                    value={nextScheduledRun || 'Not scheduled'}
                    InputProps={{ readOnly: true }}
                    sx={{ minWidth: 260 }}
                  />

                  <Button
                    variant="outlined"
                    onClick={handleSaveAutomation}
                    disabled={automationControlsDisabled}
                  >
                    {automationBusy ? 'Applying...' : 'Save Automation'}
                  </Button>

                  <Divider flexItem orientation="vertical" sx={{ display: { xs: 'none', lg: 'block' } }} />

                  {webhookEnabled ? (
                    <Button
                      variant="outlined"
                      color="warning"
                      onClick={handleDisableWebhook}
                      disabled={automationControlsDisabled}
                    >
                      Disable Webhook
                    </Button>
                  ) : (
                    <Button variant="outlined" onClick={handleEnableWebhook} disabled={automationControlsDisabled}>
                      Enable Webhook
                    </Button>
                  )}
                </Stack>

                {webhookUrl && (
                  <TextField
                    size="small"
                    label="Webhook URL"
                    value={webhookUrl}
                    InputProps={{ readOnly: true }}
                    fullWidth
                  />
                )}

                {generatedWebhookToken && (
                  <Alert severity="warning">
                    One-time webhook token: <code>{generatedWebhookToken}</code>
                  </Alert>
                )}

                <Typography variant="caption" color="text.secondary">
                  Run After Sync executes this rule automatically after Jira, Confluence, or Git sync
                  batches that changed traceability artifacts.
                </Typography>
              </Stack>
            </Paper>
          )}
        </Stack>
      </Box>

      <Box sx={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <Toolbox
          onImportExportClick={() => setImportExportOpen(true)}
          onTemplateClick={() => setTemplateDialogOpen(true)}
        />

        <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          {showValidation && activeValidation && (
            <ValidationPanel
              validation={activeValidation}
              onNodeClick={(nodeId) => {
                const match = nodes.find((node) => node.id === nodeId);
                if (match) {
                  setSelectedNode(match);
                }
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
                onDragOver={onDragOver}
                onDrop={onDrop}
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

        <PropertiesPanelEditable
          selectedNode={selectedNode}
          onClose={() => setSelectedNode(null)}
          onUpdateNode={onUpdateNode}
        />
      </Box>

      <ImportExportDialog
        open={importExportOpen}
        onClose={() => setImportExportOpen(false)}
        nodes={nodes}
        edges={edges}
        onImport={(importedNodes, importedEdges) => {
          setNodes(importedNodes.map((node) => normalizeImportedNode(node)));
          setEdges(importedEdges.map((edge) => normalizeImportedEdge(edge)));
        }}
      />

      <TemplateDialog
        open={templateDialogOpen}
        onClose={() => setTemplateDialogOpen(false)}
        onApplyTemplate={(templateNodes, templateEdges) => {
          setNodes(templateNodes.map((node) => normalizeImportedNode(node)));
          setEdges(templateEdges.map((edge) => normalizeImportedEdge(edge)));
        }}
      />

      <Snackbar
        open={snackbar.open}
        autoHideDuration={6000}
        onClose={() => setSnackbar((previous) => ({ ...previous, open: false }))}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert
          onClose={() => setSnackbar((previous) => ({ ...previous, open: false }))}
          severity={snackbar.severity}
          sx={{ width: '100%' }}
        >
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  );
};

export default TraceabilityFlowBuilder;
