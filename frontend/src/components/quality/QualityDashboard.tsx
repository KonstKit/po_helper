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
  Chip,
  Skeleton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
} from '@mui/material';
import type { SelectChangeEvent } from '@mui/material/Select';
import {
  BugReport as BugIcon,
  TrendingUp as TrendingUpIcon,
  TrendingDown as TrendingDownIcon,
  TrendingFlat as TrendingFlatIcon,
  Refresh as RefreshIcon,
  Add as AddIcon,
  Speed as SpeedIcon,
  Timer as TimerIcon,
  Warning as WarningIcon,
} from '@mui/icons-material';
import { Line, Doughnut, Bar } from 'react-chartjs-2';
import {
  QualityDashboard as QualityDashboardData,
  QualitySummary,
  EscapedDefect,
  EscapedDefectCreate,
  RootCauseAnalysis,
  ComponentAnalysis,
  QualityTrendData,
  getQualityDashboard,
  createEscapedDefect,
  SeverityLevel,
  DefectStatus,
  RootCause,
} from '../../services/api';

const SEVERITY_LEVELS: SeverityLevel[] = ['critical', 'high', 'medium', 'low'];
const DEFECT_STATUSES: DefectStatus[] = ['open', 'investigating', 'resolved', 'closed'];
const ROOT_CAUSES: RootCause[] = [
  'missing_test',
  'edge_case',
  'integration',
  'regression',
  'environment',
  'configuration',
  'third_party',
  'unknown',
];

const SEVERITY_LEVEL_SET = new Set<string>(SEVERITY_LEVELS);
const DEFECT_STATUS_SET = new Set<string>(DEFECT_STATUSES);
const ROOT_CAUSE_SET = new Set<string>(ROOT_CAUSES);

const isSeverityLevel = (value: string): value is SeverityLevel =>
  SEVERITY_LEVEL_SET.has(value);

const isDefectStatus = (value: string): value is DefectStatus =>
  DEFECT_STATUS_SET.has(value);

const isRootCause = (value: string): value is RootCause =>
  ROOT_CAUSE_SET.has(value);

interface QualityDashboardProps {
  projectId: number;
  sprintId?: number;
  onDefectAdded?: () => void;
}

// Severity color mapping
const SEVERITY_COLORS: Record<SeverityLevel, string> = {
  critical: '#d32f2f',
  high: '#f57c00',
  medium: '#fbc02d',
  low: '#388e3c',
};

const SEVERITY_OPTIONS: SeverityLevel[] = ['critical', 'high', 'medium', 'low'];
const STATUS_OPTIONS: DefectStatus[] = ['open', 'investigating', 'resolved', 'closed'];
const ROOT_CAUSE_OPTIONS: RootCause[] = [
  'missing_test', 'edge_case', 'integration', 'regression',
  'environment', 'configuration', 'third_party', 'unknown'
];

// Metric card component
const MetricCard: React.FC<{
  title: string;
  value: string | number | undefined;
  subtitle?: string;
  icon: React.ReactNode;
  color?: string;
  trend?: 'up' | 'down' | 'stable';
  trendLabel?: string;
}> = ({ title, value, subtitle, icon, color = 'primary.main', trend, trendLabel }) => (
  <Card sx={{ height: '100%' }}>
    <CardContent>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
        <Box>
          <Typography variant="body2" color="text.secondary" gutterBottom>
            {title}
          </Typography>
          <Typography variant="h4" color={color} fontWeight="bold">
            {value ?? '-'}
          </Typography>
          {subtitle && (
            <Typography variant="caption" color="text.secondary">
              {subtitle}
            </Typography>
          )}
        </Box>
        <Box sx={{ color, opacity: 0.8 }}>{icon}</Box>
      </Stack>
      {trend && (
        <Stack direction="row" alignItems="center" spacing={0.5} sx={{ mt: 1 }}>
          {trend === 'up' && <TrendingUpIcon fontSize="small" color="success" />}
          {trend === 'down' && <TrendingDownIcon fontSize="small" color="error" />}
          {trend === 'stable' && <TrendingFlatIcon fontSize="small" color="info" />}
          <Typography variant="caption" color="text.secondary">
            {trendLabel}
          </Typography>
        </Stack>
      )}
    </CardContent>
  </Card>
);

