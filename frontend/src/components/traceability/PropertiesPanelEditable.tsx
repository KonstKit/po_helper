import React, { useState, useEffect } from 'react';
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

interface PropertiesPanelEditableProps {
  selectedNode: Node | null;
  onClose: () => void;
  onUpdateNode: (nodeId: string, newData: any) => void;
}

const PropertiesPanelEditable: React.FC<PropertiesPanelEditableProps> = ({
  selectedNode,
  onClose,
  onUpdateNode,
}) => {
  const [editedData, setEditedData] = useState<any>(null);

  useEffect(() => {
    if (selectedNode) {
      setEditedData({ ...selectedNode.data });
    }
  }, [selectedNode]);

  if (!selectedNode || !editedData) return null;

  const handleSave = () => {
    onUpdateNode(selectedNode.id, editedData);
  };

  const updateFilter = (key: string, value: any) => {
    setEditedData({
      ...editedData,
      filters: {
        ...editedData.filters,
        [key]: value,
      },
    });
  };

  const updateConfig = (key: string, value: any) => {
    setEditedData({
      ...editedData,
      config: {
        ...editedData.config,
        [key]: value,
      },
    });
  };

  const toggleConfigArray = (key: string, value: string) => {
    const currentArray = editedData.config?.[key] || [];
    const newArray = currentArray.includes(value)
      ? currentArray.filter((item: string) => item !== value)
      : [...currentArray, value];
    updateConfig(key, newArray);
  };

  const renderCommitSourceFields = () => (
    <>
      <TextField
        fullWidth
        label="Branch Filter"
        value={editedData.filters?.branch || ''}
        onChange={(e) => updateFilter('branch', e.target.value)}
        placeholder="e.g., main, dev, feature/*"
        sx={{ mb: 2 }}
      />
      <TextField
        fullWidth
        label="Author Filter"
        value={editedData.filters?.author || ''}
        onChange={(e) => updateFilter('author', e.target.value)}
        placeholder="e.g., john@example.com"
        sx={{ mb: 2 }}
      />
      <TextField
        fullWidth
        label="After Date"
        type="date"
        value={editedData.filters?.after_date || ''}
        onChange={(e) => updateFilter('after_date', e.target.value)}
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
        value={editedData.filters?.project || ''}
        onChange={(e) => updateFilter('project', e.target.value)}
        placeholder="e.g., WAB, JIRA"
        sx={{ mb: 2 }}
      />
      <FormControl fullWidth sx={{ mb: 2 }}>
        <InputLabel>Issue Types</InputLabel>
        <Select
          multiple
          value={editedData.filters?.issue_type || []}
          onChange={(e) => updateFilter('issue_type', e.target.value)}
          renderValue={(selected) => (
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
              {(selected as string[]).map((value) => (
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
          value={editedData.filters?.status || []}
          onChange={(e) => updateFilter('status', e.target.value)}
          renderValue={(selected) => (
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
              {(selected as string[]).map((value) => (
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
        value={editedData.filters?.space || ''}
        onChange={(e) => updateFilter('space', e.target.value)}
        placeholder="e.g., DEV, DOCS"
        sx={{ mb: 2 }}
      />
      <TextField
        fullWidth
        label="Labels (comma-separated)"
        value={editedData.filters?.labels?.join(', ') || ''}
        onChange={(e) => updateFilter('labels', e.target.value.split(',').map((s: string) => s.trim()))}
        placeholder="e.g., requirements, design"
        sx={{ mb: 2 }}
      />
    </>
  );

  const renderJiraKeyExtractorFields = () => (
    <>
      <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>
        Search In:
      </Typography>
      <Stack spacing={1} sx={{ mb: 2 }}>
        <FormControlLabel
          control={
            <Checkbox
              checked={editedData.config?.search_in?.includes('message')}
              onChange={() => toggleConfigArray('search_in', 'message')}
            />
          }
          label="Commit Message"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={editedData.config?.search_in?.includes('branch_name')}
              onChange={() => toggleConfigArray('search_in', 'branch_name')}
            />
          }
          label="Branch Name"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={editedData.config?.search_in?.includes('title')}
              onChange={() => toggleConfigArray('search_in', 'title')}
            />
          }
          label="Title (PR/Issue)"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={editedData.config?.search_in?.includes('body')}
              onChange={() => toggleConfigArray('search_in', 'body')}
            />
          }
          label="Body (PR/Issue)"
        />
      </Stack>

      <TextField
        fullWidth
        label="Regex Pattern"
        value={editedData.config?.pattern || ''}
        onChange={(e) => updateConfig('pattern', e.target.value)}
        placeholder="\\b[A-Z][A-Z0-9_]+-[0-9]+\\b"
        sx={{ mb: 2 }}
        helperText="Modern Jira key pattern (supports numbers/underscores)"
      />

      <FormControlLabel
        control={
          <Checkbox
            checked={editedData.config?.case_sensitive || false}
            onChange={(e) => updateConfig('case_sensitive', e.target.checked)}
          />
        }
        label="Case Sensitive"
        sx={{ mb: 1 }}
      />
      <FormControlLabel
        control={
          <Checkbox
            checked={editedData.config?.must_be_uppercase || true}
            onChange={(e) => updateConfig('must_be_uppercase', e.target.checked)}
          />
        }
        label="Must Be Uppercase"
        sx={{ mb: 1 }}
      />
      <FormControlLabel
        control={
          <Checkbox
            checked={editedData.config?.extract_multiple || true}
            onChange={(e) => updateConfig('extract_multiple', e.target.checked)}
          />
        }
        label="Extract Multiple Keys"
      />
    </>
  );

  const renderFilterNodeFields = () => (
    <>
      <TextField
        fullWidth
        label="Field Name"
        value={editedData.config?.field || ''}
        onChange={(e) => updateConfig('field', e.target.value)}
        placeholder="e.g., issue_type, status, author"
        sx={{ mb: 2 }}
      />
      <FormControl fullWidth sx={{ mb: 2 }}>
        <InputLabel>Operator</InputLabel>
        <Select
          value={editedData.config?.operator || 'equals'}
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
        value={editedData.config?.value || ''}
        onChange={(e) => updateConfig('value', e.target.value)}
        placeholder="Value to filter by"
        sx={{ mb: 2 }}
      />
    </>
  );

  const renderDecisionNodeFields = () => (
    <>
      <FormControl fullWidth sx={{ mb: 2 }}>
        <InputLabel>Condition Type</InputLabel>
        <Select
          value={editedData.config?.condition_type || 'confidence_threshold'}
          onChange={(e) => updateConfig('condition_type', e.target.value)}
        >
          <MenuItem value="confidence_threshold">Confidence Threshold</MenuItem>
          <MenuItem value="field_exists">Field Exists</MenuItem>
          <MenuItem value="field_value">Field Value Match</MenuItem>
          <MenuItem value="count_threshold">Count Threshold</MenuItem>
        </Select>
      </FormControl>

      {editedData.config?.condition_type === 'confidence_threshold' && (
        <TextField
          fullWidth
          type="number"
          label="Threshold (%)"
          value={editedData.config?.threshold || 85}
          onChange={(e) => updateConfig('threshold', parseInt(e.target.value))}
          inputProps={{ min: 0, max: 100 }}
          sx={{ mb: 2 }}
          helperText="Links with confidence below this will go to FALSE branch"
        />
      )}
    </>
  );

  const renderCreateLinkActionFields = () => (
    <>
      <FormControl fullWidth sx={{ mb: 2 }}>
        <InputLabel>Link Type</InputLabel>
        <Select
          value={editedData.config?.link_type || 'relates_to'}
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
            checked={editedData.config?.bidirectional || false}
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
            value={editedData.config?.reverse_link_type || ''}
            onChange={(e) => updateConfig('reverse_link_type', e.target.value)}
          >
            <MenuItem value="relates_to">Relates To</MenuItem>
            <MenuItem value="implemented_by">Implemented By</MenuItem>
            <MenuItem value="tested_by">Tested By</MenuItem>
            <MenuItem value="blocked_by">Blocked By</MenuItem>
            <MenuItem value="required_by">Required By</MenuItem>
          </Select>
        </FormControl>
      )}
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
      case 'jiraKeyExtractor':
        return renderJiraKeyExtractorFields();
      case 'filterNode':
        return renderFilterNodeFields();
      case 'decisionNode':
        return renderDecisionNodeFields();
      case 'createLinkAction':
        return renderCreateLinkActionFields();
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
        {/* Node Label */}
        <TextField
          fullWidth
          label="Node Label"
          value={editedData.label || ''}
          onChange={(e) => setEditedData({ ...editedData, label: e.target.value })}
          sx={{ mb: 3 }}
        />

        <Divider sx={{ my: 2 }} />

        {/* Node Type (Read-only) */}
        <Typography variant="caption" color="text.secondary">
          Node Type
        </Typography>
        <Typography variant="body2" sx={{ mb: 3 }}>
          {selectedNode.type}
        </Typography>

        <Divider sx={{ my: 2 }} />

        {/* Node-specific fields */}
        {renderNodeFields()}
      </Box>

      {/* Save Button */}
      <Box sx={{ p: 2, borderTop: 1, borderColor: 'divider' }}>
        <Button
          fullWidth
          variant="contained"
          startIcon={<SaveIcon />}
          onClick={handleSave}
        >
          Apply Changes
        </Button>
      </Box>
    </Drawer>
  );
};

export default PropertiesPanelEditable;
