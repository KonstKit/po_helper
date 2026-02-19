import React, { useEffect, useState, useCallback } from 'react';
import {
  Box,
  Paper,
  Typography,
  Grid,
  Card,
  CardContent,
  Chip,
  Button,
  LinearProgress,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  IconButton,
  Tooltip,
  CircularProgress,
  Alert,
  Tabs,
  Tab,
} from '@mui/material';
import {
  TrendingUp as TrendingUpIcon,
  TrendingDown as TrendingDownIcon,
  TrendingFlat as TrendingFlatIcon,
  Warning as WarningIcon,
  CheckCircle as CheckCircleIcon,
  BugReport as BugReportIcon,
  Speed as SpeedIcon,
  Refresh as RefreshIcon,
  FolderOpen as FolderIcon,
  Assignment as AssignmentIcon,
} from '@mui/icons-material';
import { Line, Doughnut } from 'react-chartjs-2';
import {
  getTestAnalyticsDashboard,
  detectFlakyTests,
  calculateComponentCoverage,
  updateFlakyTest,
  TestAnalyticsDashboard as TestAnalyticsDashboardType,
  FlakyTest,
  ComponentCoverage,
  FlakyTestStatus,
} from '../../services/api';

interface Props {
  projectId: number;
  sprintId?: number;
  coverageTarget?: number;
}

const MetricCard: React.FC<{
  title: string;
  value: string | number;
  subtitle?: string;
  icon: React.ReactNode;
  color: string;
  trend?: 'up' | 'down' | 'stable';
  trendValue?: string;
}> = ({ title, value, subtitle, icon, color, trend, trendValue }) => (
  <Card sx={{ height: '100%' }}>
    <CardContent>
      <Box display="flex" alignItems="center" gap={1} mb={1}>
        <Box sx={{ color }}>{icon}</Box>
        <Typography variant="body2" color="text.secondary">{title}</Typography>
      </Box>
      <Typography variant="h4" fontWeight="bold">{value}</Typography>
      {subtitle && <Typography variant="caption" color="text.secondary">{subtitle}</Typography>}
      {trend && (
        <Box display="flex" alignItems="center" gap={0.5} mt={1}>
          {trend === 'up' && <TrendingUpIcon color="success" fontSize="small" />}
          {trend === 'down' && <TrendingDownIcon color="error" fontSize="small" />}
          {trend === 'stable' && <TrendingFlatIcon color="action" fontSize="small" />}
          {trendValue && <Typography variant="caption">{trendValue}</Typography>}
        </Box>
      )}
    </CardContent>
  </Card>
);

const CoverageGauge: React.FC<{
  coverage: number;
  target: number;
  label: string;
}> = ({ coverage, target, label }) => {
  const percentage = Math.round(coverage * 100);
  const targetPercentage = Math.round(target * 100);
  const met = coverage >= target;

  return (
    <Box sx={{ textAlign: 'center' }}>
      <Box sx={{ position: 'relative', display: 'inline-flex' }}>
        <CircularProgress
          variant="determinate"
          value={percentage}
          size={120}
          thickness={8}
          sx={{ color: met ? 'success.main' : 'warning.main' }}
        />
        <CircularProgress
          variant="determinate"
          value={100}
          size={120}
          thickness={8}
          sx={{
            position: 'absolute',
            left: 0,
            color: 'grey.200',
            zIndex: -1,
          }}
        />
        <Box
          sx={{
            position: 'absolute',
            top: 0,
            left: 0,
            bottom: 0,
            right: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexDirection: 'column',
          }}
        >
          <Typography variant="h5" fontWeight="bold">{percentage}%</Typography>
          <Typography variant="caption" color="text.secondary">{label}</Typography>
        </Box>
      </Box>
      <Box mt={1}>
        <Chip
          size="small"
          icon={met ? <CheckCircleIcon /> : <WarningIcon />}
          label={met ? 'Target Met' : `Target: ${targetPercentage}%`}
          color={met ? 'success' : 'warning'}
        />
      </Box>
    </Box>
  );
};

