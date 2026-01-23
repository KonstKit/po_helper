import React, { useState } from 'react';
import {
  Box,
  Paper,
  Typography,
  Button,
  IconButton,
  Collapse,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Select,
  MenuItem,
  FormControl,
  Chip,
  Tooltip,
  Alert,
} from '@mui/material';
import {
  ExpandMore as ExpandMoreIcon,
  Delete as DeleteIcon,
  Info as InfoIcon,
} from '@mui/icons-material';
import { JiraField, FieldMapping } from '../services/jiraFieldsApi';

interface AdvancedFieldMappingProps {
  fields: Record<string, JiraField>;
  mappings: FieldMapping[];
  onSaveMapping: (fieldType: string, fieldId: string) => Promise<void>;
  onDeleteMapping: (mappingId: number) => Promise<void>;
}

const FIELD_TYPES = [
  { value: 'sprint', label: 'Sprint', description: 'Links tasks to sprints' },
  { value: 'epic_link', label: 'Epic Link', description: 'Groups tasks by epic' },
  { value: 'story_points', label: 'Story Points', description: 'Estimates task size' },
  { value: 'business_value', label: 'Business Value', description: 'Tracks ROI' },
  { value: 'team', label: 'Team', description: 'Team assignment' },
  { value: 'fix_version', label: 'Fix Version', description: 'Release version' },
  { value: 'reporter', label: 'Reporter', description: 'Issue reporter' },
  { value: 'components', label: 'Components', description: 'Issue components' },
];

