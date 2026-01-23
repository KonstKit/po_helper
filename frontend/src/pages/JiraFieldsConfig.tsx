import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Paper,
  Typography,
  Button,
  Select,
  MenuItem,
  FormControl,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  IconButton,
  TextField,
  Alert,
  CircularProgress,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Tooltip,
  Grid,
  Card,
  CardContent,
  Snackbar,
  type ChipProps,
} from '@mui/material';
import {
  Refresh,
  Save,
  Delete,
  Science,
  Download,
  Upload,
  Check,
  Close,
  Settings as SettingsIcon,
} from '@mui/icons-material';
import type { SelectChangeEvent } from '@mui/material/Select';
import EmptyState from '../components/EmptyState';
import { QuickSetupPanel } from '../components/QuickSetupPanel';
import { AdvancedFieldMapping } from '../components/AdvancedFieldMapping';
import { HelpPanel } from '../components/HelpPanel';
import {
  discoverJiraFields,
  calibrateFields,
  getFieldMappings,
  saveFieldMapping,
  deleteFieldMapping,
  testFieldMapping,
  exportConfiguration,
  importConfiguration,
  FieldMapping,
  JiraField,
  TestMappingResult,
} from '../services/jiraFieldsApi';

const FIELD_TYPES = [
  { value: 'sprint', label: 'Sprint' },
  { value: 'epic_link', label: 'Epic Link' },
  { value: 'story_points', label: 'Story Points' },
  { value: 'business_value', label: 'Business Value' },
  { value: 'team', label: 'Team' },
  { value: 'fix_version', label: 'Fix Version' },
  { value: 'reporter', label: 'Reporter' },
  { value: 'components', label: 'Components' },
];

