import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Paper,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  IconButton,
  Button,
  Chip,
  Tooltip,
  Alert,
  Stack,
  Card,
  CardContent,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Slider,
  Skeleton,
  Grid,
} from '@mui/material';
import {
  Add as AddIcon,
  Edit as EditIcon,
  Delete as DeleteIcon,
  Refresh as RefreshIcon,
  Person as PersonIcon,
  Schedule as ScheduleIcon,
  Speed as SpeedIcon,
} from '@mui/icons-material';
import {
  CapacitySetting,
  TeamCapacitySummary,
  listCapacitySettings,
  createCapacitySetting,
  updateCapacitySetting,
  deleteCapacitySetting,
  getTeamCapacitySummary,
} from '../../services/api';
import {
  getFocusFactorColor,
  calculateEffectiveCapacity,
  focusFactorToPercent,
} from '../../hooks/useCapacityCalc';

interface CapacitySettingsPanelProps {
  projectId?: number;
  sprintWeeks?: number;
  sprintId?: number;
  onCapacityChange?: () => void;
}

const FocusFactorSlider: React.FC<{
  value: number;
  onChange: (value: number) => void;
  disabled?: boolean;
}> = ({ value, onChange, disabled }) => {
  const percentage = focusFactorToPercent(value);
  const color = getFocusFactorColor(value);
  const sliderColor = color === 'default' ? 'primary' : color;
  const labelColor = color === 'default' ? 'text.secondary' : `${color}.main`;

  return (
    <Box sx={{ width: '100%' }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
        <Typography variant="body2" color="text.secondary">
          Focus Factor
        </Typography>
        <Typography variant="body2" fontWeight="bold" color={labelColor}>
          {percentage}%
        </Typography>
      </Box>
      <Slider
        value={value}
        min={0.5}
        max={1.0}
        step={0.05}
        onChange={(_, v) => {
          if (!Array.isArray(v)) {
            onChange(v);
          }
        }}
        disabled={disabled}
        marks={[
          { value: 0.5, label: '50%' },
          { value: 0.75, label: '75%' },
          { value: 1.0, label: '100%' },
        ]}
        color={sliderColor}
        valueLabelDisplay="auto"
        valueLabelFormat={(v) => `${focusFactorToPercent(v)}%`}
      />
      <Typography variant="caption" color="text.secondary">
        Percentage of theoretical hours actually productive (meetings, interruptions reduce this)
      </Typography>
    </Box>
  );
};

const CapacitySettingsPanel: React.FC<CapacitySettingsPanelProps> = ({
  projectId,
  sprintWeeks = 2,
  onCapacityChange,
}) => {
  const [settings, setSettings] = useState<CapacitySetting[]>([]);
  const [summary, setSummary] = useState<TeamCapacitySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingSetting, setEditingSetting] = useState<CapacitySetting | null>(null);

  // Form state
  const [formData, setFormData] = useState({
    assignee_email: '',
    assignee_name: '',
    hours_per_week: 40,
    focus_factor: 0.8,
    valid_from: '',
    valid_to: '',
    notes: '',
  });

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [settingsData, summaryData] = await Promise.all([
        listCapacitySettings({ projectId }),
        projectId ? getTeamCapacitySummary(projectId, { sprintWeeks }) : Promise.resolve(null),
      ]);
      setSettings(settingsData.data);
      setSummary(summaryData);
    } catch (err) {
      console.error('Failed to load capacity data:', err);
      setError('Failed to load capacity settings');
    } finally {
      setLoading(false);
    }
  }, [projectId, sprintWeeks]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleOpenDialog = (setting?: CapacitySetting) => {
    if (setting) {
      setEditingSetting(setting);
      setFormData({
        assignee_email: setting.assignee_email,
        assignee_name: setting.assignee_name || '',
        hours_per_week: setting.hours_per_week,
        focus_factor: setting.focus_factor,
        valid_from: setting.valid_from || '',
        valid_to: setting.valid_to || '',
        notes: setting.notes || '',
      });
    } else {
      setEditingSetting(null);
      setFormData({
        assignee_email: '',
        assignee_name: '',
        hours_per_week: 40,
        focus_factor: 0.8,
        valid_from: '',
        valid_to: '',
        notes: '',
      });
    }
    setDialogOpen(true);
  };

  const handleCloseDialog = () => {
    setDialogOpen(false);
    setEditingSetting(null);
  };

  const handleSave = async () => {
    try {
      if (editingSetting) {
        await updateCapacitySetting(editingSetting.id, {
          assigneeName: formData.assignee_name || undefined,
          hoursPerWeek: formData.hours_per_week,
          focusFactor: formData.focus_factor,
          validFrom: formData.valid_from || undefined,
          validTo: formData.valid_to || undefined,
          notes: formData.notes || undefined,
        });
      } else {
        await createCapacitySetting({
          assigneeEmail: formData.assignee_email,
          assigneeName: formData.assignee_name || undefined,
          projectId,
          hoursPerWeek: formData.hours_per_week,
          focusFactor: formData.focus_factor,
          validFrom: formData.valid_from || undefined,
          validTo: formData.valid_to || undefined,
          notes: formData.notes || undefined,
        });
      }
      handleCloseDialog();
      loadData();
      onCapacityChange?.();
    } catch (err) {
      console.error('Failed to save capacity setting:', err);
      setError('Failed to save capacity setting');
    }
  };

  const handleDelete = async (settingId: number) => {
    if (!window.confirm('Are you sure you want to delete this capacity setting?')) return;
    try {
      await deleteCapacitySetting(settingId);
      loadData();
      onCapacityChange?.();
    } catch (err) {
      console.error('Failed to delete capacity setting:', err);
      setError('Failed to delete capacity setting');
    }
  };

  if (loading) {
    return (
      <Paper sx={{ p: 2 }}>
        <Stack spacing={2}>
          <Skeleton variant="rectangular" height={100} />
          <Skeleton variant="rectangular" height={200} />
        </Stack>
      </Paper>
    );
  }

  return (
    <Box>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Summary Cards */}
      {summary && (
        <Grid container spacing={2} sx={{ mb: 3 }}>
          <Grid item xs={12} sm={6} md={3}>
            <Card>
              <CardContent>
                <Stack direction="row" spacing={1} alignItems="center">
                  <PersonIcon color="primary" />
                  <Typography variant="subtitle2" color="text.secondary">
                    Team Members
                  </Typography>
                </Stack>
                <Typography variant="h4" sx={{ mt: 1 }}>
                  {summary.team_members}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <Card>
              <CardContent>
                <Stack direction="row" spacing={1} alignItems="center">
                  <ScheduleIcon color="primary" />
                  <Typography variant="subtitle2" color="text.secondary">
                    Theoretical Capacity
                  </Typography>
                </Stack>
                <Typography variant="h4" sx={{ mt: 1 }}>
                  {summary.total_theoretical_hours}h
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  for {sprintWeeks} week sprint
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <Card>
              <CardContent>
                <Stack direction="row" spacing={1} alignItems="center">
                  <SpeedIcon color="success" />
                  <Typography variant="subtitle2" color="text.secondary">
                    Effective Capacity
                  </Typography>
                </Stack>
                <Typography variant="h4" sx={{ mt: 1 }} color="success.main">
                  {summary.total_effective_hours}h
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  after focus factor
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <Card>
              <CardContent>
                <Stack direction="row" spacing={1} alignItems="center">
                  <SpeedIcon color="warning" />
                  <Typography variant="subtitle2" color="text.secondary">
                    Avg Focus Factor
                  </Typography>
                </Stack>
                <Typography variant="h4" sx={{ mt: 1 }} color="warning.main">
                  {Math.round(summary.average_focus_factor * 100)}%
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}

      {/* Settings Table */}
      <Paper sx={{ p: 2 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
          <Typography variant="h6">Capacity Settings</Typography>
          <Stack direction="row" spacing={1}>
            <Button
              startIcon={<RefreshIcon />}
              onClick={loadData}
              size="small"
            >
              Refresh
            </Button>
            <Button
              variant="contained"
              startIcon={<AddIcon />}
              onClick={() => handleOpenDialog()}
            >
              Add Setting
            </Button>
          </Stack>
        </Stack>

        {settings.length === 0 ? (
          <Alert severity="info">
            No custom capacity settings configured. All team members will use the default (40h/week, 80% focus).
            Add settings for team members with different capacity or focus factors.
          </Alert>
        ) : (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Team Member</TableCell>
                  <TableCell align="right">Hours/Week</TableCell>
                  <TableCell align="right">Focus Factor</TableCell>
                  <TableCell align="right">Effective Capacity</TableCell>
                  <TableCell>Validity</TableCell>
                  <TableCell>Notes</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {settings.map((setting) => (
                  <TableRow key={setting.id}>
                    <TableCell>
                      <Box>
                        <Typography variant="body2" fontWeight="medium">
                          {setting.assignee_name || setting.assignee_email}
                        </Typography>
                        {setting.assignee_name && (
                          <Typography variant="caption" color="text.secondary">
                            {setting.assignee_email}
                          </Typography>
                        )}
                      </Box>
                    </TableCell>
                    <TableCell align="right">
                      <Chip
                        label={`${setting.hours_per_week}h`}
                        size="small"
                        color={setting.hours_per_week < 40 ? 'warning' : 'default'}
                      />
                    </TableCell>
                    <TableCell align="right">
                      <Chip
                        label={`${focusFactorToPercent(setting.focus_factor)}%`}
                        size="small"
                        color={getFocusFactorColor(setting.focus_factor)}
                      />
                    </TableCell>
                    <TableCell align="right">
                      <Typography variant="body2" fontWeight="bold">
                        {setting.effective_capacity?.toFixed(1) || calculateEffectiveCapacity(setting.hours_per_week, setting.focus_factor).toFixed(1)}h/week
                      </Typography>
                    </TableCell>
                    <TableCell>
                      {setting.valid_from || setting.valid_to ? (
                        <Typography variant="caption">
                          {setting.valid_from || '...'} - {setting.valid_to || '...'}
                        </Typography>
                      ) : (
                        <Typography variant="caption" color="text.secondary">
                          Always active
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      {setting.notes && (
                        <Tooltip title={setting.notes}>
                          <Typography
                            variant="caption"
                            sx={{
                              maxWidth: 150,
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                              display: 'block',
                            }}
                          >
                            {setting.notes}
                          </Typography>
                        </Tooltip>
                      )}
                    </TableCell>
                    <TableCell align="right">
                      <Tooltip title="Edit">
                        <IconButton size="small" onClick={() => handleOpenDialog(setting)}>
                          <EditIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Delete">
                        <IconButton
                          size="small"
                          color="error"
                          onClick={() => handleDelete(setting.id)}
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Paper>

      {/* Add/Edit Dialog */}
      <Dialog open={dialogOpen} onClose={handleCloseDialog} maxWidth="sm" fullWidth>
        <DialogTitle>
          {editingSetting ? 'Edit Capacity Setting' : 'Add Capacity Setting'}
        </DialogTitle>
        <DialogContent>
          <Stack spacing={3} sx={{ mt: 1 }}>
            <TextField
              label="Email"
              value={formData.assignee_email}
              onChange={(e) => setFormData({ ...formData, assignee_email: e.target.value })}
              disabled={!!editingSetting}
              required
              fullWidth
              helperText="Team member's email address"
            />
            <TextField
              label="Name (Optional)"
              value={formData.assignee_name}
              onChange={(e) => setFormData({ ...formData, assignee_name: e.target.value })}
              fullWidth
              helperText="Display name for the team member"
            />
            <TextField
              label="Hours per Week"
              type="number"
              value={formData.hours_per_week}
              onChange={(e) =>
                setFormData({ ...formData, hours_per_week: parseFloat(e.target.value) || 40 })
              }
              inputProps={{ min: 0, max: 168, step: 1 }}
              fullWidth
              helperText="Theoretical hours available per week (default: 40)"
            />
            <FocusFactorSlider
              value={formData.focus_factor}
              onChange={(v) => setFormData({ ...formData, focus_factor: v })}
            />
            <Grid container spacing={2}>
              <Grid item xs={6}>
                <TextField
                  label="Valid From"
                  type="date"
                  value={formData.valid_from}
                  onChange={(e) => setFormData({ ...formData, valid_from: e.target.value })}
                  InputLabelProps={{ shrink: true }}
                  fullWidth
                  helperText="Leave empty for immediate effect"
                />
              </Grid>
              <Grid item xs={6}>
                <TextField
                  label="Valid To"
                  type="date"
                  value={formData.valid_to}
                  onChange={(e) => setFormData({ ...formData, valid_to: e.target.value })}
                  InputLabelProps={{ shrink: true }}
                  fullWidth
                  helperText="Leave empty for no expiration"
                />
              </Grid>
            </Grid>
            <TextField
              label="Notes"
              value={formData.notes}
              onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
              multiline
              rows={2}
              fullWidth
              helperText="E.g., 'Part-time contractor', 'On vacation May 1-15'"
            />

            {/* Preview */}
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="subtitle2" gutterBottom>
                Effective Capacity Preview
              </Typography>
              <Typography variant="h5" color="primary">
                {calculateEffectiveCapacity(formData.hours_per_week, formData.focus_factor).toFixed(1)} hours/week
              </Typography>
              <Typography variant="caption" color="text.secondary">
                = {formData.hours_per_week}h x {focusFactorToPercent(formData.focus_factor)}% focus
              </Typography>
            </Paper>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDialog}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleSave}
            disabled={!editingSetting && !formData.assignee_email}
          >
            {editingSetting ? 'Update' : 'Create'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default CapacitySettingsPanel;
