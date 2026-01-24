/**
 * MatrixConfigPanel - Saved matrix configurations (projections) management.
 *
 * Allows users to:
 * - List saved configurations
 * - Load/apply a saved configuration
 * - Save current filters as new configuration
 * - Edit/delete existing configurations
 * - Set default configuration
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  IconButton,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemSecondaryAction,
  ListItemText,
  Paper,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import SaveIcon from '@mui/icons-material/Save';
import FolderOpenIcon from '@mui/icons-material/FolderOpen';
import DeleteIcon from '@mui/icons-material/Delete';
import EditIcon from '@mui/icons-material/Edit';
import StarIcon from '@mui/icons-material/Star';
import StarBorderIcon from '@mui/icons-material/StarBorder';
import AddIcon from '@mui/icons-material/Add';
import RefreshIcon from '@mui/icons-material/Refresh';
import type {
  MatrixConfig,
  MatrixConfigCreate,
  RTMFilters,
  RTMPagination,
} from '../../services/api/types';
import {
  listMatrixConfigs,
  createMatrixConfig,
  updateMatrixConfig,
  deleteMatrixConfig,
} from '../../services/api/traceability';
import { getErrorMessage } from '../../utils/errorUtils';

interface MatrixConfigPanelProps {
  projectId?: number;
  currentFilters: RTMFilters;
  onLoadConfig: (filters: RTMFilters, pagination?: RTMPagination) => void;
}

interface ConfigFormData {
  name: string;
  description: string;
}

const MatrixConfigPanel: React.FC<MatrixConfigPanelProps> = ({
  projectId,
  currentFilters,
  onLoadConfig,
}) => {
  // Saved configurations list
  const [configs, setConfigs] = useState<MatrixConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Dialog states
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [editingConfig, setEditingConfig] = useState<MatrixConfig | null>(null);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [configToDelete, setConfigToDelete] = useState<MatrixConfig | null>(null);

  // Form data
  const [formData, setFormData] = useState<ConfigFormData>({
    name: '',
    description: '',
  });
  const [saving, setSaving] = useState(false);

  // Fetch configurations
  const fetchConfigs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listMatrixConfigs({ projectId });
      setConfigs(data);
    } catch (err) {
      console.error('Failed to load matrix configs', err);
      setError(getErrorMessage(err, 'Failed to load saved configurations'));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  // Fetch on mount and when projectId changes
  useEffect(() => {
    fetchConfigs();
  }, [fetchConfigs]);

  // Handle save dialog open
  const handleOpenSaveDialog = useCallback((config?: MatrixConfig) => {
    if (config) {
      // Editing existing config
      setEditingConfig(config);
      setFormData({
        name: config.name,
        description: config.description || '',
      });
    } else {
      // Creating new config
      setEditingConfig(null);
      setFormData({ name: '', description: '' });
    }
    setSaveDialogOpen(true);
  }, []);

  // Handle save
  const handleSave = useCallback(async () => {
    if (!formData.name.trim()) return;

    setSaving(true);
    try {
      if (editingConfig) {
        // Update existing
        await updateMatrixConfig(editingConfig.id, {
          name: formData.name.trim(),
          description: formData.description.trim() || null,
          filters: currentFilters,
        });
      } else {
        // Create new
        const payload: MatrixConfigCreate = {
          project_id: projectId,
          name: formData.name.trim(),
          description: formData.description.trim() || null,
          filters: currentFilters,
        };
        await createMatrixConfig(payload);
      }
      setSaveDialogOpen(false);
      fetchConfigs();
    } catch (err) {
      console.error('Failed to save config', err);
      setError(getErrorMessage(err, 'Failed to save configuration'));
    } finally {
      setSaving(false);
    }
  }, [formData, editingConfig, currentFilters, projectId, fetchConfigs]);

  // Handle load configuration
  const handleLoadConfig = useCallback(
    (config: MatrixConfig) => {
      onLoadConfig(config.filters || {}, config.pagination || undefined);
    },
    [onLoadConfig]
  );

  // Handle set default
  const handleSetDefault = useCallback(
    async (config: MatrixConfig) => {
      try {
        // First, unset any existing default
        const currentDefault = configs.find((c) => c.is_default && c.id !== config.id);
        if (currentDefault) {
          await updateMatrixConfig(currentDefault.id, { is_default: false });
        }
        // Then set new default
        await updateMatrixConfig(config.id, { is_default: !config.is_default });
        fetchConfigs();
      } catch (err) {
        console.error('Failed to set default', err);
        setError(getErrorMessage(err, 'Failed to update default configuration'));
      }
    },
    [configs, fetchConfigs]
  );

  // Handle delete confirmation
  const handleDeleteClick = useCallback((config: MatrixConfig) => {
    setConfigToDelete(config);
    setDeleteConfirmOpen(true);
  }, []);

  // Handle delete
  const handleDelete = useCallback(async () => {
    if (!configToDelete) return;

    try {
      await deleteMatrixConfig(configToDelete.id);
      setDeleteConfirmOpen(false);
      setConfigToDelete(null);
      fetchConfigs();
    } catch (err) {
      console.error('Failed to delete config', err);
      setError(getErrorMessage(err, 'Failed to delete configuration'));
    }
  }, [configToDelete, fetchConfigs]);

  // Format date
  const formatDate = (dateStr: string): string => {
    return new Date(dateStr).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  // Count filters in a config
  const countFilters = (config: MatrixConfig): number => {
    const f = config.filters || {};
    return [
      f.row_types?.length ?? 0,
      f.col_types?.length ?? 0,
      f.row_statuses?.length ?? 0,
      f.col_statuses?.length ?? 0,
      f.link_types?.length ?? 0,
      f.min_confidence !== undefined ? 1 : 0,
      f.search_query ? 1 : 0,
    ].reduce((sum, count) => sum + (count > 0 ? 1 : 0), 0);
  };

  return (
    <Paper sx={{ p: 2 }}>
      {/* Header */}
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        sx={{ mb: 2 }}
      >
        <Stack direction="row" spacing={1} alignItems="center">
          <FolderOpenIcon fontSize="small" color="action" />
          <Typography variant="subtitle2">Saved Projections</Typography>
        </Stack>
        <Stack direction="row" spacing={0.5}>
          <Tooltip title="Refresh list">
            <IconButton size="small" onClick={fetchConfigs} disabled={loading}>
              <RefreshIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title="Save current filters">
            <IconButton
              size="small"
              color="primary"
              onClick={() => handleOpenSaveDialog()}
            >
              <AddIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Stack>
      </Stack>

      {/* Error display */}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Loading state */}
      {loading && (
        <Box sx={{ textAlign: 'center', py: 2 }}>
          <CircularProgress size={24} />
        </Box>
      )}

      {/* Empty state */}
      {!loading && configs.length === 0 && (
        <Box sx={{ textAlign: 'center', py: 3 }}>
          <Typography variant="body2" color="text.secondary" gutterBottom>
            No saved projections yet.
          </Typography>
          <Button
            variant="outlined"
            size="small"
            startIcon={<SaveIcon />}
            onClick={() => handleOpenSaveDialog()}
            sx={{ mt: 1 }}
          >
            Save Current Filters
          </Button>
        </Box>
      )}

      {/* Configurations list */}
      {configs.length > 0 && (
        <List dense disablePadding>
          {configs.map((config, index) => (
            <React.Fragment key={config.id}>
              {index > 0 && <Divider />}
              <ListItem disablePadding>
                <ListItemButton onClick={() => handleLoadConfig(config)}>
                  <ListItemIcon sx={{ minWidth: 36 }}>
                    <Tooltip
                      title={config.is_default ? 'Default projection' : 'Set as default'}
                    >
                      <IconButton
                        size="small"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleSetDefault(config);
                        }}
                      >
                        {config.is_default ? (
                          <StarIcon fontSize="small" color="warning" />
                        ) : (
                          <StarBorderIcon fontSize="small" />
                        )}
                      </IconButton>
                    </Tooltip>
                  </ListItemIcon>
                  <ListItemText
                    primary={
                      <Stack direction="row" spacing={1} alignItems="center">
                        <Typography variant="body2" noWrap>
                          {config.name}
                        </Typography>
                        {countFilters(config) > 0 && (
                          <Chip
                            size="small"
                            label={`${countFilters(config)} filters`}
                            sx={{ height: 18, fontSize: '0.7rem' }}
                          />
                        )}
                      </Stack>
                    }
                    secondary={
                      config.description ||
                      `Created ${formatDate(config.created_at)}`
                    }
                    secondaryTypographyProps={{
                      variant: 'caption',
                      noWrap: true,
                    }}
                  />
                  <ListItemSecondaryAction>
                    <Stack direction="row" spacing={0.5}>
                      <Tooltip title="Edit">
                        <IconButton
                          size="small"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleOpenSaveDialog(config);
                          }}
                        >
                          <EditIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Delete">
                        <IconButton
                          size="small"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDeleteClick(config);
                          }}
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </Stack>
                  </ListItemSecondaryAction>
                </ListItemButton>
              </ListItem>
            </React.Fragment>
          ))}
        </List>
      )}

      {/* Save/Edit Dialog */}
      <Dialog
        open={saveDialogOpen}
        onClose={() => setSaveDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>
          {editingConfig ? 'Edit Projection' : 'Save Current Filters'}
        </DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              autoFocus
              fullWidth
              label="Name"
              value={formData.name}
              onChange={(e) =>
                setFormData((prev) => ({ ...prev, name: e.target.value }))
              }
              placeholder="e.g., Requirements → Tests"
              required
            />
            <TextField
              fullWidth
              label="Description"
              value={formData.description}
              onChange={(e) =>
                setFormData((prev) => ({ ...prev, description: e.target.value }))
              }
              placeholder="Optional description..."
              multiline
              rows={2}
            />
            {!editingConfig && (
              <Alert severity="info" sx={{ mt: 1 }}>
                This will save the current filter settings as a reusable projection.
              </Alert>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSaveDialogOpen(false)} disabled={saving}>
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={handleSave}
            disabled={!formData.name.trim() || saving}
            startIcon={saving ? <CircularProgress size={16} /> : <SaveIcon />}
          >
            {editingConfig ? 'Update' : 'Save'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog
        open={deleteConfirmOpen}
        onClose={() => setDeleteConfirmOpen(false)}
      >
        <DialogTitle>Delete Projection?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Are you sure you want to delete &quot;{configToDelete?.name}&quot;?
            This action cannot be undone.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteConfirmOpen(false)}>Cancel</Button>
          <Button color="error" onClick={handleDelete}>
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </Paper>
  );
};

export default MatrixConfigPanel;