const FlakyTestsPanel: React.FC<{
  tests: FlakyTest[];
  onStatusChange: (id: number, status: FlakyTestStatus) => void;
}> = ({ tests, onStatusChange }) => (
  <TableContainer>
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>Test Name</TableCell>
          <TableCell>Class</TableCell>
          <TableCell align="right">Flakiness</TableCell>
          <TableCell align="right">Runs</TableCell>
          <TableCell>Status</TableCell>
          <TableCell>Actions</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {tests.map((test) => (
          <TableRow key={test.id}>
            <TableCell>
              <Typography variant="body2" noWrap sx={{ maxWidth: 200 }}>
                {test.test_name}
              </Typography>
            </TableCell>
            <TableCell>
              <Typography variant="caption" color="text.secondary" noWrap sx={{ maxWidth: 150 }}>
                {test.classname || '-'}
              </Typography>
            </TableCell>
            <TableCell align="right">
              <Chip
                size="small"
                label={`${Math.round((test.flakiness_rate || 0) * 100)}%`}
                color={(test.flakiness_rate || 0) > 0.3 ? 'error' : 'warning'}
              />
            </TableCell>
            <TableCell align="right">{test.total_runs}</TableCell>
            <TableCell>
              <Chip
                size="small"
                label={test.status}
                color={
                  test.status === 'fixed' ? 'success' :
                  test.status === 'quarantined' ? 'warning' :
                  test.status === 'ignored' ? 'default' : 'error'
                }
              />
            </TableCell>
            <TableCell>
              <Box display="flex" gap={0.5}>
                <Tooltip title="Quarantine">
                  <IconButton
                    size="small"
                    onClick={() => onStatusChange(test.id, 'quarantined')}
                  >
                    <WarningIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
                <Tooltip title="Mark Fixed">
                  <IconButton
                    size="small"
                    color="success"
                    onClick={() => onStatusChange(test.id, 'fixed')}
                  >
                    <CheckCircleIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </Box>
            </TableCell>
          </TableRow>
        ))}
        {tests.length === 0 && (
          <TableRow>
            <TableCell colSpan={6} align="center">
              <Typography color="text.secondary">No flaky tests detected</Typography>
            </TableCell>
          </TableRow>
        )}
      </TableBody>
    </Table>
  </TableContainer>
);

const ComponentCoveragePanel: React.FC<{
  components: ComponentCoverage[];
  threshold: number;
}> = ({ components, threshold }) => (
  <TableContainer>
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>Component</TableCell>
          <TableCell align="right">Coverage</TableCell>
          <TableCell align="right">Files</TableCell>
          <TableCell align="right">Lines</TableCell>
          <TableCell>Risk</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {components.slice(0, 10).map((comp) => (
          <TableRow key={comp.id}>
            <TableCell>
              <Box display="flex" alignItems="center" gap={1}>
                <FolderIcon fontSize="small" color="action" />
                <Typography variant="body2" noWrap sx={{ maxWidth: 200 }}>
                  {comp.component_path}
                </Typography>
              </Box>
            </TableCell>
            <TableCell align="right">
              <Box display="flex" alignItems="center" gap={1} justifyContent="flex-end">
                <LinearProgress
                  variant="determinate"
                  value={Math.min((comp.line_coverage || 0) * 100, 100)}
                  sx={{ width: 60, height: 6, borderRadius: 3 }}
                  color={(comp.line_coverage || 0) >= threshold ? 'success' : 'warning'}
                />
                <Typography variant="body2">
                  {Math.round((comp.line_coverage || 0) * 100)}%
                </Typography>
              </Box>
            </TableCell>
            <TableCell align="right">{comp.total_files}</TableCell>
            <TableCell align="right">{comp.total_lines?.toLocaleString()}</TableCell>
            <TableCell>
              <Chip
                size="small"
                label={comp.priority || 'low'}
                color={
                  comp.priority === 'critical' ? 'error' :
                  comp.priority === 'high' ? 'warning' :
                  comp.priority === 'medium' ? 'info' : 'default'
                }
              />
            </TableCell>
          </TableRow>
        ))}
        {components.length === 0 && (
          <TableRow>
            <TableCell colSpan={5} align="center">
              <Typography color="text.secondary">No component data available</Typography>
            </TableCell>
          </TableRow>
        )}
      </TableBody>
    </Table>
  </TableContainer>
);

