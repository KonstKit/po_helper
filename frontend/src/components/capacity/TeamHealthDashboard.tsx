import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Paper,
  Typography,
  Grid,
  Card,
  CardContent,
  Stack,
  Alert,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Slider,
  Skeleton,
  Chip,
  LinearProgress,
} from '@mui/material';
import type { ChipProps } from '@mui/material';
import {
  Add as AddIcon,
  Refresh as RefreshIcon,
  TrendingUp as TrendingUpIcon,
  TrendingDown as TrendingDownIcon,
  TrendingFlat as TrendingFlatIcon,
  Mood as MoodIcon,
  MoodBad as MoodBadIcon,
  SentimentSatisfied as NeutralIcon,
  Warning as WarningIcon,
} from '@mui/icons-material';
import {
  TeamHealthSummary,
  createTeamHealthCheck,
  getTeamHealthSummary,
} from '../../services/api';
import { getErrorMessage } from '../../utils/errorUtils';

interface TeamHealthDashboardProps {
  projectId: number;
  sprintId?: number;
  onHealthCheckAdded?: () => void;
}

type HealthMetricKey =
  | 'satisfaction'
  | 'workload_balance'
  | 'technical_debt_pressure'
  | 'collaboration_quality';

const METRIC_LABELS: Record<
  HealthMetricKey,
  { label: string; description: string; inverted?: boolean }
> = {
  satisfaction: {
    label: 'Team Satisfaction',
    description: 'Overall team satisfaction with work and environment',
  },
  workload_balance: {
    label: 'Workload Balance',
    description: 'How balanced the workload feels across the team',
  },
  technical_debt_pressure: {
    label: 'Tech Debt Pressure',
    description: 'How much technical debt is affecting work',
    inverted: true, // Higher = worse
  },
  collaboration_quality: {
    label: 'Collaboration',
    description: 'Quality of team collaboration and communication',
  },
};

type TrendDirection = 'improving' | 'declining' | 'stable';
const METRIC_KEYS: HealthMetricKey[] = [
  'satisfaction',
  'workload_balance',
  'technical_debt_pressure',
  'collaboration_quality',
];

interface HealthFormData {
  check_date: string;
  satisfaction: number;
  workload_balance: number;
  technical_debt_pressure: number;
  collaboration_quality: number;
  respondent_count: number;
  notes: string;
}