export const AdvancedFieldMapping: React.FC<AdvancedFieldMappingProps> = ({
  fields,
  mappings,
  onSaveMapping,
  onDeleteMapping,
}) => {
  const [expanded, setExpanded] = useState(false);
  const [editingType, setEditingType] = useState<string | null>(null);
  const [selectedFieldId, setSelectedFieldId] = useState<string>('');

  const unmappedFieldTypes = FIELD_TYPES.filter(
    (ft) => !mappings.some((m) => m.field_type === ft.value)
  );

  const getConfidenceColor = (confidence?: number) => {
    if (!confidence) return 'default';
    if (confidence > 0.8) return 'success';
    if (confidence > 0.5) return 'warning';
    return 'error';
  };

  const handleStartMapping = (fieldType: string) => {
    setEditingType(fieldType);
    // Pre-select if there's a likely candidate
    const likelyField = Object.entries(fields).find(([, field]) =>
      field.name.toLowerCase().includes(fieldType.replace('_', ' '))
    );
    if (likelyField) {
      setSelectedFieldId(likelyField[0]);
    }
  };

  const handleSaveMapping = async () => {
    if (editingType && selectedFieldId) {
      await onSaveMapping(editingType, selectedFieldId);
      setEditingType(null);
      setSelectedFieldId('');
    }
  };

  const handleCancelMapping = () => {
    setEditingType(null);
    setSelectedFieldId('');
  };

  return (
    <Paper sx={{ p: 2 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center">
        <Box display="flex" alignItems="center" gap={1}>
          <Typography variant="h6">Advanced Field Mapping</Typography>
          <Chip
            label={`${mappings.length} / ${FIELD_TYPES.length} mapped`}
            size="small"
            color={mappings.length === FIELD_TYPES.length ? 'success' : 'default'}
          />
        </Box>
        <IconButton
          onClick={() => setExpanded(!expanded)}
          sx={{
            transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)',
            transition: 'transform 0.3s',
          }}
        >
          <ExpandMoreIcon />
        </IconButton>
      </Box>

      <Collapse in={expanded}>
        <Box mt={2}>
          <Alert severity="info" sx={{ mb: 2 }}>
            <Typography variant="body2">
              Map additional Jira fields for advanced analytics. Each field type corresponds to a
              specific feature in PO Helper.
            </Typography>
          </Alert>

          {/* Mapped Fields Table */}
          <Typography variant="subtitle2" gutterBottom sx={{ mt: 2 }}>
            Currently Mapped Fields
          </Typography>
          <TableContainer sx={{ mb: 3 }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Field Type</TableCell>
                  <TableCell>Jira Field</TableCell>
                  <TableCell>Field ID</TableCell>
                  <TableCell align="center">Confidence</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {mappings.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} align="center" sx={{ py: 3 }}>
                      <Typography color="text.secondary">
                        No fields mapped yet. Use Quick Setup or add mappings below.
                      </Typography>
                    </TableCell>
                  </TableRow>
                ) : (
                  mappings.map((mapping) => (
                    <TableRow key={mapping.id ?? mapping.field_id}>
                      <TableCell>
                        <Box display="flex" alignItems="center" gap={1}>
                          {FIELD_TYPES.find((ft) => ft.value === mapping.field_type)?.label ||
                            mapping.field_type}
                          <Tooltip
                            title={
                              FIELD_TYPES.find((ft) => ft.value === mapping.field_type)
                                ?.description || ''
                            }
                          >
                            <InfoIcon fontSize="small" color="action" />
                          </Tooltip>
                        </Box>
                      </TableCell>
                      <TableCell>{mapping.jira_field_name}</TableCell>
                      <TableCell>
                        <Typography variant="body2" fontFamily="monospace">
                          {mapping.jira_field_id}
                        </Typography>
                      </TableCell>
                      <TableCell align="center">
                        {mapping.confidence && (
                          <Chip
                            label={`${Math.round(mapping.confidence * 100)}%`}
                            size="small"
                            color={getConfidenceColor(mapping.confidence)}
                          />
                        )}
                      </TableCell>
                      <TableCell align="right">
                        <IconButton
                          size="small"
                          color="error"
                          onClick={() => {
                            if (mapping.id !== undefined) {
                              onDeleteMapping(mapping.id);
                            }
                          }}
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </TableContainer>

          {/* Unmapped Fields */}
          {unmappedFieldTypes.length > 0 && (
            <>
              <Typography variant="subtitle2" gutterBottom>
                Available Field Types ({unmappedFieldTypes.length})
              </Typography>
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Field Type</TableCell>
                      <TableCell>Description</TableCell>
                      <TableCell align="right">Actions</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {unmappedFieldTypes.map((fieldType) => (
                      <TableRow key={fieldType.value}>
                        <TableCell>
                          <Typography fontWeight={600}>{fieldType.label}</Typography>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2" color="text.secondary">
                            {fieldType.description}
                          </Typography>
                        </TableCell>
                        <TableCell align="right">
                          {editingType === fieldType.value ? (
                            <Box display="flex" gap={1} justifyContent="flex-end">
                              <FormControl size="small" sx={{ minWidth: 200 }}>
                                <Select
                                  value={selectedFieldId}
                                  onChange={(e) => setSelectedFieldId(e.target.value)}
                                  displayEmpty
                                >
                                  <MenuItem value="" disabled>
                                    Select Jira field...
                                  </MenuItem>
                                  {Object.entries(fields).map(([id, field]) => (
                                    <MenuItem key={id} value={id}>
                                      {field.name} ({id})
                                    </MenuItem>
                                  ))}
                                </Select>
                              </FormControl>
                              <Button
                                size="small"
                                variant="contained"
                                onClick={handleSaveMapping}
                                disabled={!selectedFieldId}
                              >
                                Save
                              </Button>
                              <Button
                                size="small"
                                variant="outlined"
                                onClick={handleCancelMapping}
                              >
                                Cancel
                              </Button>
                            </Box>
                          ) : (
                            <Button
                              size="small"
                              variant="outlined"
                              onClick={() => handleStartMapping(fieldType.value)}
                            >
                              Map Field
                            </Button>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </>
          )}
        </Box>
      </Collapse>
    </Paper>
  );
};