const TestAnalyticsDashboard: React.FC<Props> = ({ projectId, sprintId, coverageTarget = 0.8 }) => {
  const [data, setData] = useState<TestAnalyticsDashboardType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detecting, setDetecting] = useState(false);
  const [calculating, setCalculating] = useState(false);
  const [activeTab, setActiveTab] = useState(0);

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await getTestAnalyticsDashboard(projectId, { sprintId, coverageTarget });
      setData(result);
    } catch (err) {
      setError('Failed to load test analytics');
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [projectId, sprintId, coverageTarget]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleDetectFlaky = async () => {
    try {
      setDetecting(true);
      await detectFlakyTests(projectId, { days: 30, minRuns: 5 });
      await loadData();
    } catch (err) {
      console.error('Failed to detect flaky tests:', err);
    } finally {
      setDetecting(false);
    }
  };

  const handleCalculateComponents = async () => {
    try {
      setCalculating(true);
      await calculateComponentCoverage(projectId, { depth: 2 });
      await loadData();
    } catch (err) {
      console.error('Failed to calculate component coverage:', err);
    } finally {
      setCalculating(false);
    }
  };

  const handleFlakyStatusChange = async (id: number, status: FlakyTestStatus) => {
    try {
      await updateFlakyTest(id, { status });
      await loadData();
    } catch (err) {
      console.error('Failed to update flaky test:', err);
    }
  };

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight={400}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Alert severity="error" action={<Button onClick={loadData}>Retry</Button>}>
        {error}
      </Alert>
    );
  }

  if (!data) return null;

  const trendData = {
    labels: data.coverage_trend?.data_points?.map(p =>
      new Date(p.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    ) || [],
    datasets: [
      {
        label: 'Line Coverage',
        data: data.coverage_trend?.data_points?.map(p => (p.line_coverage || 0) * 100) || [],
        borderColor: 'rgb(75, 192, 192)',
        backgroundColor: 'rgba(75, 192, 192, 0.1)',
        fill: true,
        tension: 0.4,
      },
      {
        label: 'Test Pass Rate',
        data: data.coverage_trend?.data_points?.map(p => (p.test_pass_rate || 0) * 100) || [],
        borderColor: 'rgb(54, 162, 235)',
        backgroundColor: 'rgba(54, 162, 235, 0.1)',
        fill: true,
        tension: 0.4,
      },
    ],
  };

  const flakyCauseData = {
    labels: Object.keys(data.flaky_summary?.by_cause || {}),
    datasets: [{
      data: Object.values(data.flaky_summary?.by_cause || {}),
      backgroundColor: [
        '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF', '#FF9F40'
      ],
    }],
  };

  const testResultsData = {
    labels: ['Passing', 'Failing', 'Skipped'],
    datasets: [{
      data: [data.passing_tests, data.failing_tests, data.skipped_tests],
      backgroundColor: ['#4caf50', '#f44336', '#9e9e9e'],
    }],
  };

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h5">Test Analytics Dashboard</Typography>
        <Box display="flex" gap={1}>
          <Button
            variant="outlined"
            size="small"
            startIcon={<BugReportIcon />}
            onClick={handleDetectFlaky}
            disabled={detecting}
          >
            {detecting ? 'Detecting...' : 'Detect Flaky Tests'}
          </Button>
          <Button
            variant="outlined"
            size="small"
            startIcon={<FolderIcon />}
            onClick={handleCalculateComponents}
            disabled={calculating}
          >
            {calculating ? 'Calculating...' : 'Analyze Components'}
          </Button>
          <IconButton onClick={loadData} size="small">
            <RefreshIcon />
          </IconButton>
        </Box>
      </Box>

      {/* Coverage Summary Cards */}
      <Grid container spacing={2} mb={3}>
        <Grid item xs={12} md={3}>
          <CoverageGauge
            coverage={data.current_line_coverage || 0}
            target={data.coverage_target}
            label="Line Coverage"
          />
        </Grid>
        <Grid item xs={12} md={3}>
          <CoverageGauge
            coverage={data.current_branch_coverage || 0}
            target={data.coverage_target}
            label="Branch Coverage"
          />
        </Grid>
        <Grid item xs={12} md={3}>
          <MetricCard
            title="Test Pass Rate"
            value={`${Math.round(data.test_pass_rate * 100)}%`}
            subtitle={`${data.passing_tests}/${data.total_tests} tests`}
            icon={<CheckCircleIcon />}
            color={data.test_pass_rate > 0.95 ? '#4caf50' : '#ff9800'}
          />
        </Grid>
        <Grid item xs={12} md={3}>
          <MetricCard
            title="Active Flaky Tests"
            value={data.flaky_summary?.active_flaky_tests || 0}
            subtitle={`${data.flaky_summary?.quarantined || 0} quarantined`}
            icon={<BugReportIcon />}
            color={data.flaky_summary?.active_flaky_tests ? '#f44336' : '#4caf50'}
            trend={data.flaky_summary?.trend_direction === 'improving' ? 'down' :
                   data.flaky_summary?.trend_direction === 'degrading' ? 'up' : 'stable'}
          />
        </Grid>
      </Grid>

      {/* Delta Coverage Alert */}
      {data.latest_delta && (
        <Alert
          severity={data.latest_delta.line_coverage_delta >= 0 ? 'success' : 'warning'}
          sx={{ mb: 3 }}
          icon={data.latest_delta.line_coverage_delta >= 0 ? <TrendingUpIcon /> : <TrendingDownIcon />}
        >
          Latest PR Coverage Delta: {data.latest_delta.line_coverage_delta >= 0 ? '+' : ''}
          {Math.round(data.latest_delta.line_coverage_delta * 100)}% line coverage
          ({data.latest_delta.files_improved} files improved, {data.latest_delta.files_degraded} degraded)
        </Alert>
      )}

      {/* Tabs for Details */}
      <Paper sx={{ mb: 3 }}>
        <Tabs value={activeTab} onChange={(_, v) => setActiveTab(v)}>
          <Tab label="Coverage Trend" icon={<TrendingUpIcon />} iconPosition="start" />
          <Tab label="Flaky Tests" icon={<BugReportIcon />} iconPosition="start" />
          <Tab label="Component Coverage" icon={<FolderIcon />} iconPosition="start" />
          <Tab label="Test Results" icon={<AssignmentIcon />} iconPosition="start" />
        </Tabs>
      </Paper>

      {/* Coverage Trend Tab */}
      {activeTab === 0 && (
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>Coverage Trend (30 Days)</Typography>
          <Box sx={{ height: 300 }}>
            <Line
              data={trendData}
              options={{
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                  y: {
                    min: 0,
                    max: 100,
                    title: { display: true, text: 'Percentage (%)' },
                  },
                },
                plugins: {
                  legend: { position: 'top' },
                },
              }}
            />
          </Box>
          <Box display="flex" justifyContent="center" gap={4} mt={2}>
            <Box textAlign="center">
              <Typography variant="body2" color="text.secondary">Trend Direction</Typography>
              <Chip
                icon={
                  data.coverage_trend?.coverage_direction === 'improving' ? <TrendingUpIcon /> :
                  data.coverage_trend?.coverage_direction === 'degrading' ? <TrendingDownIcon /> :
                  <TrendingFlatIcon />
                }
                label={data.coverage_trend?.coverage_direction || 'stable'}
                color={
                  data.coverage_trend?.coverage_direction === 'improving' ? 'success' :
                  data.coverage_trend?.coverage_direction === 'degrading' ? 'error' : 'default'
                }
              />
            </Box>
            <Box textAlign="center">
              <Typography variant="body2" color="text.secondary">Net Change</Typography>
              <Typography variant="h6">
                {(data.coverage_trend?.coverage_change || 0) >= 0 ? '+' : ''}
                {Math.round((data.coverage_trend?.coverage_change || 0) * 100)}%
              </Typography>
            </Box>
          </Box>
        </Paper>
      )}

      {/* Flaky Tests Tab */}
      {activeTab === 1 && (
        <Grid container spacing={3}>
          <Grid item xs={12} md={8}>
            <Paper sx={{ p: 2 }}>
              <Typography variant="h6" gutterBottom>Active Flaky Tests</Typography>
              <FlakyTestsPanel
                tests={data.flaky_summary?.top_flaky_tests || []}
                onStatusChange={handleFlakyStatusChange}
              />
            </Paper>
          </Grid>
          <Grid item xs={12} md={4}>
            <Paper sx={{ p: 2 }}>
              <Typography variant="h6" gutterBottom>Flakiness by Cause</Typography>
              {Object.keys(data.flaky_summary?.by_cause || {}).length > 0 ? (
                <Box sx={{ height: 250 }}>
                  <Doughnut
                    data={flakyCauseData}
                    options={{
                      responsive: true,
                      maintainAspectRatio: false,
                      plugins: {
                        legend: { position: 'right' },
                      },
                    }}
                  />
                </Box>
              ) : (
                <Box display="flex" justifyContent="center" alignItems="center" height={200}>
                  <Typography color="text.secondary">No cause data</Typography>
                </Box>
              )}
            </Paper>
          </Grid>
        </Grid>
      )}

      {/* Component Coverage Tab */}
      {activeTab === 2 && (
        <Grid container spacing={3}>
          <Grid item xs={12} md={8}>
            <Paper sx={{ p: 2 }}>
              <Typography variant="h6" gutterBottom>Component Coverage (by Risk)</Typography>
              <ComponentCoveragePanel
                components={data.component_summary?.components || []}
                threshold={data.coverage_target}
              />
            </Paper>
          </Grid>
          <Grid item xs={12} md={4}>
            <Paper sx={{ p: 2 }}>
              <Typography variant="h6" gutterBottom>Coverage Summary</Typography>
              <Box display="flex" flexDirection="column" gap={2}>
                <Box display="flex" justifyContent="space-between">
                  <Typography>Total Components</Typography>
                  <Typography fontWeight="bold">{data.component_summary?.total_components || 0}</Typography>
                </Box>
                <Box display="flex" justifyContent="space-between">
                  <Typography color="success.main">Above Threshold</Typography>
                  <Typography fontWeight="bold" color="success.main">
                    {data.component_summary?.components_above_threshold || 0}
                  </Typography>
                </Box>
                <Box display="flex" justifyContent="space-between">
                  <Typography color="warning.main">Below Threshold</Typography>
                  <Typography fontWeight="bold" color="warning.main">
                    {data.component_summary?.components_below_threshold || 0}
                  </Typography>
                </Box>
                <Box display="flex" justifyContent="space-between">
                  <Typography>Average Coverage</Typography>
                  <Typography fontWeight="bold">
                    {Math.round((data.component_summary?.average_coverage || 0) * 100)}%
                  </Typography>
                </Box>
              </Box>
              {(data.component_summary?.critical_risk_components?.length || 0) > 0 && (
                <Alert severity="error" sx={{ mt: 2 }}>
                  {data.component_summary?.critical_risk_components?.length} critical risk components
                </Alert>
              )}
            </Paper>
          </Grid>
        </Grid>
      )}

      {/* Test Results Tab */}
      {activeTab === 3 && (
        <Grid container spacing={3}>
          <Grid item xs={12} md={6}>
            <Paper sx={{ p: 3 }}>
              <Typography variant="h6" gutterBottom>Test Results Distribution</Typography>
              <Box sx={{ height: 300, display: 'flex', justifyContent: 'center' }}>
                <Doughnut
                  data={testResultsData}
                  options={{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                      legend: { position: 'right' },
                    },
                  }}
                />
              </Box>
            </Paper>
          </Grid>
          <Grid item xs={12} md={6}>
            <Paper sx={{ p: 3 }}>
              <Typography variant="h6" gutterBottom>Test Metrics</Typography>
              <Grid container spacing={2}>
                <Grid item xs={6}>
                  <MetricCard
                    title="Total Tests"
                    value={data.total_tests}
                    icon={<AssignmentIcon />}
                    color="#2196f3"
                  />
                </Grid>
                <Grid item xs={6}>
                  <MetricCard
                    title="Passing"
                    value={data.passing_tests}
                    icon={<CheckCircleIcon />}
                    color="#4caf50"
                  />
                </Grid>
                <Grid item xs={6}>
                  <MetricCard
                    title="Failing"
                    value={data.failing_tests}
                    icon={<WarningIcon />}
                    color="#f44336"
                  />
                </Grid>
                <Grid item xs={6}>
                  <MetricCard
                    title="Skipped"
                    value={data.skipped_tests}
                    icon={<SpeedIcon />}
                    color="#9e9e9e"
                  />
                </Grid>
              </Grid>
            </Paper>
          </Grid>
        </Grid>
      )}
    </Box>
  );
};

export default TestAnalyticsDashboard;