const MetricSlider: React.FC<{
  label: string;
  description: string;
  value: number | undefined;
  onChange: (value: number) => void;
  inverted?: boolean;
}> = ({ label, description, value, onChange, inverted }) => {
  const displayValue = value ?? 3;
  const color = inverted
    ? displayValue >= 4 ? 'error' : displayValue >= 3 ? 'warning' : 'success'
    : displayValue >= 4 ? 'success' : displayValue >= 3 ? 'warning' : 'error';

  return (
    <Box sx={{ mb: 2 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
        <Box>
          <Typography variant="body2" fontWeight="medium">
            {label}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {description}
          </Typography>
        </Box>
        <Typography variant="h6" color={`${color}.main`}>
          {value?.toFixed(1) || '-'}
        </Typography>
      </Box>
      <Slider
        value={displayValue}
        min={1}
        max={5}
        step={0.5}
        onChange={(_, v) => {
          if (!Array.isArray(v)) {
            onChange(v);
          }
        }}
        marks={[
          { value: 1, label: '1' },
          { value: 3, label: '3' },
          { value: 5, label: '5' },
        ]}
        color={color}
        valueLabelDisplay="auto"
      />
    </Box>
  );
};

const HappinessGauge: React.FC<{ value?: number; size?: 'small' | 'large' }> = ({
  value,
  size = 'large',
}) => {
  if (value === undefined) {
    return <Typography color="text.secondary">No data</Typography>;
  }

  const Icon = value >= 4 ? MoodIcon : value >= 3 ? NeutralIcon : MoodBadIcon;
  const color = value >= 4 ? 'success' : value >= 3 ? 'warning' : 'error';
  const iconSize = size === 'large' ? 64 : 32;

  return (
    <Stack alignItems="center" spacing={1}>
      <Icon sx={{ fontSize: iconSize }} color={color} />
      <Typography variant={size === 'large' ? 'h3' : 'h5'} color={`${color}.main`}>
        {value.toFixed(1)}
      </Typography>
      <Typography variant="caption" color="text.secondary">
        out of 5
      </Typography>
    </Stack>
  );
};

const TREND_CONFIG: Record<
  TrendDirection,
  { icon: typeof TrendingUpIcon; color: ChipProps['color']; label: string }
> = {
  improving: { icon: TrendingUpIcon, color: 'success', label: 'Improving' },
  declining: { icon: TrendingDownIcon, color: 'error', label: 'Declining' },
  stable: { icon: TrendingFlatIcon, color: 'info', label: 'Stable' },
};

const TrendIndicator: React.FC<{ direction: TrendDirection }> = ({ direction }) => {
  const config = TREND_CONFIG[direction];
  const Icon = config.icon;

  return (
    <Chip
      icon={<Icon />}
      label={config.label}
      color={config.color}
      size="small"
      variant="outlined"
    />
  );
};

const BurnoutRiskIndicator: React.FC<{ score?: number }> = ({ score }) => {
  if (score === undefined) return null;

  const percentage = Math.round(score * 100);
  const color = score >= 0.7 ? 'error' : score >= 0.4 ? 'warning' : 'success';
  const label = score >= 0.7 ? 'High Risk' : score >= 0.4 ? 'Moderate' : 'Low Risk';

  return (
    <Card sx={{ bgcolor: `${color}.50`, border: 1, borderColor: `${color}.200` }}>
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
          <WarningIcon color={color} />
          <Typography variant="subtitle2">Burnout Risk</Typography>
        </Stack>
        <Typography variant="h4" color={`${color}.main`}>
          {percentage}%
        </Typography>
        <Chip label={label} color={color} size="small" sx={{ mt: 1 }} />
        <LinearProgress
          variant="determinate"
          value={percentage}
          color={color}
          sx={{ mt: 1, height: 8, borderRadius: 4 }}
        />
      </CardContent>
    </Card>
  );
};

const TeamHealthDashboard: React.FC<TeamHealthDashboardProps> = ({
  projectId,
  sprintId,
  onHealthCheckAdded,
}) => {
  const [summary, setSummary] = useState<TeamHealthSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  // Form state for new health check
  const [formData, setFormData] = useState<HealthFormData>({
    check_date: new Date().toISOString().split('T')[0],
    satisfaction: 3,
    workload_balance: 3,
    technical_debt_pressure: 3,
    collaboration_quality: 3,
    respondent_count: 1,
    notes: '',
  });

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const summaryData = await getTeamHealthSummary(projectId, { periodDays: 10 });
      setSummary(summaryData);
    } catch (err) {
      console.error('Failed to load health data:', err);
      setError(getErrorMessage(err, 'Failed to load team health data'));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleSaveHealthCheck = async () => {
    try {
      // Calculate happiness index (weighted average, with tech debt inverted)
      const metrics = [
        formData.satisfaction,
        formData.workload_balance,
        6 - formData.technical_debt_pressure, // Invert: 5 becomes 1, 1 becomes 5
        formData.collaboration_quality,
      ];
      const happiness_index = metrics.reduce((a, b) => a + b, 0) / metrics.length;

      await createTeamHealthCheck({
        projectId,
        sprintId,
        checkDate: formData.check_date,
        satisfaction: formData.satisfaction,
        workloadBalance: formData.workload_balance,
        technicalDebtPressure: formData.technical_debt_pressure,
        collaborationQuality: formData.collaboration_quality,
        happinessIndex: happiness_index,
        respondentCount: formData.respondent_count,
        notes: formData.notes || undefined,
      });
      setDialogOpen(false);
      loadData();
      onHealthCheckAdded?.();
    } catch (err) {
      console.error('Failed to save health check:', err);
      setError(getErrorMessage(err, 'Failed to save health check'));
    }
  };

  if (loading) {
    return (
      <Paper sx={{ p: 2 }}>
        <Stack spacing={2}>
          <Skeleton variant="rectangular" height={150} />
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

      {/* Header */}
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 3 }}>
        <Typography variant="h6">Team Health</Typography>
        <Stack direction="row" spacing={1}>
          <Button startIcon={<RefreshIcon />} onClick={loadData} size="small">
            Refresh
          </Button>
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setDialogOpen(true)}>
            Add Health Check
          </Button>
        </Stack>
      </Stack>

      {/* Main Stats */}
      <Grid container spacing={3}>
        {/* Happiness Index */}
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 3, height: '100%', textAlign: 'center' }}>
            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
              Happiness Index
            </Typography>
            <HappinessGauge value={summary?.latest_happiness_index} />
            {summary && (
              <Box sx={{ mt: 2 }}>
                <TrendIndicator direction={summary.trend_direction} />
              </Box>
            )}
          </Paper>
        </Grid>

        {/* Burnout Risk */}
        <Grid item xs={12} md={4}>
          <BurnoutRiskIndicator score={summary?.latest_burnout_risk} />
        </Grid>

        {/* Check History */}
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 2, height: '100%' }}>
            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
              Health Check History
            </Typography>
            {summary?.checks_count === 0 ? (
              <Alert severity="info" sx={{ mt: 1 }}>
                No health checks recorded yet. Add your first check to start tracking team health.
              </Alert>
            ) : (
              <Stack spacing={1} sx={{ mt: 1 }}>
                {summary?.trend_data.slice(0, 5).map((trend, idx) => (
                  <Box
                    key={idx}
                    sx={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                    }}
                  >
                    <Typography variant="caption" color="text.secondary">
                      {new Date(trend.check_date).toLocaleDateString()}
                    </Typography>
                    <Stack direction="row" spacing={1} alignItems="center">
                      <LinearProgress
                        variant="determinate"
                        value={((trend.happiness_index || 0) / 5) * 100}
                        sx={{ width: 80, height: 6, borderRadius: 3 }}
                        color={
                          (trend.happiness_index || 0) >= 4
                            ? 'success'
                            : (trend.happiness_index || 0) >= 3
                            ? 'warning'
                            : 'error'
                        }
                      />
                      <Typography variant="body2" fontWeight="medium">
                        {trend.happiness_index?.toFixed(1) || '-'}
                      </Typography>
                    </Stack>
                  </Box>
                ))}
              </Stack>
            )}
            <Typography variant="caption" color="text.secondary" sx={{ mt: 2, display: 'block' }}>
              {summary?.checks_count || 0} total checks recorded
            </Typography>
          </Paper>
        </Grid>
      </Grid>

      {/* Add Health Check Dialog */}
      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Record Team Health Check</DialogTitle>
        <DialogContent>
          <Stack spacing={3} sx={{ mt: 1 }}>
            <TextField
              label="Check Date"
              type="date"
              value={formData.check_date}
              onChange={(e) => setFormData({ ...formData, check_date: e.target.value })}
              InputLabelProps={{ shrink: true }}
              fullWidth
            />

            {METRIC_KEYS.map((key) => {
              const { label, description, inverted } = METRIC_LABELS[key];
              return (
                <MetricSlider
                  key={key}
                  label={label}
                  description={description}
                  value={formData[key]}
                  onChange={(v) => setFormData({ ...formData, [key]: v })}
                  inverted={inverted}
                />
              );
            })}

            <TextField
              label="Respondent Count"
              type="number"
              value={formData.respondent_count}
              onChange={(e) =>
                setFormData({ ...formData, respondent_count: parseInt(e.target.value) || 1 })
              }
              inputProps={{ min: 1 }}
              fullWidth
              helperText="Number of team members who participated in the check"
            />

            <TextField
              label="Notes"
              value={formData.notes}
              onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
              multiline
              rows={2}
              fullWidth
              helperText="Any context or observations about this health check"
            />

            {/* Preview */}
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="subtitle2" gutterBottom>
                Calculated Happiness Index
              </Typography>
              <HappinessGauge
                value={
                  (formData.satisfaction +
                    formData.workload_balance +
                    (6 - formData.technical_debt_pressure) +
                    formData.collaboration_quality) /
                  4
                }
                size="small"
              />
            </Paper>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleSaveHealthCheck}>
            Save Health Check
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default TeamHealthDashboard;
