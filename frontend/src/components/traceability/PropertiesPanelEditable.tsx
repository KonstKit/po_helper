import React, { useEffect, useState } from 'react';
import {
  Box,
  Drawer,
  Typography,
  IconButton,
  Divider,
  TextField,
  Button,
  FormControlLabel,
  Checkbox,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Chip,
  Stack,
} from '@mui/material';
import { Close as CloseIcon, Save as SaveIcon } from '@mui/icons-material';
import { Node } from 'reactflow';

interface NodeFilters {
  branch?: string;
  author?: string;
  space?: string;
  labels?: string[];
  date_from?: string;
  date_to?: string;
  project?: string;
  issue_type?: string[];
  status?: string[];
  project_id?: string;
  suite_id?: string;
  type?: string[];
  priority?: string[];
  [key: string]: unknown;
}

interface NodeConfig {
  condition_type?: string;
  threshold?: number;
  link_type?: string;
  bidirectional?: boolean;
  reverse_link_type?: string;
  search_in?: string[];
  pattern?: string;
  case_sensitive?: boolean;
  must_be_uppercase?: boolean;
  extract_multiple?: boolean;
  field?: string;
  operator?: string;
  value?: string;
  artifact_ids?: number[];
  external_ids?: string[];
  artifact_types?: string[];
  project_id?: string;
  tags?: string[];
  transform_type?: string;
  reason?: string;
  priority?: string;
  [key: string]: unknown;
}

interface NodeData {
  label?: string;
  filters?: NodeFilters;
  config?: NodeConfig;
  [key: string]: unknown;
}

const isStringArray = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((item) => typeof item === 'string');

const getStringArray = (value: unknown): string[] => (isStringArray(value) ? value : []);

const toStringArray = (value: unknown): string[] => {
  if (typeof value === 'string') {
    return value
      .split(',')
      .map((entry) => entry.trim())
      .filter(Boolean);
  }
  if (isStringArray(value)) {
    return value;
  }
  return [];
};

const toNumberArray = (value: unknown): number[] => {
  if (Array.isArray(value) && value.every((item) => typeof item === 'number')) {
    return value.filter((item) => Number.isInteger(item) && item > 0);
  }
  const asStringList = toStringArray(value);
  return asStringList
    .map((item) => Number(item))
    .filter((num) => Number.isInteger(num) && num > 0);
};

const normalizeSearchIn = (value: unknown): string[] =>
  getStringArray(value).map((field) => {
    if (field === 'branch_name') return 'branch';
    if (field === 'body') return 'description';
    return field;
  });

const normalizeNodeData = (input: NodeData): NodeData => {
  const data: NodeData = { ...input };
  const filters = { ...(data.filters || {}) };
  const config = { ...(data.config || {}) };

  if (filters.after_date && !filters.date_from) {
    filters.date_from = String(filters.after_date);
  }
  if (filters.before_date && !filters.date_to) {
    filters.date_to = String(filters.before_date);
  }

  if (config.search_in) {
    config.search_in = normalizeSearchIn(config.search_in);
  }

  data.filters = filters;
  data.config = config;
  return data;
};

interface PropertiesPanelEditableProps {
  selectedNode: Node | null;
  onClose: () => void;
  onUpdateNode: (nodeId: string, newData: NodeData) => void;
}