const JiraFieldsConfig: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [fields, setFields] = useState<Record<string, JiraField>>({});
  const [mappings, setMappings] = useState<FieldMapping[]>([]);
  const [selectedProject, setSelectedProject] = useState<string>('');
  const [calibrating, setCalibrating] = useState(false);
  const [testDialogOpen, setTestDialogOpen] = useState(false);
  const [testIssueKey, setTestIssueKey] = useState('');
  const [testResult, setTestResult] = useState<TestMappingResult | null>(null);
  const [editMapping, setEditMapping] = useState<FieldMapping | null>(null);
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' | 'info' }>({
    open: false,
    message: '',
    severity: 'info',
  });
  const handleEditFieldChange = (event: SelectChangeEvent<string>) => {
    setEditMapping((prev) => {
      if (!prev) {
        return prev;
      }
      return { ...prev, field_id: event.target.value };
    });
  };

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [discoveryResult, mappingsResult] = await Promise.all([
        discoverJiraFields(),
        getFieldMappings(),
      ]);
      setFields(discoveryResult.all_fields || {});
      setMappings(mappingsResult);
    } catch (error) {
      console.error('Failed to load data:', error);
      showSnackbar('Failed to load field data', 'error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleDiscoverFields = async (forceRefresh: boolean = false) => {
    setLoading(true);
    try {
      const result = await discoverJiraFields(forceRefresh);
      setFields(result.all_fields || {});
      showSnackbar(`Discovered ${result.total_fields} fields (${result.custom_fields} custom)`, 'success');
    } catch (error) {
      console.error('Failed to discover fields:', error);
      showSnackbar('Failed to discover fields', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleCalibrate = async () => {
    if (!selectedProject) {
      showSnackbar('Please select a project first', 'error');
      return;
    }

    setCalibrating(true);
    try {
      const result = await calibrateFields(selectedProject);
      if (result.warning) {
        showSnackbar(result.warning, 'info');
      } else {
        showSnackbar(
          `Calibration complete: ${result.auto_mapped} fields auto-mapped`,
          'success'
        );
      }
      await loadData(); // Reload mappings
    } catch (error) {
      console.error('Calibration failed:', error);
      showSnackbar('Calibration failed', 'error');
    } finally {
      setCalibrating(false);
    }
  };

  const handleSaveMapping = async (fieldType: string, fieldId: string) => {
    try {
      await saveFieldMapping(fieldType, fieldId, selectedProject);
      showSnackbar('Field mapping saved', 'success');
      await loadData();
      setEditMapping(null);
    } catch (error) {
      console.error('Failed to save mapping:', error);
      showSnackbar('Failed to save mapping', 'error');
    }
  };

  const handleDeleteMapping = async (mappingId: number) => {
    try {
      await deleteFieldMapping(mappingId);
      showSnackbar('Field mapping deleted', 'success');
      await loadData();
    } catch (error) {
      console.error('Failed to delete mapping:', error);
      showSnackbar('Failed to delete mapping', 'error');
    }
  };

  const handleTestMapping = async () => {
    if (!testIssueKey) {
      showSnackbar('Please enter an issue key', 'error');
      return;
    }

    setLoading(true);
    try {
      const result = await testFieldMapping(testIssueKey);
      setTestResult(result);
      showSnackbar('Test completed successfully', 'success');
    } catch (error) {
      console.error('Test failed:', error);
      showSnackbar('Test failed', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleExport = async () => {
    try {
      const config = await exportConfiguration();
      const blob = new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'jira-field-mappings.json';
      a.click();
      URL.revokeObjectURL(url);
      showSnackbar('Configuration exported', 'success');
    } catch (error) {
      console.error('Export failed:', error);
      showSnackbar('Export failed', 'error');
    }
  };

  const handleImport = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    try {
      const text = await file.text();
      const config = JSON.parse(text);
      const result = await importConfiguration(config);
      showSnackbar(`Imported ${result.mappings_count} mappings`, 'success');
      await loadData();
    } catch (error) {
      console.error('Import failed:', error);
      showSnackbar('Import failed', 'error');
    }
  };

  const showSnackbar = (message: string, severity: 'success' | 'error' | 'info') => {
    setSnackbar({ open: true, message, severity });
  };

  const getConfidenceColor = (confidence?: number): ChipProps['color'] => {
    if (!confidence) return 'default';
    if (confidence > 0.8) return 'success';
    if (confidence > 0.5) return 'warning';
    return 'error';
  };

  // Helper to check which essential fields are mapped
  const getMappedFieldsStatus = () => {
    return {
      sprint: mappings.some((m) => m.field_type === 'sprint'),
      storyPoints: mappings.some((m) => m.field_type === 'story_points'),
      epicLink: mappings.some((m) => m.field_type === 'epic_link'),
      businessValue: mappings.some((m) => m.field_type === 'business_value'),
    };
  };

  const handleAutoMapWrapper = async () => {
    // First discover fields if not already done
    if (Object.keys(fields).length === 0) {
      await handleDiscoverFields(false);
    }
    // Then calibrate
    await handleCalibrate();
  };

  const handleManualSetupClick = () => {
    // Discover fields if not already done
    if (Object.keys(fields).length === 0) {
      handleDiscoverFields(false);
    }
  };

  const showEmptyState = !loading && Object.keys(fields).length === 0;

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Jira Field Configuration
      </Typography>

      <Typography variant="body1" color="text.secondary" paragraph>
        Map Jira fields to enable analytics features like velocity tracking, burndown charts, and ROI calculations.
      </Typography>

      {!showEmptyState && (
        <HelpPanel
          title="💡 Field Mapping Guide"
          description="Different fields enable different analytics features in PO Helper:"
          variant="guide"
          steps={[
            { text: 'Sprint → Required for burndown charts and velocity tracking' },
            { text: 'Story Points → Required for velocity calculations and effort tracking' },
            { text: 'Epic Link → Optional, enables epic-level views and rollup metrics' },
            { text: 'Business Value → Optional, enables ROI calculations and value tracking' },
            { text: 'Team → Optional, enables team-level analytics and comparisons' },
            { text: 'Fix Version → Optional, enables release planning and version tracking' },
          ]}
          docsUrl="https://docs.example.com/jira-field-mapping"
        />
      )}

      {showEmptyState && (
        <Box sx={{ my: 4 }}>
          <EmptyState
            icon={<SettingsIcon sx={{ fontSize: 80 }} />}
            title="Jira Field Mapping Not Configured"
            description="Map your Jira custom fields to enable velocity tracking, sprint analytics, and business value calculations"
            primaryAction={{
              label: 'Discover Fields from Jira',
              onClick: () => handleDiscoverFields(true),
            }}
            secondaryAction={{
              label: 'Manual Mapping',
              onClick: handleManualSetupClick,
            }}
            benefits={[
              'Track story points for team velocity',
              'Link sprints to burndown charts',
              'Calculate business value ROI',
              'Map custom fields for advanced analytics',
            ]}
            setupSteps={[
              'Click "Discover Fields" to scan your Jira instance',
              'Enter a project key and use Auto-Map for quick setup',
              'Review and adjust field mappings as needed',
            ]}
          />
        </Box>
      )}

      {!showEmptyState && (
        <>
          {/* Quick Setup Panel */}
          <QuickSetupPanel
            projectKey={selectedProject}
            onProjectKeyChange={setSelectedProject}
            onAutoMap={handleAutoMapWrapper}
            onManualSetup={handleManualSetupClick}
            mappedFields={getMappedFieldsStatus()}
            isCalibrating={calibrating}
          />

          {/* Advanced Mapping Section */}
          <AdvancedFieldMapping
            fields={fields}
            mappings={mappings}
            onSaveMapping={handleSaveMapping}
            onDeleteMapping={handleDeleteMapping}
          />

          {/* Utilities Section */}
          <Paper sx={{ p: 2, mb: 3 }}>
            <Typography variant="subtitle1" gutterBottom>
              Utilities
            </Typography>
            <Box display="flex" gap={1} flexWrap="wrap">
              <Button
                variant="outlined"
                startIcon={<Refresh />}
                onClick={() => handleDiscoverFields(true)}
                disabled={loading}
              >
                Refresh Fields
              </Button>
              <Button
                variant="outlined"
                startIcon={<Science />}
                onClick={() => setTestDialogOpen(true)}
              >
                Test Mapping
              </Button>
              <Button variant="outlined" startIcon={<Download />} onClick={handleExport}>
                Export Config
              </Button>
              <Button variant="outlined" startIcon={<Upload />} component="label">
                Import Config
                <input type="file" hidden accept=".json" onChange={handleImport} />
              </Button>
            </Box>
          </Paper>

          {/* Statistics Cards */}
          <Grid container spacing={2} sx={{ mb: 3 }}>
            <Grid item xs={12} sm={6} md={3}>
              <Card>
                <CardContent>
                  <Typography color="text.secondary" gutterBottom>
                    Total Fields
                  </Typography>
                  <Typography variant="h4">{Object.keys(fields).length}</Typography>
                </CardContent>
              </Card>
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <Card>
                <CardContent>
                  <Typography color="text.secondary" gutterBottom>
                    Custom Fields
                  </Typography>
                  <Typography variant="h4">
                    {Object.values(fields).filter((f) => f.custom).length}
                  </Typography>
                </CardContent>
              </Card>
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <Card>
                <CardContent>
                  <Typography color="text.secondary" gutterBottom>
                    Mapped Fields
                  </Typography>
                  <Typography variant="h4">{mappings.filter((m) => m.is_active).length}</Typography>
                </CardContent>
              </Card>
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <Card>
                <CardContent>
                  <Typography color="text.secondary" gutterBottom>
                    Auto-Detected
                  </Typography>
                  <Typography variant="h4">
                    {mappings.filter((m) => m.discovery_method === 'auto').length}
                  </Typography>
                </CardContent>
              </Card>
            </Grid>
          </Grid>
        </>
      )}

      {/* Field Mappings Table (Legacy, kept for detailed view) */}
      {!showEmptyState && Object.keys(fields).length > 0 && (
        <Paper sx={{ display: 'none' }}>
        <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
          <Typography variant="h6">Field Mappings</Typography>
        </Box>

        {loading ? (
          <Box display="flex" justifyContent="center" p={4}>
            <CircularProgress />
          </Box>
        ) : (
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>Field Type</TableCell>
                  <TableCell>Jira Field</TableCell>
                  <TableCell>Discovery Method</TableCell>
                  <TableCell>Confidence</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {FIELD_TYPES.map((fieldType) => {
                  const mapping = mappings.find((m) => m.field_type === fieldType.value);
                  const isEditing = editMapping?.field_type === fieldType.value;

                  return (
                    <TableRow key={fieldType.value}>
                      <TableCell>
                        <Typography variant="body2" fontWeight="medium">
                          {fieldType.label}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        {isEditing ? (
                          <FormControl size="small" fullWidth>
                            <Select
                              value={editMapping?.field_id || ''}
                              onChange={handleEditFieldChange}
                            >
                              <MenuItem value="">
                                <em>None</em>
                              </MenuItem>
                              {Object.entries(fields)
                                // Show custom first, then system fields
                                .sort((a, b) => {
                                  const ac = a[1]?.custom ? 0 : 1;
                                  const bc = b[1]?.custom ? 0 : 1;
                                  if (ac !== bc) return ac - bc;
                                  const an = (a[1]?.name || '').toLowerCase();
                                  const bn = (b[1]?.name || '').toLowerCase();
                                  return an.localeCompare(bn);
                                })
                                .map(([id, field]) => (
                                  <MenuItem key={id} value={id}>
                                    {field.name} ({id}) {field.custom ? '' : '• system'}
                                  </MenuItem>
                                ))}
                            </Select>
                          </FormControl>
                        ) : (
                          <Box>
                            {mapping ? (
                              <>
                                <Typography variant="body2">{mapping.field_name || mapping.field_id}</Typography>
                                <Typography variant="caption" color="text.secondary">
                                  {mapping.field_id}
                                </Typography>
                              </>
                            ) : (
                              <Typography variant="body2" color="text.secondary">
                                Not mapped
                              </Typography>
                            )}
                          </Box>
                        )}
                      </TableCell>
                      <TableCell>
                        {mapping && (
                          <Chip
                            size="small"
                            label={mapping.discovery_method || 'manual'}
                            color={mapping.discovery_method === 'auto' ? 'primary' : 'default'}
                          />
                        )}
                      </TableCell>
                      <TableCell>
                        {mapping?.confidence_score && (
                          <Tooltip title={`Confidence: ${(mapping.confidence_score * 100).toFixed(0)}%`}>
                            <Chip
                              size="small"
                              label={`${(mapping.confidence_score * 100).toFixed(0)}%`}
                              color={getConfidenceColor(mapping.confidence_score)}
                            />
                          </Tooltip>
                        )}
                      </TableCell>
                      <TableCell>
                        {mapping?.is_active ? (
                          <Chip size="small" label="Active" color="success" icon={<Check />} />
                        ) : mapping ? (
                          <Chip size="small" label="Inactive" icon={<Close />} />
                        ) : null}
                      </TableCell>
                      <TableCell>
                        {isEditing ? (
                          <Box display="flex" gap={1}>
                            <IconButton
                              size="small"
                              color="primary"
                              onClick={() => {
                                if (editMapping) {
                                  handleSaveMapping(fieldType.value, editMapping.field_id);
                                }
                              }}
                            >
                              <Save />
                            </IconButton>
                            <IconButton size="small" onClick={() => setEditMapping(null)}>
                              <Close />
                            </IconButton>
                          </Box>
                        ) : (
                          <Box display="flex" gap={1}>
                            <IconButton
                              size="small"
                              onClick={() =>
                                setEditMapping({
                                  field_type: fieldType.value,
                                  field_id: mapping?.field_id || '',
                                  is_active: true,
                                })
                              }
                            >
                              <Save />
                            </IconButton>
                            {mapping && (
                              <IconButton
                                size="small"
                                color="error"
                                onClick={() => handleDeleteMapping(mapping.id!)}
                              >
                                <Delete />
                              </IconButton>
                            )}
                          </Box>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>
        )}
        </Paper>
      )}

      {/* Test Dialog */}
      <Dialog open={testDialogOpen} onClose={() => setTestDialogOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>Test Field Mapping</DialogTitle>
        <DialogContent>
          <Box sx={{ pt: 2 }}>
            <TextField
              fullWidth
              label="Issue Key"
              value={testIssueKey}
              onChange={(e) => setTestIssueKey(e.target.value)}
              placeholder="e.g., WAB-2786"
              sx={{ mb: 2 }}
            />

            {testResult && (
              <Box>
                <Alert severity="success" sx={{ mb: 2 }}>
                  Successfully retrieved fields for {testResult.issue_key}
                </Alert>

                {testResult.has_sprint_data && (
                  <Alert severity="info" sx={{ mb: 2 }}>
                    Found {testResult.sprints?.length || 0} sprint(s) for this issue
                  </Alert>
                )}

                <Typography variant="h6" gutterBottom>
                  Mapped Fields:
                </Typography>
                <Paper variant="outlined" sx={{ p: 2, maxHeight: 400, overflow: 'auto' }}>
                  <pre>{JSON.stringify(testResult.mapped_fields, null, 2)}</pre>
                </Paper>
              </Box>
            )}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setTestDialogOpen(false)}>Close</Button>
          <Button variant="contained" onClick={handleTestMapping} disabled={loading}>
            Test
          </Button>
        </DialogActions>
      </Dialog>

      {/* Snackbar */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={6000}
        onClose={() => setSnackbar({ ...snackbar, open: false })}
      >
        <Alert
          onClose={() => setSnackbar({ ...snackbar, open: false })}
          severity={snackbar.severity}
          sx={{ width: '100%' }}
        >
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  );
};

export default JiraFieldsConfig;
