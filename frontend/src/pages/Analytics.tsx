import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Grid,
  Paper,
  Typography,
  Box,
  Card,
  CardContent,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  TableContainer,
  Table,
  TableHead,
  TableRow,
  TableCell,
  TableBody,
  Chip,
  LinearProgress,
  List,
  ListItem,
  ListItemAvatar,
  ListItemText,
  Avatar,
  Stack,
  Link,
  Button,
} from '@mui/material';
import { Line, Bar, Doughnut } from 'react-chartjs-2';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import GitHubIcon from '@mui/icons-material/GitHub';
import { listProjects, getVelocity, getBurndown, getRisks, getForecast, listTasks, getTestTrend, getCoverageTrend, getPRMetrics, getProjectValueMetrics, getDoraMetrics, getProjectTeamHealth, getGitHubProjectPulls, withRetry } from '../services/api';
import type { PRMetricsSummary, TeamHealthMetrics, GitHubPullRequest } from '../services/api';
import CircularProgressWithLabel from '../components/CircularProgressWithLabel';
import { AnalyticsFilters } from '../components/AnalyticsFilters';

const Analytics = () => {
  const [projects, setProjects] = useState<any[]>([]);
  const [projectId, setProjectId] = useState<number | 'all'>('all');
  const [prMetricsRange, setPRMetricsRange] = useState<'14d' | '30d' | '90d' | 'all'>('30d');
  const [velocity, setVelocity] = useState<any>(null);
  const [burndown, setBurndown] = useState<any>(null);
  const [risks, setRisks] = useState<any>(null);
  const [forecast, setForecast] = useState<any>(null);
  const [teamHealth, setTeamHealth] = useState<TeamHealthMetrics | null>(null);

  const [tasks, setTasks] = useState<any[]>([]);
  const [testTrend, setTestTrend] = useState<{ day: string; total: number; failed: number }[]>([]);
  const [valueMetrics, setValueMetrics] = useState<{ value_delivered: number; total_spent_hours: number; roi: number }|null>(null);
  const [githubPulls, setGithubPulls] = useState<GitHubPullRequest[]>([]);
  const [githubPullLoading, setGithubPullLoading] = useState(false);
  const [githubPullError, setGithubPullError] = useState<string | null>(null);
  const [coverageTrend, setCoverageTrend] = useState<{ day: string; avg_line: number; avg_branch: number; count: number }[]>([]);
  const [prMetrics, setPRMetrics] = useState<PRMetricsSummary | null>(null);
  const [prMetricsLoading, setPRMetricsLoading] = useState(false);
  const [timeRange, setTimeRange] = useState<'1month'|'3months'|'6months'|'1year'>('6months');
  const [progress, setProgress] = useState<{ loading: boolean; percent: number; step: string }>({ loading: false, percent: 0, step: '' });

  useEffect(() => { (async () => {
    try {
      const ps = await withRetry(
        () => listProjects({ timeout: 10000 }), // Reduced from 45s to 10s
        { retries: 2, baseDelayMs: 300, maxDelayMs: 2000 }
      );
      setProjects(ps);
      if (ps.length) setProjectId(ps[0].id);
    } catch (error) {
      console.error('Failed to load projects:', error);
      setProjects([]); // Set empty to prevent UI issues
    }
  })(); }, []);
  useEffect(() => { (async () => {
    if (typeof projectId === 'number') {
      setPRMetrics(null);
      setTeamHealth(null);

      const steps: Array<{label: string; run: () => Promise<void>}> = [
        { label: 'Loading velocity...', run: async () => { setVelocity(await getVelocity(projectId)); } },
        { label: 'Loading burndown...', run: async () => { setBurndown(await getBurndown(projectId)); } },
        { label: 'Loading risks...', run: async () => { setRisks(await getRisks(projectId)); } },
        { label: 'Loading value metrics...', run: async () => { setValueMetrics(await getProjectValueMetrics(projectId)); } },
        { label: 'Assessing team health...', run: async () => { setTeamHealth(await withRetry(() => getProjectTeamHealth(projectId), { retries: 1, baseDelayMs: 400, maxDelayMs: 3000 })); } },
        { label: 'Forecasting completion...', run: async () => { setForecast(await getForecast(projectId)); } },
        { label: 'Loading tasks...', run: async () => {
          try {
            const taskList = await withRetry(
              () => listTasks({ project_id: projectId }, { timeout: 15000 }), // Reduced from 60s to 15s
              { retries: 2, baseDelayMs: 500, maxDelayMs: 4000 }
            );
            setTasks(taskList);
          } catch (error) {
            console.error('Failed to load tasks:', error);
            setTasks([]); // Set empty array on error
          }
        } },
        { label: 'Fetching test trend...', run: async () => { const tt = await getTestTrend(projectId, 30); setTestTrend(tt?.trend || []); } },
        { label: 'Fetching coverage trend...', run: async () => { const ct = await getCoverageTrend(projectId, 30); setCoverageTrend(ct?.trend || []); } },
        { label: 'Fetching GitHub pull requests...', run: async () => {
          setGithubPullLoading(true);
          try {
            const res = await getGitHubProjectPulls(projectId, { limit: 10 });
            setGithubPulls(res.pulls || []);
            setGithubPullError(null);
          } catch (error) {
            console.warn('Failed to load GitHub pull requests', error);
            setGithubPulls([]);
            setGithubPullError('Failed to load GitHub pull requests');
          } finally {
            setGithubPullLoading(false);
          }
        } },
      ];
      setProgress({ loading: true, percent: 0, step: 'Starting...' });
      for (let i = 0; i < steps.length; i++) {
        setProgress({ loading: true, percent: Math.round((i / steps.length) * 100), step: steps[i].label });
        try { await steps[i].run(); } catch {}
      }
      setProgress({ loading: false, percent: 100, step: 'Ready' });
    }
  })(); }, [projectId]);

  const prRangeDays = useMemo(() => {
    if (prMetricsRange === 'all') return undefined;
    const parsed = parseInt(prMetricsRange.replace('d', ''), 10);
    return Number.isFinite(parsed) ? parsed : undefined;
  }, [prMetricsRange]);

  const prRangeLabel = prMetricsRange === 'all' ? 'All time' : prMetricsRange;

  useEffect(() => {
    if (typeof projectId !== 'number') {
      setPRMetrics(null);
      setTeamHealth(null);

      setPRMetricsLoading(false);
      return;
    }
    let cancelled = false;
    const fetchMetrics = async () => {
      setPRMetricsLoading(true);
      try {
        const data = await getPRMetrics({ project_id: projectId, since_days: prRangeDays });
        if (!cancelled) {
          setPRMetrics(data);
        }
      } catch (err) {
        if (!cancelled) {
          console.error('Failed to load PR metrics', err);
        }
      } finally {
        if (!cancelled) {
          setPRMetricsLoading(false);
        }
      }
    };
    fetchMetrics();
    return () => { cancelled = true; };
  }, [projectId, prRangeDays]);

  const rangeStart = useMemo(() => {
    const now = new Date();
    const d = new Date(now);
    if (timeRange === '1month') d.setMonth(d.getMonth() - 1);
    if (timeRange === '3months') d.setMonth(d.getMonth() - 3);
    if (timeRange === '6months') d.setMonth(d.getMonth() - 6);
    if (timeRange === '1year') d.setFullYear(d.getFullYear() - 1);
    return d;
  }, [timeRange]);

  const filteredTasks = useMemo(() => {
    const start = rangeStart.getTime();
    return tasks.filter(t => {
      const dates = [t.updated_date, t.resolved_date, t.created_date]
        .filter(Boolean)
        .map((x:any)=> new Date(x).getTime());
      return dates.some((ts:number)=> ts >= start);
    });
  }, [tasks, rangeStart]);

  const velocityData = useMemo(() => {
    // Build weekly velocity from filtered tasks (done in range)
    const doneSet = new Set(['Done','Closed','Resolved']);
    const weeks: string[] = [];
    const buckets: Record<string, number> = {};
    const now = new Date();
    for (let i = 12; i >= 0; i--) {
      const d = new Date(now); d.setDate(d.getDate() - i*7);
      const y = d.getFullYear(); const soY = new Date(y,0,1);
      const w = Math.ceil((((+d - +soY)/86400000) + soY.getDay()+1)/7);
      const label = `${y}-W${w}`; weeks.push(label); buckets[label] = 0;
    }
    filteredTasks.forEach((t:any) => {
      if (!doneSet.has(t.status) || !t.updated_date) return;
      const d = new Date(t.updated_date);
      if (d < rangeStart) return;
      const y = d.getFullYear(); const soY = new Date(y,0,1);
      const w = Math.ceil((((+d - +soY)/86400000) + soY.getDay()+1)/7);
      const label = `${y}-W${w}`;
      if (label in buckets) buckets[label] += (t.estimate_hours || 0);
    });
    return { labels: weeks, datasets: [{ label: 'Velocity (h)', data: weeks.map(w=> Math.round((buckets[w]||0)*10)/10), borderColor:'rgb(75,192,192)', backgroundColor:'rgba(75,192,192,0.2)' }] };
  }, [filteredTasks, rangeStart]);

  const burndownData = useMemo(() => {
    if (!burndown || !burndown.ideal_burndown) return { labels: [], datasets: [] };
    const labels = burndown.ideal_burndown.map((p:any)=>`Day ${p.day}`);
    const ideal = burndown.ideal_burndown.map((p:any)=>p.ideal_remaining);
    const actual = burndown.actual_burndown?.map((p:any)=>p.remaining) || ideal;
    return { labels, datasets: [
      { label:'Ideal', data: ideal, borderColor:'rgba(255,99,132,0.8)', backgroundColor:'rgba(255,99,132,0.1)', borderDash:[5,5] },
      { label:'Actual', data: actual, borderColor:'rgba(54,162,235,0.8)', backgroundColor:'rgba(54,162,235,0.1)' },
    ]};
  }, [burndown]);

  const testTrendData = useMemo(() => {
    const labels = testTrend.map(d => d.day);
    return {
      labels,
      datasets: [
        { label: 'Total', data: testTrend.map(d=>d.total), borderColor:'rgba(75,192,192,0.9)', backgroundColor:'rgba(75,192,192,0.2)' },
        { label: 'Failed', data: testTrend.map(d=>d.failed), borderColor:'rgba(255,99,132,0.9)', backgroundColor:'rgba(255,99,132,0.2)' },
      ],
    };
  }, [testTrend]);

  const coverageTrendData = useMemo(() => {
    const labels = coverageTrend.map(d=>d.day);
    return {
      labels,
      datasets: [
        { label: 'Line Coverage', data: coverageTrend.map(d=> Math.round((d.avg_line||0)*1000)/10), borderColor:'rgba(54,162,235,0.9)', backgroundColor:'rgba(54,162,235,0.2)' },
        { label: 'Branch Coverage', data: coverageTrend.map(d=> Math.round((d.avg_branch||0)*1000)/10), borderColor:'rgba(255,206,86,0.9)', backgroundColor:'rgba(255,206,86,0.2)' },
      ],
    };
  }, [coverageTrend]);

  const teamCompletionPct = useMemo(() => teamHealth ? Math.round(teamHealth.completion_rate * 1000) / 10 : null, [teamHealth]);
  const avgCycleHours = useMemo(() => (teamHealth?.avg_cycle_time_hours != null ? Math.round(teamHealth.avg_cycle_time_hours * 10) / 10 : null), [teamHealth]);
  const medianCycleHours = useMemo(() => (teamHealth?.median_cycle_time_hours != null ? Math.round(teamHealth.median_cycle_time_hours * 10) / 10 : null), [teamHealth]);
  const estimateHours = useMemo(() => (teamHealth ? Math.round(teamHealth.estimate_hours * 10) / 10 : null), [teamHealth]);
  const spentHours = useMemo(() => (teamHealth ? Math.round(teamHealth.spent_hours * 10) / 10 : null), [teamHealth]);
  const avgTaskCompletionDays = useMemo(() => {
    const done = filteredTasks.filter(t => {
      if (!t.resolved_date) return false;
      const resolved = new Date(t.resolved_date).getTime();
      return resolved >= rangeStart.getTime();
    });
    if (!done.length) return null;
    const durations = done.map(t => {
      const resolved = new Date(t.resolved_date as string).getTime();
      const start = t.created_date || t.updated_date;
      const started = start ? new Date(start).getTime() : resolved;
      return (resolved - started) / (1000 * 3600 * 24);
    });
    const mean = durations.reduce((acc, value) => acc + value, 0) / durations.length;
    return Math.round(mean * 10) / 10;
  }, [filteredTasks, rangeStart]);
  const budgetEfficiencyPct = useMemo(() => {
    if (!filteredTasks.length) return null;
    const sumEst = filteredTasks.reduce((acc, t) => acc + (t.estimate_hours || 0), 0);
    const sumSpent = filteredTasks.reduce((acc, t) => acc + (t.spent_hours || 0), 0);
    if (!sumSpent) return 100;
    const efficiency = Math.max(0, Math.min(100, Math.round((sumEst / sumSpent) * 100)));
    return efficiency;
  }, [filteredTasks]);
  const teamPerformanceData = useMemo(() => {
    const byUser: Record<string, { completed: number; estimate: number }> = {};
    const done = new Set(['Done','Closed','Resolved']);
    filteredTasks.forEach(t => {
      const key = t.assignee_name || 'Unassigned';
      if (!byUser[key]) byUser[key] = { completed: 0, estimate: 0 };
      if (done.has(t.status)) byUser[key].completed++;
      byUser[key].estimate += (t.estimate_hours || 0);
    });
    const labels = Object.keys(byUser);
    return {
      labels,
      datasets: [
        { label: 'Tasks Completed', data: labels.map(l=>byUser[l].completed), backgroundColor: 'rgba(53,162,235,0.8)' },
        { label: 'Estimate (h)', data: labels.map(l=>Math.round(byUser[l].estimate)), backgroundColor: 'rgba(255,206,86,0.8)' },
      ],
    };
  }, [filteredTasks]);

  const riskDistribution = useMemo(() => {
    if (!risks || !risks.risks) return { labels: [], datasets: [] };
    const groups: Record<string, number> = {};
    risks.risks.forEach((r:any)=> { groups[r.severity] = (groups[r.severity]||0)+1; });
    const labels = Object.keys(groups);
    const data = labels.map(l=>groups[l]);
    return { labels, datasets: [{ data, backgroundColor: labels.map((l,i)=>['rgba(75,192,192,0.8)','rgba(255,206,86,0.8)','rgba(255,99,132,0.8)','rgba(156,39,176,0.8)'][i%4]) }] };
  }, [risks]);

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'top' as const,
      },
    },
  };

  const prHistogramData = useMemo(() => {
    if (!prMetrics?.histogram) return { labels: [], datasets: [] };
    const bins = prMetrics.histogram.bins || [];
    const cycle = prMetrics.histogram.cycle_counts || [];
    const lead = prMetrics.histogram.lead_counts || [];
    const pad = (arr: number[]) => bins.map((_, idx) => arr[idx] ?? 0);
    return {
      labels: bins,
      datasets: [
        {
          label: 'Cycle Time PRs',
          data: pad(cycle),
          backgroundColor: 'rgba(3, 169, 244, 0.6)',
          borderColor: 'rgba(3, 169, 244, 1)',
          borderWidth: 1,
        },
        {
          label: 'Lead Time PRs',
          data: pad(lead),
          backgroundColor: 'rgba(156, 39, 176, 0.6)',
          borderColor: 'rgba(156, 39, 176, 1)',
          borderWidth: 1,
        },
      ],
    };
  }, [prMetrics]);

  const prHistogramOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'top' as const,
      },
    },
    scales: {
      x: { stacked: false },
      y: { beginAtZero: true, ticks: { precision: 0 } },
    },
  };

  const prOverlayData = useMemo(() => {
    if (!prMetrics?.histogram) return { labels: [], datasets: [] };
    const bins = prMetrics.histogram.bins || [];
    const cycleCounts = (prMetrics.histogram.cycle_counts || []).map((n: number | undefined) => n || 0);
    const leadCounts = (prMetrics.histogram.lead_counts || []).map((n: number | undefined) => n || 0);
    const cycleTotal = cycleCounts.reduce((acc, val) => acc + val, 0);
    const leadTotal = leadCounts.reduce((acc, val) => acc + val, 0);
    const toPct = (arr: number[], total: number) => bins.map((_, idx) => {
      const value = arr[idx] ?? 0;
      if (!total) return 0;
      return Math.round(((value / total) * 100) * 10) / 10;
    });
    const smooth = (arr: number[]) => arr.map((val, idx, src) => {
      const window: number[] = [];
      if (idx > 0) window.push(src[idx - 1]);
      window.push(val);
      if (idx < src.length - 1) window.push(src[idx + 1]);
      const avg = window.reduce((sum, current) => sum + current, 0) / (window.length || 1);
      return Math.round(avg * 10) / 10;
    });
    const cyclePct = smooth(toPct(cycleCounts, cycleTotal));
    const leadPct = smooth(toPct(leadCounts, leadTotal));
    return {
      labels: bins,
      datasets: [
        {
          label: 'Cycle Time %',
          data: cyclePct,
          borderColor: 'rgba(3, 169, 244, 1)',
          backgroundColor: 'rgba(3, 169, 244, 0.15)',
          tension: 0.3,
          fill: false,
        },
        {
          label: 'Lead Time %',
          data: leadPct,
          borderColor: 'rgba(156, 39, 176, 1)',
          backgroundColor: 'rgba(156, 39, 176, 0.15)',
          tension: 0.3,
          fill: false,
        },
      ],
    };
  }, [prMetrics]);
  const prOverlayOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { position: 'top' as const },
      tooltip: { callbacks: { label: (ctx: any) => `${ctx.dataset.label}: ${ctx.parsed.y}%` } },
    },
    scales: {
      x: { stacked: false },
      y: { beginAtZero: true, max: 100, ticks: { callback: (value: number | string) => `${value}%` } },
    },
  };

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Analytics
      </Typography>

      {/* Filters with Progressive Disclosure */}
      <AnalyticsFilters
        projectId={projectId}
        onProjectChange={setProjectId}
        projects={projects}
        timeRange={timeRange}
        onTimeRangeChange={setTimeRange}
        prMetricsRange={prMetricsRange}
        onPRMetricsRangeChange={setPRMetricsRange}
      />

      <Grid container spacing={3}>
        {progress.loading && (
          <Grid item xs={12}>
            <Paper sx={{ p: 2, display: 'flex', justifyContent: 'center' }}>
              <CircularProgressWithLabel value={progress.percent} label={progress.step} />
            </Paper>
          </Grid>
        )}

        {/* Key Metrics (real) */}
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom>
                Average Velocity
              </Typography>
              <Typography variant="h4">{velocity?.average_velocity ?? 0}</Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom>
                Total Value Delivered
              </Typography>
              <Typography variant="h4">{valueMetrics ? Math.round((valueMetrics.value_delivered || 0) * 10) / 10 : 0}</Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom>
                Completion Rate
              </Typography>
              <Typography variant="h4">{teamCompletionPct != null ? `${teamCompletionPct}%` : "--"}</Typography>
              <Typography variant="caption" color="text.secondary">
                Done {teamHealth?.done ?? "--"} / {teamHealth?.total ?? "--"}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom>
                Avg Cycle Time
              </Typography>
              <Typography variant="h4">{avgCycleHours != null ? `${avgCycleHours}h` : "--"}</Typography>
              <Typography variant="caption" color="text.secondary">
                Median {medianCycleHours != null ? `${medianCycleHours}h` : "--"} | Samples {teamHealth?.cycle_samples ?? "--"}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom>
                Avg. Task Completion
              </Typography>
              <Typography variant="h4">{avgTaskCompletionDays != null ? `${avgTaskCompletionDays}d` : "--"}</Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom>
                Budget Efficiency
              </Typography>
              <Typography variant="h4">{budgetEfficiencyPct != null ? `${budgetEfficiencyPct}%` : "--"}</Typography>
            </CardContent>
          </Card>
        </Grid>

        {/* Velocity Chart */}
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom>
                Active Blockers
              </Typography>
              <Typography variant="h4">{teamHealth ? teamHealth.blockers : "--"}</Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom>
                Overdue Work
              </Typography>
              <Typography variant="h4">{teamHealth ? teamHealth.overdue : "--"}</Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom>
                In Progress
              </Typography>
              <Typography variant="h4">{teamHealth ? teamHealth.in_progress : "--"}</Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom>
                Backlog
              </Typography>
              <Typography variant="h4">{teamHealth ? teamHealth.backlog : "--"}</Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>Team Health Snapshot</Typography>
            <Typography variant="body2" color="text.secondary" gutterBottom>
              {teamHealth ? 'Insights based on current task data' : 'No team activity for this range'}
            </Typography>
            <Box display="grid" gridTemplateColumns={{ xs: '1fr 1fr', sm: '1fr auto' }} rowGap={1} columnGap={2}>
              <Typography variant="body2" color="text.secondary">Total</Typography>
              <Typography variant="body2" fontWeight={600} textAlign="right">{teamHealth ? teamHealth.total : "--"}</Typography>
              <Typography variant="body2" color="text.secondary">Done</Typography>
              <Typography variant="body2" textAlign="right">{teamHealth ? teamHealth.done : "--"}</Typography>
              <Typography variant="body2" color="text.secondary">In Progress</Typography>
              <Typography variant="body2" textAlign="right">{teamHealth ? teamHealth.in_progress : "--"}</Typography>
              <Typography variant="body2" color="text.secondary">Backlog</Typography>
              <Typography variant="body2" textAlign="right">{teamHealth ? teamHealth.backlog : "--"}</Typography>
              <Typography variant="body2" color="text.secondary">Blockers</Typography>
              <Typography variant="body2" textAlign="right">{teamHealth ? teamHealth.blockers : "--"}</Typography>
              <Typography variant="body2" color="text.secondary">Overdue</Typography>
              <Typography variant="body2" textAlign="right">{teamHealth ? teamHealth.overdue : "--"}</Typography>
              <Typography variant="body2" color="text.secondary">Estimate (h)</Typography>
              <Typography variant="body2" textAlign="right">{estimateHours != null ? estimateHours : "--"}</Typography>
              <Typography variant="body2" color="text.secondary">Spent (h)</Typography>
              <Typography variant="body2" textAlign="right">{spentHours != null ? spentHours : "--"}</Typography>
              <Typography variant="body2" color="text.secondary">Completion</Typography>
              <Typography variant="body2" textAlign="right">{teamCompletionPct != null ? `${teamCompletionPct}%` : "--"}</Typography>
              <Typography variant="body2" color="text.secondary">Cycle Time (avg / median)</Typography>
              <Typography variant="body2" textAlign="right">
                {avgCycleHours != null ? `${avgCycleHours}h` : "--"} / {medianCycleHours != null ? `${medianCycleHours}h` : "--"}
              </Typography>
            </Box>
          </Paper>
        </Grid>
        <Grid item xs={12} md={8}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>
              Team Velocity Trend
            </Typography>
            <Box height={300}>
              <Line data={velocityData} options={chartOptions} />
            </Box>
          </Paper>
        </Grid>

        {/* Risk Distribution */}
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>
              Risk Distribution
            </Typography>
            <Box height={300}>
              <Doughnut data={riskDistribution} options={chartOptions} />
            </Box>
          </Paper>
        </Grid>

        {/* Sprint Burndown */}
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>
              Current Sprint Burndown
            </Typography>
            <Box height={300}>
              <Line data={burndownData} options={chartOptions} />
            </Box>
          </Paper>
        </Grid>

        {/* Test Trend */}
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>
              Test Trend (Total vs Failed)
            </Typography>
            <Box height={300}>
              <Line data={testTrendData} options={chartOptions} />
            </Box>
          </Paper>
        </Grid>

        {/* Coverage Trend */}
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>
              Coverage Trend (% by day)
            </Typography>
            <Box height={300}>
              <Line data={coverageTrendData} options={chartOptions} />
            </Box>
          </Paper>
        </Grid>

        {/* PR Metrics Summary */}
        <Grid item xs={12}>
          <Paper sx={{ p: 2 }}>
            <Box display="flex" alignItems="center" justifyContent="space-between" mb={1}>
              <Typography variant="h6">Pull Request Metrics</Typography>
              <Box display="flex" alignItems="center" gap={1}>
                {prMetrics?.since_days ? (
                  <Chip size="small" color="info" label={`Range: Last ${prMetrics.since_days}d`} />
                ) : (
                  <Chip size="small" label={`Range: ${prRangeLabel}`} />
                )}
                {prMetrics?.cache_hit !== undefined && (
                  <Chip size="small" color={prMetrics.cache_hit ? 'default' : 'success'} label={prMetrics.cache_hit ? 'Cached' : 'Fresh'} />
                )}
              </Box>
            </Box>
            {prMetricsLoading && <LinearProgress sx={{ mb: 2 }} />}
            <Grid container spacing={2}>
              <Grid item xs={12} sm={6} md={3}>
                <Card><CardContent><Typography color="textSecondary">PRs Total</Typography><Typography variant="h5">{prMetrics?.total ?? 0}</Typography></CardContent></Card>
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <Card><CardContent><Typography color="textSecondary">Avg Cycle (h)</Typography><Typography variant="h5">{Math.round((prMetrics?.avg_cycle_time_hours || 0)*10)/10}</Typography></CardContent></Card>
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <Card><CardContent><Typography color="textSecondary">Avg Lead (h)</Typography><Typography variant="h5">{Math.round((prMetrics?.avg_lead_time_hours || 0)*10)/10}</Typography></CardContent></Card>
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <Card><CardContent><Typography color="textSecondary">Rework Rate (%)</Typography><Typography variant="h5">{Math.round(((prMetrics?.rework_rate || 0)*100)*10)/10}</Typography></CardContent></Card>
              </Grid>
            </Grid>
            {prMetrics && (
              <Box mt={2} display="flex" flexWrap="wrap" gap={2}>
                <Typography variant="body2" color="textSecondary">
                  Avg first review: {Math.round((prMetrics.avg_time_to_first_review_hours || 0)*10)/10}h ({prMetrics.first_review_samples || 0} samples)
                </Typography>
                <Typography variant="body2" color="textSecondary">
                  Samples analysed пїЅ cycle: {prMetrics.cycle_samples || 0}, lead: {prMetrics.lead_samples || 0}
                </Typography>
                <Typography variant="body2" color="textSecondary">
                  Throughput last {prMetrics.recent_throughput?.days ?? 14}d: {prMetrics.recent_throughput?.merged ?? 0} merged
                </Typography>
              </Box>
            )}
            {prMetrics && prHistogramData.labels.length > 0 && (
              <Box mt={3}>
                <Typography variant="subtitle1" gutterBottom>
                  Lead vs Cycle Time Distribution
                </Typography>
                <Box height={260}>
                  <Bar data={prHistogramData} options={prHistogramOptions} />
                </Box>
              </Box>
            )}
            {prMetrics && prOverlayData.labels.length > 0 && (
              <Box mt={3}>
                <Typography variant="subtitle1" gutterBottom>
                  Lead vs Cycle Time Overlay
                </Typography>
                <Box height={260}>
                  <Line data={prOverlayData} options={prOverlayOptions} />
                </Box>
              </Box>
            )}
            {prMetrics?.sample_prs && prMetrics.sample_prs.length > 0 && (
              <Box mt={3}>
                <Typography variant="subtitle1" gutterBottom>Recent Pull Requests</Typography>
                <TableContainer>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>#</TableCell>
                        <TableCell>Title</TableCell>
                        <TableCell>State</TableCell>
                        <TableCell align="right">Cycle (h)</TableCell>
                        <TableCell align="right">Lead (h)</TableCell>
                        <TableCell align="right">Rework</TableCell>
                        <TableCell align="right">Merged</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {prMetrics.sample_prs.map((item, idx) => (
                        <TableRow key={`${item.id || item.number || idx}-${idx}`}>
                          <TableCell>{item.number ?? item.id ?? 'пїЅ'}</TableCell>
                          <TableCell>{item.title || 'пїЅ'}</TableCell>
                          <TableCell>{item.state || 'пїЅ'}</TableCell>
                          <TableCell align="right">{item.cycle_time_hours ?? 'пїЅ'}</TableCell>
                          <TableCell align="right">{item.lead_time_hours ?? 'пїЅ'}</TableCell>
                          <TableCell align="right">{item.rework_count ?? 0}</TableCell>
                          <TableCell align="right">{item.merged_at ? new Date(item.merged_at).toLocaleDateString() : 'пїЅ'}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
                <Typography variant="caption" color="textSecondary">Showing {prMetrics.sample_prs.length} of {prMetrics.total} PRs</Typography>
              </Box>
            )}
          </Paper>
        </Grid>

        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom display="flex" alignItems="center" gap={1}>
              <GitHubIcon fontSize="small" /> GitHub Pull Requests
            </Typography>
            {githubPullLoading && <LinearProgress />}
            {!githubPullLoading && githubPullError && (
              <Typography color="error" variant="body2">{githubPullError}</Typography>
            )}
            {!githubPullLoading && !githubPullError && githubPulls.length === 0 && (
              <Typography variant="body2" color="text.secondary">No pull requests found.</Typography>
            )}
            {!githubPullLoading && githubPulls.length > 0 && (
              <List>
                {githubPulls.map((pr) => (
                  <ListItem key={pr.number} alignItems="flex-start" secondaryAction={pr.html_url ? (
                    <Link href={pr.html_url} target="_blank" rel="noopener" display="inline-flex" alignItems="center" gap={0.5}>
                      <OpenInNewIcon fontSize="small" />
                    </Link>
                  ) : null}>
                    <ListItemAvatar>
                      <Avatar src={pr.user?.avatar_url || undefined}>
                        {pr.user?.login ? pr.user.login.charAt(0).toUpperCase() : <GitHubIcon fontSize="small" />}
                      </Avatar>
                    </ListItemAvatar>
                    <ListItemText
                      primary={pr.title || `PR #${pr.number}`}
                      secondary={(
                        <Stack direction="row" spacing={2} flexWrap="wrap">
                          <Typography variant="caption">#{pr.number}</Typography>
                          {pr.user?.login && (<Typography variant="caption">{pr.user.login}</Typography>)}
                          {pr.state && (<Chip size="small" label={pr.state} color={pr.state === 'open' ? 'success' : pr.state === 'merged' ? 'primary' : 'default'} />)}
                          {pr.created_at && (<Typography variant="caption">Opened {new Date(pr.created_at).toLocaleDateString()}</Typography>)}
                        </Stack>
                      )}
                    />
                  </ListItem>
                ))}
              </List>
            )}
          </Paper>
        </Grid>

        {/* Team Performance */}
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>
              Team Performance
            </Typography>
            <Box height={300}>
              <Bar data={teamPerformanceData} options={chartOptions} />
            </Box>
          </Paper>
        </Grid>

        {/* Forecast (real) */}
        <Grid item xs={12}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>
              Project Completion Forecast
            </Typography>
            <Grid container spacing={2}>
              <Grid item xs={12} md={4}>
                <Box p={2} bgcolor="background.default" borderRadius={1}>
                  <Typography variant="subtitle2" color="textSecondary">
                    {projects.find(p=>p.id===projectId)?.name || ''}
                  </Typography>
                  <Typography variant="h6">{forecast?.estimated_completion_date || 'N/A'}</Typography>
                  <Typography variant="body2" color={forecast?.confidence_level==='high'?'success.main':'warning.main'}>
                    {forecast?.forecast_available ? `${forecast?.confidence_level || ''} confidence` : 'Insufficient data'}
                  </Typography>
                </Box>
              </Grid>
            </Grid>
          </Paper>
        </Grid>
      </Grid>
    </Box>
  );
};

export default Analytics;