const PropertiesPanelEditable: React.FC<PropertiesPanelEditableProps> = ({
  selectedNode,
  onClose,
  onUpdateNode,
}) => {
  const [editedData, setEditedData] = useState<NodeData | null>(null);

  useEffect(() => {
    if (!selectedNode) return;
    const timeoutId = setTimeout(() => {
      setEditedData(normalizeNodeData({ ...(selectedNode.data as NodeData) }));
    }, 0);
    return () => clearTimeout(timeoutId);
  }, [selectedNode]);

  if (!selectedNode || !editedData) return null;

  const handleSave = () => {
    onUpdateNode(selectedNode.id, normalizeNodeData(editedData));
  };

  const updateFilter = (key: string, value: unknown) => {
    setEditedData({
      ...editedData,
      filters: {
        ...(editedData.filters || {}),
        [key]: value,
      },
    });
  };

  const updateConfig = (key: string, value: unknown) => {
    setEditedData({
      ...editedData,
      config: {
        ...(editedData.config || {}),
        [key]: value,
      },
    });
  };

  const toggleSearchIn = (value: string) => {
    const currentArray = normalizeSearchIn(editedData.config?.search_in);
    const newArray = currentArray.includes(value)
      ? currentArray.filter((item: string) => item !== value)
      : [...currentArray, value];
    updateConfig('search_in', newArray);
  };

  const renderCommitSourceFields = () => (
    <>
      <TextField
        fullWidth
        label="Branch Filter"
        value={String(editedData.filters?.branch || '')}
        onChange={(e) => updateFilter('branch', e.target.value)}
        placeholder="e.g., main, dev, feature/*"
        sx={{ mb: 2 }}
      />
      <TextField
        fullWidth
        label="Author Filter"
        value={String(editedData.filters?.author || '')}
        onChange={(e) => updateFilter('author', e.target.value)}
        placeholder="e.g., john@example.com"
        sx={{ mb: 2 }}
      />
      <TextField
        fullWidth
        label="Date From"
        type="date"
        value={String(editedData.filters?.date_from || '')}
        onChange={(e) => updateFilter('date_from', e.target.value)}
        InputLabelProps={{ shrink: true }}
        sx={{ mb: 2 }}
      />
      <TextField
        fullWidth
        label="Date To"
        type="date"
        value={String(editedData.filters?.date_to || '')}
        onChange={(e) => updateFilter('date_to', e.target.value)}
        InputLabelProps={{ shrink: true }}
        sx={{ mb: 2 }}
      />
    </>
  );

  const renderJiraIssueSourceFields = () => (
    <>
      <TextField
        fullWidth
        label="Project Key"
        value={String(editedData.filters?.project || '')}
        onChange={(e) => updateFilter('project', e.target.value)}
        placeholder="e.g., WAB, JIRA"
        sx={{ mb: 2 }}
      />
      <FormControl fullWidth sx={{ mb: 2 }}>
        <InputLabel>Issue Types</InputLabel>
        <Select
          multiple
          value={getStringArray(editedData.filters?.issue_type)}
          onChange={(e) => updateFilter('issue_type', e.target.value)}
          renderValue={(selected) => (
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
              {getStringArray(selected).map((value) => (
                <Chip key={value} label={value} size="small" />
              ))}
            </Box>
          )}
        >
          <MenuItem value="Story">Story</MenuItem>
          <MenuItem value="Task">Task</MenuItem>
          <MenuItem value="Sub-task">Sub-task</MenuItem>
          <MenuItem value="Bug">Bug</MenuItem>
          <MenuItem value="Epic">Epic</MenuItem>
        </Select>
      </FormControl>
      <FormControl fullWidth sx={{ mb: 2 }}>
        <InputLabel>Status</InputLabel>
        <Select
          multiple
          value={getStringArray(editedData.filters?.status)}
          onChange={(e) => updateFilter('status', e.target.value)}
          renderValue={(selected) => (
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
              {getStringArray(selected).map((value) => (
                <Chip key={value} label={value} size="small" />
              ))}
            </Box>
          )}
        >
          <MenuItem value="To Do">To Do</MenuItem>
          <MenuItem value="In Progress">In Progress</MenuItem>
          <MenuItem value="In Review">In Review</MenuItem>
          <MenuItem value="Done">Done</MenuItem>
          <MenuItem value="Closed">Closed</MenuItem>
        </Select>
      </FormControl>
    </>
  );

  const renderConfluenceSourceFields = () => (
    <>
      <TextField
        fullWidth
        label="Space Key"
        value={String(editedData.filters?.space || '')}
        onChange={(e) => updateFilter('space', e.target.value)}
        placeholder="e.g., DEV, DOCS"
        sx={{ mb: 2 }}
      />
      <TextField
        fullWidth
        label="Labels (comma-separated)"
        value={getStringArray(editedData.filters?.labels).join(', ')}
        onChange={(e) => updateFilter('labels', toStringArray(e.target.value))}
        placeholder="e.g., requirements, design"
        sx={{ mb: 2 }}
      />
    </>
  );

  const renderTestRailSourceFields = () => (
    <>
      <TextField
        fullWidth
        label="Project ID"
        value={String(editedData.filters?.project_id || '')}
        onChange={(e) => updateFilter('project_id', e.target.value)}
        sx={{ mb: 2 }}
      />
      <TextField
        fullWidth
        label="Suite ID"
        value={String(editedData.filters?.suite_id || '')}
        onChange={(e) => updateFilter('suite_id', e.target.value)}
        sx={{ mb: 2 }}
      />
      <TextField
        fullWidth
        label="Status (comma-separated)"
        value={getStringArray(editedData.filters?.status).join(', ')}
        onChange={(e) => updateFilter('status', toStringArray(e.target.value))}
        sx={{ mb: 2 }}
      />
      <TextField
        fullWidth
        label="Type (comma-separated)"
        value={getStringArray(editedData.filters?.type).join(', ')}
        onChange={(e) => updateFilter('type', toStringArray(e.target.value))}
        sx={{ mb: 2 }}
      />
      <TextField
        fullWidth
        label="Priority (comma-separated)"
        value={getStringArray(editedData.filters?.priority).join(', ')}
        onChange={(e) => updateFilter('priority', toStringArray(e.target.value))}
        sx={{ mb: 2 }}
      />
      <TextField
        fullWidth
        label="Date From"
        type="date"
        value={String(editedData.filters?.date_from || '')}
        onChange={(e) => updateFilter('date_from', e.target.value)}
        InputLabelProps={{ shrink: true }}
        sx={{ mb: 2 }}
      />
      <TextField
        fullWidth
        label="Date To"
        type="date"
        value={String(editedData.filters?.date_to || '')}
        onChange={(e) => updateFilter('date_to', e.target.value)}
        InputLabelProps={{ shrink: true }}
        sx={{ mb: 2 }}
      />
    </>
  );

  const renderManualSourceFields = () => (
    <>
      <TextField
        fullWidth
        label="Artifact IDs (comma-separated)"
        value={toNumberArray(editedData.config?.artifact_ids).join(', ')}
        onChange={(e) => updateConfig('artifact_ids', toNumberArray(e.target.value))}
        sx={{ mb: 2 }}
      />
      <TextField
        fullWidth
        label="External IDs (comma-separated)"
        value={getStringArray(editedData.config?.external_ids).join(', ')}
        onChange={(e) => updateConfig('external_ids', toStringArray(e.target.value))}
        sx={{ mb: 2 }}
      />
      <TextField
        fullWidth
        label="Artifact Types (comma-separated)"
        value={getStringArray(editedData.config?.artifact_types).join(', ')}
        onChange={(e) => updateConfig('artifact_types', toStringArray(e.target.value))}
        sx={{ mb: 2 }}
      />
      <TextField
        fullWidth
        label="Project ID (optional)"
        value={String(editedData.config?.project_id || '')}
        onChange={(e) => updateConfig('project_id', e.target.value)}
        sx={{ mb: 2 }}
      />
      <TextField
        fullWidth
        label="Tags (comma-separated)"
        value={getStringArray(editedData.config?.tags).join(', ')}
        onChange={(e) => updateConfig('tags', toStringArray(e.target.value))}
        sx={{ mb: 2 }}
      />
    </>
  );

  const renderJiraKeyExtractorFields = () => {
    const searchIn = normalizeSearchIn(editedData.config?.search_in);
    return (
      <>
        <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>
          Search In:
        </Typography>
        <Stack spacing={1} sx={{ mb: 2 }}>
          <FormControlLabel
            control={
              <Checkbox
                checked={searchIn.includes('message')}
                onChange={() => toggleSearchIn('message')}
              />
            }
            label="Commit Message"
          />
          <FormControlLabel
            control={
              <Checkbox checked={searchIn.includes('branch')} onChange={() => toggleSearchIn('branch')} />
            }
            label="Branch Name"
          />
          <FormControlLabel
            control={
              <Checkbox checked={searchIn.includes('title')} onChange={() => toggleSearchIn('title')} />
            }
            label="Title"
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={searchIn.includes('description')}
                onChange={() => toggleSearchIn('description')}
              />
            }
            label="Description"
          />
        </Stack>

        <TextField
          fullWidth
          label="Regex Pattern"
          value={String(editedData.config?.pattern || '')}
          onChange={(e) => updateConfig('pattern', e.target.value)}
          placeholder="\\b[A-Z][A-Z0-9_]+-[0-9]+\\b"
          sx={{ mb: 2 }}
          helperText="Modern Jira key pattern (supports numbers/underscores)"
        />

        <FormControlLabel
          control={
            <Checkbox
              checked={Boolean(editedData.config?.case_sensitive)}
              onChange={(e) => updateConfig('case_sensitive', e.target.checked)}
            />
          }
          label="Case Sensitive"
          sx={{ mb: 1 }}
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={editedData.config?.must_be_uppercase !== false}
              onChange={(e) => updateConfig('must_be_uppercase', e.target.checked)}
            />
          }
          label="Must Be Uppercase"
          sx={{ mb: 1 }}
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={editedData.config?.extract_multiple !== false}
              onChange={(e) => updateConfig('extract_multiple', e.target.checked)}
            />
          }
          label="Extract Multiple Keys"
        />
      </>
    );
  };

  const renderFilterNodeFields = () => (
    <>
      <TextField
        fullWidth
        label="Field Name"
        value={String(editedData.config?.field || '')}
        onChange={(e) => updateConfig('field', e.target.value)}
        placeholder="e.g., issue_type, status, author"
        sx={{ mb: 2 }}
      />
      <FormControl fullWidth sx={{ mb: 2 }}>
        <InputLabel>Operator</InputLabel>
        <Select
          value={String(editedData.config?.operator || 'equals')}
          onChange={(e) => updateConfig('operator', e.target.value)}
        >
          <MenuItem value="equals">Equals</MenuItem>
          <MenuItem value="not_equals">Not Equals</MenuItem>
          <MenuItem value="contains">Contains</MenuItem>
          <MenuItem value="not_contains">Not Contains</MenuItem>
          <MenuItem value="matches">Matches Regex</MenuItem>
          <MenuItem value="in">In List</MenuItem>
        </Select>
      </FormControl>
      <TextField
        fullWidth
        label="Value"
        value={String(editedData.config?.value || '')}
        onChange={(e) => updateConfig('value', e.target.value)}
        placeholder="Value to filter by"
        sx={{ mb: 2 }}
      />
    </>
  );

  const renderTransformNodeFields = () => (
    <FormControl fullWidth sx={{ mb: 2 }}>
      <InputLabel>Transform Type</InputLabel>
      <Select
        value={String(editedData.config?.transform_type || 'passthrough')}
        onChange={(e) => updateConfig('transform_type', e.target.value)}
      >
        <MenuItem value="passthrough">Passthrough</MenuItem>
      </Select>
    </FormControl>
  );

  const renderDecisionNodeFields = () => (
    <>
      <FormControl fullWidth sx={{ mb: 2 }}>
        <InputLabel>Condition Type</InputLabel>
        <Select
          value={String(editedData.config?.condition_type || 'confidence_threshold')}
          onChange={(e) => updateConfig('condition_type', e.target.value)}
        >
          <MenuItem value="confidence_threshold">Confidence Threshold</MenuItem>
          <MenuItem value="count_threshold">Count Threshold</MenuItem>
          <MenuItem value="count_equals">Count Equals</MenuItem>
          <MenuItem value="has_artifacts">Has Artifacts</MenuItem>
          <MenuItem value="is_empty">Is Empty</MenuItem>
        </Select>
      </FormControl>

      {(editedData.config?.condition_type === 'confidence_threshold' ||
        editedData.config?.condition_type === 'count_threshold' ||
        editedData.config?.condition_type === 'count_equals') && (
        <TextField
          fullWidth
          type="number"
          label={editedData.config?.condition_type === 'confidence_threshold' ? 'Threshold (%)' : 'Threshold'}
          value={Number(editedData.config?.threshold ?? 85)}
          onChange={(e) => updateConfig('threshold', Number(e.target.value))}
          inputProps={
            editedData.config?.condition_type === 'confidence_threshold'
              ? { min: 0, max: 100 }
              : { min: 0 }
          }
          sx={{ mb: 2 }}
          helperText={
            editedData.config?.condition_type === 'confidence_threshold'
              ? 'Artifacts with confidence below threshold go to FALSE branch'
              : undefined
          }
        />
      )}
    </>
  );

  const renderCreateLinkActionFields = () => (
    <>
      <FormControl fullWidth sx={{ mb: 2 }}>
        <InputLabel>Link Type</InputLabel>
        <Select
          value={String(editedData.config?.link_type || 'relates_to')}
          onChange={(e) => updateConfig('link_type', e.target.value)}
        >
          <MenuItem value="relates_to">Relates To</MenuItem>
          <MenuItem value="implements">Implements</MenuItem>
          <MenuItem value="tests">Tests</MenuItem>
          <MenuItem value="blocks">Blocks</MenuItem>
          <MenuItem value="depends_on">Depends On</MenuItem>
          <MenuItem value="child_of">Child Of</MenuItem>
          <MenuItem value="parent_of">Parent Of</MenuItem>
        </Select>
      </FormControl>

      <FormControlLabel
        control={
          <Checkbox
            checked={Boolean(editedData.config?.bidirectional)}
            onChange={(e) => updateConfig('bidirectional', e.target.checked)}
          />
        }
        label="Create Bidirectional Link"
        sx={{ mb: 2 }}
      />

      {editedData.config?.bidirectional && (
        <FormControl fullWidth sx={{ mb: 2 }}>
          <InputLabel>Reverse Link Type</InputLabel>
          <Select
            value={String(editedData.config?.reverse_link_type || '')}
            onChange={(e) => updateConfig('reverse_link_type', e.target.value)}
          >
            <MenuItem value="relates_to">Relates To</MenuItem>
            <MenuItem value="implemented_by">Implemented By</MenuItem>
            <MenuItem value="tested_by">Tested By</MenuItem>
            <MenuItem value="blocked_by">Blocked By</MenuItem>
            <MenuItem value="required_by">Required By</MenuItem>
            <MenuItem value="depends_on">Depends On</MenuItem>
            <MenuItem value="parent_of">Parent Of</MenuItem>
          </Select>
        </FormControl>
      )}
    </>
  );

  const renderQueueReviewActionFields = () => (
    <>
      <TextField
        fullWidth
        label="Reason"
        value={String(editedData.config?.reason || '')}
        onChange={(e) => updateConfig('reason', e.target.value)}
        sx={{ mb: 2 }}
      />
      <FormControl fullWidth sx={{ mb: 2 }}>
        <InputLabel>Priority</InputLabel>
        <Select
          value={String(editedData.config?.priority || 'normal')}
          onChange={(e) => updateConfig('priority', e.target.value)}
        >
          <MenuItem value="low">Low</MenuItem>
          <MenuItem value="normal">Normal</MenuItem>
          <MenuItem value="high">High</MenuItem>
          <MenuItem value="critical">Critical</MenuItem>
        </Select>
      </FormControl>
    </>
  );

  const renderNodeFields = () => {
    switch (selectedNode.type) {
      case 'commitSource':
        return renderCommitSourceFields();
      case 'jiraIssueSource':
        return renderJiraIssueSourceFields();
      case 'confluenceSource':
        return renderConfluenceSourceFields();
      case 'testrailSource':
        return renderTestRailSourceFields();
      case 'manualSource':
        return renderManualSourceFields();
      case 'jiraKeyExtractor':
        return renderJiraKeyExtractorFields();
      case 'filterNode':
        return renderFilterNodeFields();
      case 'transformNode':
        return renderTransformNodeFields();
      case 'decisionNode':
        return renderDecisionNodeFields();
      case 'createLinkAction':
        return renderCreateLinkActionFields();
      case 'queueReviewAction':
        return renderQueueReviewActionFields();
      default:
        return (
          <Typography variant="body2" color="text.secondary">
            No editable fields for this node type
          </Typography>
        );
    }
  };

  return (
    <Drawer
      anchor="right"
      open={!!selectedNode}
      onClose={onClose}
      variant="persistent"
      PaperProps={{ 'data-testid': 'properties-panel' }}
      sx={{
        width: 360,
        flexShrink: 0,
        '& .MuiDrawer-paper': {
          width: 360,
          mt: '64px',
          height: 'calc(100% - 64px)',
        },
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', p: 2, bgcolor: 'background.paper' }}>
        <Typography variant="h6" sx={{ flex: 1 }}>
          Edit Properties
        </Typography>
        <IconButton size="small" onClick={onClose}>
          <CloseIcon />
        </IconButton>
      </Box>
      <Divider />

      <Box sx={{ p: 2, overflowY: 'auto', flex: 1 }}>
        <TextField
          fullWidth
          label="Node Label"
          value={String(editedData.label || '')}
          onChange={(e) => setEditedData({ ...editedData, label: e.target.value })}
          sx={{ mb: 3 }}
        />

        <Divider sx={{ my: 2 }} />

        <Typography variant="caption" color="text.secondary">
          Node Type
        </Typography>
        <Typography variant="body2" sx={{ mb: 3 }}>
          {selectedNode.type}
        </Typography>

        <Divider sx={{ my: 2 }} />
        {renderNodeFields()}
      </Box>

      <Box sx={{ p: 2, borderTop: 1, borderColor: 'divider' }}>
        <Button fullWidth variant="contained" startIcon={<SaveIcon />} onClick={handleSave}>
          Apply Changes
        </Button>
      </Box>
    </Drawer>
  );
};

export default PropertiesPanelEditable;
