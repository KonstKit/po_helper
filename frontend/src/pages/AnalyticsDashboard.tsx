import React, { useEffect, useState, useCallback } from 'react';
import {
  Box,
  Card,
  CardContent,
  Grid,
  Typography,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  LinearProgress,
  Chip,
  Button,
  Alert,
} from '@mui/material';
import {
  CheckCircle as CheckCircleIcon,
  Cancel as CancelIcon,
  TrendingUp as TrendingUpIcon,
  Timer as TimerIcon,
  People as PeopleIcon,
} from '@mui/icons-material';
import { analytics, OnboardingMetrics, TimeToValueMetrics, FeatureAdoptionMetrics } from '../services/analytics';

const AnalyticsDashboard: React.FC = () => {
  const [onboardingMetrics, setOnboardingMetrics] = useState<OnboardingMetrics | null>(null);
  const [timeToValueMetrics, setTimeToValueMetrics] = useState<TimeToValueMetrics | null>(null);
  const [featureAdoptionMetrics, setFeatureAdoptionMetrics] = useState<FeatureAdoptionMetrics | null>(null);
  const [timeToFirstValue, setTimeToFirstValue] = useState<number | null>(null);
  const [sessionDuration, setSessionDuration] = useState<number>(0);

  const loadMetrics = useCallback(() => {
    setOnboardingMetrics(analytics.getOnboardingMetrics());
    setTimeToValueMetrics(analytics.getTimeToValueMetrics());
    setFeatureAdoptionMetrics(analytics.getFeatureAdoptionMetrics());
    setTimeToFirstValue(analytics.getTimeToFirstValue());
    setSessionDuration(analytics.getSessionDuration());
  }, []);

  useEffect(() => {
    const timeoutId = setTimeout(() => loadMetrics(), 0);

    // Refresh session duration every 30 seconds
    const interval = setInterval(() => {
      setSessionDuration(analytics.getSessionDuration());
    }, 30000);

    return () => {
      clearTimeout(timeoutId);
      clearInterval(interval);
    };
  }, [loadMetrics]);

  const formatDuration = (minutes: number | null): string => {
    if (minutes === null || minutes === 0) return 'N/A';
    if (minutes < 60) return `${minutes}m`;
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return `${hours}h ${mins}m`;
  };

  const formatTimestamp = (timestamp: number | undefined): string => {
    if (!timestamp) return 'Not tracked';
    return new Date(timestamp).toLocaleString();
  };

  const exportData = () => {
    const data = analytics.exportData();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `analytics_${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const clearLocalCache = () => {
    if (
      window.confirm(
        'Clear local analytics cache? This affects only client-side widgets ' +
          'in this browser. Server-side telemetry and any unsent events ' +
          'queued for the backend are not affected.',
      )
    ) {
      // Use the UI-only cache reset, not the full clear() — clear() also
      // drops the backend transport queue, which would silently lose any
      // unsent telemetry and contradicts the button's stated contract.
      analytics.clearLocalUiCache();
      loadMetrics();
    }
  };

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4">Usage Analytics Dashboard</Typography>
        <Box display="flex" gap={1}>
          <Button variant="outlined" onClick={loadMetrics}>
            Refresh
          </Button>
          <Button variant="outlined" onClick={exportData}>
            Export Local Cache
          </Button>
          <Button variant="outlined" color="error" onClick={clearLocalCache}>
            Clear Local Cache
          </Button>
        </Box>
      </Box>

      <Alert severity="info" sx={{ mb: 3 }}>
        This dashboard tracks user behavior metrics to help improve the onboarding experience and feature adoption.
        Local cache is used for client-side widgets in this browser. Server-side usage telemetry is stored
        separately and follows the configured retention policy.
      </Alert>

      {/* KPI Summary */}
      <Grid container spacing={3} mb={3}>
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Box display="flex" alignItems="center" mb={1}>
                <CheckCircleIcon color="primary" sx={{ mr: 1 }} />
                <Typography variant="subtitle2" color="text.secondary">
                  Onboarding Status
                </Typography>
              </Box>
              <Typography variant="h4">
                {onboardingMetrics?.completed ? (
                  <Chip label="Completed" color="success" size="small" />
                ) : onboardingMetrics?.started ? (
                  <Chip label="In Progress" color="warning" size="small" />
                ) : (
                  <Chip label="Not Started" size="small" />
                )}
              </Typography>
              {onboardingMetrics?.started && (
                <Typography variant="body2" color="text.secondary" mt={1}>
                  {onboardingMetrics.stepsCompleted.length} / {onboardingMetrics.totalSteps} steps
                </Typography>
              )}
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Box display="flex" alignItems="center" mb={1}>
                <TimerIcon color="primary" sx={{ mr: 1 }} />
                <Typography variant="subtitle2" color="text.secondary">
                  Time to First Value
                </Typography>
              </Box>
              <Typography variant="h4">
                {formatDuration(timeToFirstValue)}
              </Typography>
              <Typography variant="body2" color="text.secondary" mt={1}>
                Setup → First Sync
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Box display="flex" alignItems="center" mb={1}>
                <TrendingUpIcon color="primary" sx={{ mr: 1 }} />
                <Typography variant="subtitle2" color="text.secondary">
                  Feature Adoption
                </Typography>
              </Box>
              <Typography variant="h4">
                {featureAdoptionMetrics
                  ? `${Math.round(featureAdoptionMetrics.adoptionRate * 100)}%`
                  : 'N/A'}
              </Typography>
              <Typography variant="body2" color="text.secondary" mt={1}>
                {featureAdoptionMetrics
                  ? `${Object.values(featureAdoptionMetrics.features).filter(f => f.visited).length} / ${Object.keys(featureAdoptionMetrics.features).length} features`
                  : '0 / 0 features'}
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Box display="flex" alignItems="center" mb={1}>
                <PeopleIcon color="primary" sx={{ mr: 1 }} />
                <Typography variant="subtitle2" color="text.secondary">
                  Session Duration
                </Typography>
              </Box>
              <Typography variant="h4">
                {formatDuration(sessionDuration)}
              </Typography>
              <Typography variant="body2" color="text.secondary" mt={1}>
                Current session
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Onboarding Progress */}
      {onboardingMetrics && (
        <Paper sx={{ p: 3, mb: 3 }}>
          <Typography variant="h6" gutterBottom>
            Onboarding Progress
          </Typography>
          <Box mb={2}>
            <Box display="flex" justifyContent="space-between" mb={1}>
              <Typography variant="body2">
                Completion Rate
              </Typography>
              <Typography variant="body2" fontWeight={600}>
                {Math.round((onboardingMetrics.stepsCompleted.length / onboardingMetrics.totalSteps) * 100)}%
              </Typography>
            </Box>
            <LinearProgress
              variant="determinate"
              value={(onboardingMetrics.stepsCompleted.length / onboardingMetrics.totalSteps) * 100}
              sx={{ height: 8, borderRadius: 4 }}
            />
          </Box>
          <Grid container spacing={2}>
            <Grid item xs={6}>
              <Typography variant="body2" color="text.secondary">
                Started: {formatTimestamp(onboardingMetrics.startedAt)}
              </Typography>
            </Grid>
            <Grid item xs={6}>
              <Typography variant="body2" color="text.secondary">
                Completed: {formatTimestamp(onboardingMetrics.completedAt)}
              </Typography>
            </Grid>
            <Grid item xs={6}>
              <Typography variant="body2" color="text.secondary">
                Current Step: {onboardingMetrics.currentStep !== undefined ? onboardingMetrics.currentStep + 1 : 'N/A'}
              </Typography>
            </Grid>
            <Grid item xs={6}>
              <Typography variant="body2" color="text.secondary">
                Skipped: {onboardingMetrics.skipped ? 'Yes' : 'No'}
              </Typography>
            </Grid>
          </Grid>
        </Paper>
      )}

      {/* Time to Value Milestones */}
      {timeToValueMetrics && (
        <Paper sx={{ p: 3, mb: 3 }}>
          <Typography variant="h6" gutterBottom>
            Time to Value Milestones
          </Typography>
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>Milestone</TableCell>
                  <TableCell>Timestamp</TableCell>
                  <TableCell align="right">Time from Start</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                <TableRow>
                  <TableCell>Account Created</TableCell>
                  <TableCell>{formatTimestamp(timeToValueMetrics.accountCreatedAt)}</TableCell>
                  <TableCell align="right">—</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>First Login</TableCell>
                  <TableCell>{formatTimestamp(timeToValueMetrics.firstLoginAt)}</TableCell>
                  <TableCell align="right">
                    {timeToValueMetrics.accountCreatedAt && timeToValueMetrics.firstLoginAt
                      ? formatDuration(Math.round((timeToValueMetrics.firstLoginAt - timeToValueMetrics.accountCreatedAt) / 60000))
                      : 'N/A'}
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>Jira Connected</TableCell>
                  <TableCell>{formatTimestamp(timeToValueMetrics.jiraConnectedAt)}</TableCell>
                  <TableCell align="right">
                    {timeToValueMetrics.accountCreatedAt && timeToValueMetrics.jiraConnectedAt
                      ? formatDuration(Math.round((timeToValueMetrics.jiraConnectedAt - timeToValueMetrics.accountCreatedAt) / 60000))
                      : 'N/A'}
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>First Sync</TableCell>
                  <TableCell>{formatTimestamp(timeToValueMetrics.firstSyncAt)}</TableCell>
                  <TableCell align="right">
                    {timeToValueMetrics.accountCreatedAt && timeToValueMetrics.firstSyncAt
                      ? formatDuration(Math.round((timeToValueMetrics.firstSyncAt - timeToValueMetrics.accountCreatedAt) / 60000))
                      : 'N/A'}
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>First Project Viewed</TableCell>
                  <TableCell>{formatTimestamp(timeToValueMetrics.firstProjectViewedAt)}</TableCell>
                  <TableCell align="right">
                    {timeToValueMetrics.accountCreatedAt && timeToValueMetrics.firstProjectViewedAt
                      ? formatDuration(Math.round((timeToValueMetrics.firstProjectViewedAt - timeToValueMetrics.accountCreatedAt) / 60000))
                      : 'N/A'}
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>First Task Viewed</TableCell>
                  <TableCell>{formatTimestamp(timeToValueMetrics.firstTaskViewedAt)}</TableCell>
                  <TableCell align="right">
                    {timeToValueMetrics.accountCreatedAt && timeToValueMetrics.firstTaskViewedAt
                      ? formatDuration(Math.round((timeToValueMetrics.firstTaskViewedAt - timeToValueMetrics.accountCreatedAt) / 60000))
                      : 'N/A'}
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>
      )}

      {/* Feature Adoption */}
      {featureAdoptionMetrics && (
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Feature Adoption
          </Typography>
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>Feature</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Last Visit</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {Object.entries(featureAdoptionMetrics.features).map(([key, value]) => (
                  <TableRow key={key}>
                    <TableCell sx={{ textTransform: 'capitalize' }}>
                      {key.replace(/([A-Z])/g, ' $1').trim()}
                    </TableCell>
                    <TableCell>
                      {value.visited ? (
                        <Chip
                          icon={<CheckCircleIcon />}
                          label="Visited"
                          color="success"
                          size="small"
                        />
                      ) : (
                        <Chip
                          icon={<CancelIcon />}
                          label="Not Visited"
                          size="small"
                        />
                      )}
                    </TableCell>
                    <TableCell>{formatTimestamp(value.lastVisit)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>
      )}
    </Box>
  );
};

export default AnalyticsDashboard;