// DRE Gauge component
const DREGauge: React.FC<{ value?: number }> = ({ value }) => {
  if (value === undefined) {
    return <Typography color="text.secondary">No DRE data</Typography>;
  }

  const color = value >= 85 ? '#4caf50' : value >= 70 ? '#ff9800' : '#f44336';
  const label = value >= 85 ? 'Excellent' : value >= 70 ? 'Good' : 'Needs Improvement';

  return (
    <Box textAlign="center">
      <Box
        sx={{
          position: 'relative',
          width: 120,
          height: 120,
          margin: '0 auto',
        }}
      >
        <Doughnut
          data={{
            datasets: [{
              data: [value, 100 - value],
              backgroundColor: [color, '#e0e0e0'],
              borderWidth: 0,
            }],
          }}
          options={{
            cutout: '70%',
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
          }}
        />
        <Box
          sx={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            textAlign: 'center',
          }}
        >
          <Typography variant="h5" fontWeight="bold" color={color}>
            {value.toFixed(0)}%
          </Typography>
        </Box>
      </Box>
      <Chip label={label} size="small" sx={{ mt: 1, bgcolor: color, color: 'white' }} />
      <Typography variant="caption" display="block" color="text.secondary" sx={{ mt: 0.5 }}>
        Defect Removal Efficiency
      </Typography>
    </Box>
  );
};

// Severity breakdown chart
const SeverityChart: React.FC<{ summary: QualitySummary }> = ({ summary }) => {
  const data = {
    labels: ['Critical', 'High', 'Medium', 'Low'],
    datasets: [{
      data: [summary.critical_count, summary.high_count, summary.medium_count, summary.low_count],
      backgroundColor: [SEVERITY_COLORS.critical, SEVERITY_COLORS.high, SEVERITY_COLORS.medium, SEVERITY_COLORS.low],
    }],
  };

  return (
    <Box sx={{ height: 200 }}>
      <Doughnut
        data={data}
        options={{
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { position: 'right', labels: { boxWidth: 12 } },
          },
        }}
      />
    </Box>
  );
};

// Root cause bar chart
const RootCauseChart: React.FC<{ data: RootCauseAnalysis[] }> = ({ data }) => {
  const chartData = {
    labels: data.map(d => d.root_cause.replace('_', ' ')),
    datasets: [{
      label: 'Count',
      data: data.map(d => d.count),
      backgroundColor: 'rgba(25, 118, 210, 0.6)',
      borderColor: 'rgb(25, 118, 210)',
      borderWidth: 1,
    }],
  };

  return (
    <Box sx={{ height: 200 }}>
      <Bar
        data={chartData}
        options={{
          responsive: true,
          maintainAspectRatio: false,
          indexAxis: 'y',
          plugins: { legend: { display: false } },
          scales: {
            x: { beginAtZero: true },
          },
        }}
      />
    </Box>
  );
};

// Trend line chart
const TrendChart: React.FC<{ data: QualityTrendData }> = ({ data }) => {
  const chartData = {
    labels: data.trends.map(t => new Date(t.date).toLocaleDateString()),
    datasets: [
      {
        label: 'Total Defects',
        data: data.trends.map(t => t.total_defects),
        borderColor: 'rgb(244, 67, 54)',
        backgroundColor: 'rgba(244, 67, 54, 0.1)',
        fill: true,
        tension: 0.3,
      },
      {
        label: 'Resolved',
        data: data.trends.map(t => t.resolved_defects),
        borderColor: 'rgb(76, 175, 80)',
        backgroundColor: 'rgba(76, 175, 80, 0.1)',
        fill: true,
        tension: 0.3,
      },
    ],
  };

  return (
    <Box sx={{ height: 250 }}>
      <Line
        data={chartData}
        options={{
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { position: 'top' } },
          scales: {
            y: { beginAtZero: true },
          },
        }}
      />
    </Box>
  );
};

// Recent defects list
const RecentDefectsList: React.FC<{ defects: EscapedDefect[] }> = ({ defects }) => (
  <Stack spacing={1}>
    {defects.length === 0 ? (
      <Alert severity="info">No escaped defects recorded yet.</Alert>
    ) : (
      defects.slice(0, 5).map((defect) => (
        <Paper key={defect.id} variant="outlined" sx={{ p: 1.5 }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center">
            <Box flex={1}>
              <Stack direction="row" spacing={1} alignItems="center">
                <Chip
                  label={defect.severity}
                  size="small"
                  sx={{ bgcolor: SEVERITY_COLORS[defect.severity], color: 'white', fontSize: '0.7rem' }}
                />
                <Typography variant="body2" noWrap sx={{ maxWidth: 300 }}>
                  {defect.title}
                </Typography>
              </Stack>
              <Typography variant="caption" color="text.secondary">
                {defect.external_id && `${defect.external_id} • `}
                {new Date(defect.detected_at).toLocaleDateString()}
              </Typography>
            </Box>
            <Chip
              label={defect.status}
              size="small"
              variant="outlined"
              color={defect.status === 'resolved' || defect.status === 'closed' ? 'success' : 'default'}
            />
          </Stack>
        </Paper>
      ))
    )}
  </Stack>
);

// Component analysis table
const ComponentTable: React.FC<{ data: ComponentAnalysis[] }> = ({ data }) => (
  <Stack spacing={1}>
    {data.length === 0 ? (
      <Typography color="text.secondary" variant="body2">No component data</Typography>
    ) : (
      data.slice(0, 5).map((comp) => (
        <Box key={comp.component} sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Typography variant="body2" sx={{ flex: 1 }}>{comp.component}</Typography>
          <Stack direction="row" spacing={1} alignItems="center">
            <Chip label={`${comp.defect_count}`} size="small" color="primary" variant="outlined" />
            {comp.critical_count > 0 && (
              <Chip label={`${comp.critical_count} critical`} size="small" color="error" />
            )}
          </Stack>
        </Box>
      ))
    )}
  </Stack>
);

// Add Defect Dialog
const AddDefectDialog: React.FC<{
  open: boolean;
  onClose: () => void;
  projectId: number;
  sprintId?: number;
  onSave: (defect: EscapedDefectCreate) => Promise<void>;
}> = ({ open, onClose, projectId, sprintId, onSave }) => {
  const [formData, setFormData] = useState<Partial<EscapedDefectCreate>>({
    project_id: projectId,
    sprint_id: sprintId,
    title: '',
    severity: 'medium',
    status: 'open',
    detected_at: new Date().toISOString().split('T')[0],
    environment: 'production',
  });
  const [saving, setSaving] = useState(false);

  const handleSeverityChange = (event: SelectChangeEvent) => {
    const value = event.target.value;
    if (isSeverityLevel(value)) {
      setFormData({ ...formData, severity: value });
    }
  };

  const handleStatusChange = (event: SelectChangeEvent) => {
    const value = event.target.value;
    if (isDefectStatus(value)) {
      setFormData({ ...formData, status: value });
    }
  };

  const handleRootCauseChange = (event: SelectChangeEvent) => {
    const value = event.target.value;
    if (isRootCause(value)) {
      setFormData({ ...formData, root_cause: value });
    }
  };

  const handleSave = async () => {
    if (!formData.title) return;
    setSaving(true);
    try {
      const detectedAt = formData.detected_at
        ? new Date(formData.detected_at).toISOString()
        : new Date().toISOString();
      const payload: EscapedDefectCreate = {
        project_id: projectId,
        sprint_id: formData.sprint_id ?? sprintId,
        title: formData.title,
        description: formData.description,
        external_id: formData.external_id,
        severity: formData.severity,
        priority: formData.priority,
        environment: formData.environment,
        root_cause: formData.root_cause,
        affected_component: formData.affected_component,
        detected_at: detectedAt,
        status: formData.status,
      };
      await onSave(payload);
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Report Escaped Defect</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField
            label="Title"
            value={formData.title}
            onChange={(e) => setFormData({ ...formData, title: e.target.value })}
            fullWidth
            required
          />
          <TextField
            label="External ID (e.g., JIRA-123)"
            value={formData.external_id || ''}
            onChange={(e) => setFormData({ ...formData, external_id: e.target.value })}
            fullWidth
          />
          <TextField
            label="Description"
            value={formData.description || ''}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            multiline
            rows={2}
            fullWidth
          />
          <Grid container spacing={2}>
            <Grid item xs={6}>
              <FormControl fullWidth>
                <InputLabel>Severity</InputLabel>
                <Select
                  value={formData.severity || 'medium'}
                  label="Severity"
                  onChange={handleSeverityChange}
                >
                  {SEVERITY_OPTIONS.map((s) => (
                    <MenuItem key={s} value={s}>{s}</MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={6}>
              <FormControl fullWidth>
                <InputLabel>Status</InputLabel>
                <Select
                  value={formData.status || 'open'}
                  label="Status"
                  onChange={handleStatusChange}
                >
                  {STATUS_OPTIONS.map((s) => (
                    <MenuItem key={s} value={s}>{s}</MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
          </Grid>
          <Grid container spacing={2}>
            <Grid item xs={6}>
              <TextField
                label="Detected Date"
                type="date"
                value={formData.detected_at?.split('T')[0] || ''}
                onChange={(e) => setFormData({ ...formData, detected_at: e.target.value })}
                InputLabelProps={{ shrink: true }}
                fullWidth
              />
            </Grid>
            <Grid item xs={6}>
              <FormControl fullWidth>
                <InputLabel>Root Cause</InputLabel>
                <Select
                  value={formData.root_cause || ''}
                  label="Root Cause"
                  onChange={handleRootCauseChange}
                >
                  <MenuItem value="">Unknown</MenuItem>
                  {ROOT_CAUSE_OPTIONS.map((rc) => (
                    <MenuItem key={rc} value={rc}>{rc.replace('_', ' ')}</MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
          </Grid>
          <TextField
            label="Affected Component"
            value={formData.affected_component || ''}
            onChange={(e) => setFormData({ ...formData, affected_component: e.target.value })}
            fullWidth
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={handleSave} disabled={saving || !formData.title}>
          {saving ? 'Saving...' : 'Save Defect'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

// Main Dashboard Component
const QualityDashboardComponent: React.FC<QualityDashboardProps> = ({
  projectId,
  sprintId,
  onDefectAdded,
}) => {
  const [data, setData] = useState<QualityDashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const dashboard = await getQualityDashboard(projectId, sprintId);
      setData(dashboard);
    } catch (err) {
      console.error('Failed to load quality dashboard:', err);
      setError('Failed to load quality metrics');
    } finally {
      setLoading(false);
    }
  }, [projectId, sprintId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleAddDefect = async (defect: EscapedDefectCreate) => {
    await createEscapedDefect(defect);
    loadData();
    onDefectAdded?.();
  };

  if (loading) {
    return (
      <Box>
        <Stack spacing={2}>
          <Skeleton variant="rectangular" height={100} />
          <Grid container spacing={2}>
            <Grid item xs={6}><Skeleton variant="rectangular" height={200} /></Grid>
            <Grid item xs={6}><Skeleton variant="rectangular" height={200} /></Grid>
          </Grid>
        </Stack>
      </Box>
    );
  }

  if (!data) {
    return (
      <Alert severity="info">
        No quality data available. Start tracking escaped defects to see metrics.
      </Alert>
    );
  }

  const { summary, recent_defects, root_cause_breakdown, component_analysis, trend_data } = data;

  return (
    <Box>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Header */}
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 3 }}>
        <Typography variant="h6">Quality Metrics</Typography>
        <Stack direction="row" spacing={1}>
          <Button startIcon={<RefreshIcon />} onClick={loadData} size="small">
            Refresh
          </Button>
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setDialogOpen(true)}>
            Report Defect
          </Button>
        </Stack>
      </Stack>

      {/* Key Metrics Row */}
      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="Escaped Defects"
            value={summary.total_escaped_defects}
            subtitle={`${summary.open_defects} open`}
            icon={<BugIcon fontSize="large" />}
            color={summary.critical_count > 0 ? 'error.main' : 'warning.main'}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="MTTR"
            value={summary.mttr_hours?.toFixed(1)}
            subtitle="Hours to resolve"
            icon={<TimerIcon fontSize="large" />}
            color="info.main"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="Defect Density"
            value={summary.defect_density?.toFixed(2)}
            subtitle="Defects / KLOC"
            icon={<SpeedIcon fontSize="large" />}
            color={summary.defect_density && summary.defect_density < 5 ? 'success.main' : 'warning.main'}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="Escape Rate"
            value={summary.escape_rate ? `${summary.escape_rate.toFixed(1)}%` : undefined}
            subtitle="Defects reaching prod"
            icon={<WarningIcon fontSize="large" />}
            color={summary.escape_rate && summary.escape_rate < 10 ? 'success.main' : 'error.main'}
            trend={summary.trend_direction === 'improving' ? 'down' : summary.trend_direction === 'declining' ? 'up' : 'stable'}
            trendLabel={summary.trend_direction}
          />
        </Grid>
      </Grid>

      {/* Main Content Grid */}
      <Grid container spacing={3}>
        {/* DRE Gauge */}
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 2, height: '100%' }}>
            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
              Defect Removal Efficiency
            </Typography>
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
              <DREGauge value={summary.defect_removal_efficiency} />
            </Box>
          </Paper>
        </Grid>

        {/* Severity Breakdown */}
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 2, height: '100%' }}>
            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
              Severity Distribution
            </Typography>
            <SeverityChart summary={summary} />
          </Paper>
        </Grid>

        {/* Root Cause Analysis */}
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 2, height: '100%' }}>
            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
              Root Cause Analysis
            </Typography>
            {root_cause_breakdown.length > 0 ? (
              <RootCauseChart data={root_cause_breakdown} />
            ) : (
              <Typography color="text.secondary" variant="body2" sx={{ textAlign: 'center', py: 4 }}>
                No root cause data
              </Typography>
            )}
          </Paper>
        </Grid>

        {/* Trend Chart */}
        <Grid item xs={12} md={8}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
              Defect Trend (Last {trend_data.period_days} Days)
            </Typography>
            {trend_data.trends.length > 0 ? (
              <TrendChart data={trend_data} />
            ) : (
              <Typography color="text.secondary" variant="body2" sx={{ textAlign: 'center', py: 4 }}>
                No trend data available
              </Typography>
            )}
          </Paper>
        </Grid>

        {/* Component Analysis */}
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 2, height: '100%' }}>
            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
              By Component
            </Typography>
            <ComponentTable data={component_analysis} />
          </Paper>
        </Grid>

        {/* Recent Defects */}
        <Grid item xs={12}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
              Recent Escaped Defects
            </Typography>
            <RecentDefectsList defects={recent_defects} />
          </Paper>
        </Grid>
      </Grid>

      {/* Add Defect Dialog */}
      <AddDefectDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        projectId={projectId}
        sprintId={sprintId}
        onSave={handleAddDefect}
      />
    </Box>
  );
};

export default QualityDashboardComponent;
