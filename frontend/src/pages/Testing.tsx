import React, { useEffect, useMemo, useState } from 'react';
import { Box, Grid, Paper, Typography, Chip, Button, FormControl, InputLabel, Select, MenuItem, ToggleButtonGroup, ToggleButton, Dialog, DialogTitle, DialogContent, DialogActions, Tabs, Tab } from '@mui/material';
import { DataGrid, GridColDef } from '@mui/x-data-grid';
import { Science as ScienceIcon, Assessment as AssessmentIcon } from '@mui/icons-material';
import type { SelectChangeEvent } from '@mui/material/Select';
import {
  getTestTrend,
  getCoverageTrend,
  getCoverageFiles,
  listTestRuns,
  listCoverageReports,
  listTestResults,
} from '../services/api';
import { useProjects } from '../services/api/hooks';
import type {
  Project,
  TestRun,
  TestResult,
  CoverageReportListItem,
  TestTrendPoint,
  CoverageTrendItem,
  LocalFlakyTest,
} from '../services/api';
import CircularProgressWithLabel from '../components/CircularProgressWithLabel';
import EmptyState from '../components/EmptyState';
import { Line } from 'react-chartjs-2';
import type { ChartData, ChartOptions } from 'chart.js';
import { TestAnalyticsDashboard } from '../components/testing';

interface TabPanelProps {
  children?: React.ReactNode;
  value: number;
  index: number;
}

function TabPanel({ children, value, index }: TabPanelProps) {
  return (
    <div role="tabpanel" hidden={value !== index}>
      {value === index && <Box sx={{ pt: 2 }}>{children}</Box>}
    </div>
  );
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const toRecord = (value: unknown): Record<string, unknown> => (isRecord(value) ? value : {});

const parseProjectId = (value: string): number | '' => {
  if (value === '') {
    return '';
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : '';
};

/** Coverage file info from getCoverageFiles API */
interface CoverageFile {
  file_path: string;
  line_coverage?: number;
  branch_coverage?: number;
  lines_covered?: number;
  lines_total?: number;
}

type TestProvider = 'all' | 'github' | 'gitlab' | 'generic';

const isTestProvider = (value: string): value is TestProvider =>
  value === 'all' || value === 'github' || value === 'gitlab' || value === 'generic';

const Testing: React.FC = () => {
  const [activeTab, setActiveTab] = useState(0);
  // projects come from the shared React Query cache (E1), not local state
  // only the user's explicit choice lives in state; the default is derived
  const [manualProjectId, setManualProjectId] = useState<number | ''>('');
  const [progress, setProgress] = useState<{ active: boolean; percent: number; step: string }>({ active: false, percent: 0, step: '' });
  const [runs, setRuns] = useState<TestRun[]>([]);
  const [results, setResults] = useState<TestResult[]>([]);
  const [durationTrend, setDurationTrend] = useState<Array<{ day: string; avg: number }>>([]);
  const [flaky, setFlaky] = useState<LocalFlakyTest[]>([]);
  const [coverageList, setCoverageList] = useState<CoverageReportListItem[]>([]);
  const [baseline, setBaseline] = useState<string>('');
  const [compare, setCompare] = useState<string>('');
  const [expandedCommit, setExpandedCommit] = useState<string>('');
  const [filesForCommit, setFilesForCommit] = useState<Record<string, CoverageFile[]>>({});
  const [provider, setProvider] = useState<TestProvider>('all');
  const [days, setDays] = useState<30|90>(30);
  const [testTrend, setTestTrend] = useState<TestTrendPoint[]>([]);
  const [coverageTrend, setCoverageTrend] = useState<CoverageTrendItem[]>([]);
  const [failedOpen, setFailedOpen] = useState(false);
  const [failedDetails, setFailedDetails] = useState<TestResult[]>([]);
  const lineChartOptions: ChartOptions<'line'> = useMemo(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: 'top' } },
    }),
    []
  );
  const handleBaselineChange = (event: SelectChangeEvent<string>) => {
    setBaseline(event.target.value);
  };
  const handleCompareChange = (event: SelectChangeEvent<string>) => {
    setCompare(event.target.value);
  };
  const handleTabChange = (_: React.SyntheticEvent, newValue: number) => {
    setActiveTab(newValue);
  };
  const handleProviderChange = (_: React.MouseEvent<HTMLElement>, value: string | null) => {
    if (value && isTestProvider(value)) {
      setProvider(value);
    }
  };

  const projectsQuery = useProjects(); // shared ['projects'] cache (E1)
  const projects: Project[] = useMemo(
    () => projectsQuery.data ?? [],
    [projectsQuery.data]
  );
  const projectId: number | '' =
    manualProjectId !== ''
      ? manualProjectId
      : projects.length
        ? projects[0].id
        : '';
  useEffect(() => {
    let cancelled = false; // stale-response guard (roadmap E2)
    (async () => {
    if (!projectId) return;
    setProgress({ active: true, percent: 5, step: 'Loading test runs...' });
    const runsResp = await listTestRuns({
      projectId: Number(projectId),
      provider: provider === 'all' ? undefined : provider,
    });
    if (cancelled) return;
    setRuns(runsResp.data);
    setProgress({ active: true, percent: 35, step: 'Loading coverage history...' });
    const covResp = await listCoverageReports({ projectId: Number(projectId) });
    setCoverageList(covResp.data);
    // default baseline/compare
    if (covResp.data.length >= 2) {
      setBaseline(covResp.data[1].commit_sha || '');
      setCompare(covResp.data[0].commit_sha || '');
    }
    setProgress({ active: true, percent: 55, step: 'Loading test trend...' });
    try {
      const tt = await getTestTrend({ projectId: Number(projectId), days });
      setTestTrend(tt.trend || []);
    } catch (err) {
      console.debug('Failed to load test trend', err);
    }
    setProgress({ active: true, percent: 75, step: 'Loading coverage trend...' });
    try {
      const ct = await getCoverageTrend({ projectId: Number(projectId), days });
      setCoverageTrend(ct.trend || []);
    } catch (err) {
      console.debug('Failed to load coverage trend', err);
    }
    // Pull recent test results for advanced analytics
    try {
      const resResp = await listTestResults({ projectId: Number(projectId), sinceDays: days, limit: 500 });
      const arr = resResp.data;
      setResults(arr);
      // Duration trend by day (avg)
      const buckets: Record<string, { sum: number; n: number }> = {};
      arr.forEach((r: TestResult) => {
        const d = r.created_at ? new Date(r.created_at) : null;
        if (!d) return;
        const day = new Date(d.getFullYear(), d.getMonth(), d.getDate()).toISOString().slice(0,10);
        const dur = Number(r.duration || 0) || 0;
        if (!buckets[day]) buckets[day] = { sum: 0, n: 0 };
        buckets[day].sum += dur;
        buckets[day].n += 1;
      });
      const trend = Object.entries(buckets).sort((a,b)=> a[0].localeCompare(b[0])).map(([day, v])=> ({ day, avg: v.n ? v.sum/v.n : 0 }));
      setDurationTrend(trend);
      // Flaky detection
      const tests: Record<string, { classname: string; name: string; runs: number; fails: number }> = {};
      arr.forEach((r: TestResult) => {
        const id = `${r.classname||''}::${r.name||''}`;
        if (!tests[id]) tests[id] = { classname: r.classname||'', name: r.name||'', runs: 0, fails: 0 };
        tests[id].runs += 1;
        const st = (r.status||'').toLowerCase();
        if (st === 'failed' || st === 'error') tests[id].fails += 1;
      });
      const fl = Object.entries(tests)
        .filter(([, t]) => t.runs >= 3)
        .map(([id, t]) => {
          const failRate = t.fails / t.runs;
          // Simple flaky score: high for mid-range fail rates (0.2..0.8)
          const volatility = Math.abs(0.5 - failRate);
          const score = Math.max(0, 1 - volatility*2); // 1 at 0.5, 0 at 0 or 1
          return { id, classname: t.classname, name: t.name, runs: t.runs, failRate, score };
        })
        .filter(t => t.score > 0.2)
        .sort((a,b)=> b.score - a.score)
        .slice(0, 20);
      setFlaky(fl);
    } catch (err) {
      if (!cancelled) console.warn('Failed to load test analytics', err);
    }
    if (!cancelled) setProgress({ active: false, percent: 100, step: 'Ready' });
  })(); 
    return () => { cancelled = true; };
  }, [projectId, provider, days]);

  const runColumns: GridColDef[] = [
    { field: 'provider', headerName: 'Provider', width: 110, valueGetter: (p)=> (p.row.provider || '').toUpperCase() },
    { field: 'commit_sha', headerName: 'Commit', width: 130, renderCell: (p)=> <code>{(p.value || '').slice(0,8)}</code> },
    { field: 'pr_number', headerName: 'PR', width: 80 },
    { field: 'total', headerName: 'Total', width: 90 },
    { field: 'failed', headerName: 'Failed', width: 90 },
    { field: 'error', headerName: 'Error', width: 90 },
    { field: 'skipped', headerName: 'Skipped', width: 100 },
    { field: 'created_at', headerName: 'Time', width: 180 },
    { field: 'actions', headerName: 'Actions', width: 150, sortable: false, renderCell: (p) => (
      <Button size="small" variant="outlined" onClick={async ()=> {
        setFailedOpen(true);
        try {
          if (!projectId) return;
          const rows = await listTestResults({
            projectId: Number(projectId),
            commitSha: p.row.commit_sha,
          });
          const errs = rows.data.filter((r: TestResult) => ['failed','error'].includes((r.status||'').toLowerCase()));
          setFailedDetails(errs);
        } catch {
          setFailedDetails([]);
        }
      }}>Failed Details</Button>
    )}
  ];

  const testTrendData = useMemo<ChartData<'line'>>(() => ({
    labels: testTrend.map((d) => d.day),
    datasets: [
      { label: 'Total', data: testTrend.map((d) => d.total), borderColor: 'rgba(75,192,192,0.9)', backgroundColor:'rgba(75,192,192,0.2)' },
      { label: 'Failed', data: testTrend.map((d) => d.failed), borderColor: 'rgba(255,99,132,0.9)', backgroundColor:'rgba(255,99,132,0.2)' },
    ]
  }), [testTrend]);

  const coverageTrendData = useMemo<ChartData<'line'>>(() => ({
    labels: coverageTrend.map((d) => d.day),
    datasets: [
      { label: 'Line %', data: coverageTrend.map((d) => Math.round((d.avg_line||0)*1000)/10), borderColor: 'rgba(54,162,235,0.9)', backgroundColor: 'rgba(54,162,235,0.2)' },
      { label: 'Branch %', data: coverageTrend.map((d) => Math.round((d.avg_branch||0)*1000)/10), borderColor: 'rgba(255,206,86,0.9)', backgroundColor: 'rgba(255,206,86,0.2)' },
    ]
  }), [coverageTrend]);

  const durationTrendData = useMemo<ChartData<'line'>>(() => ({
    labels: durationTrend.map(d=> d.day),
    datasets: [
      { label: 'Avg Test Duration (s)', data: durationTrend.map(d=> Math.round((d.avg||0)*100)/100), borderColor:'rgba(153,102,255,0.9)', backgroundColor:'rgba(153,102,255,0.2)' }
    ]
  }), [durationTrend]);

  const coverageDelta = useMemo(() => {
    if (!baseline || !compare) return {};
    const base = coverageList.find((c) => c.commit_sha === baseline);
    const comp = coverageList.find((c) => c.commit_sha === compare);
    if (!base || !comp) return {};
    return {
      line: (comp.line_coverage || 0) - (base.line_coverage || 0),
      branch: (comp.branch_coverage || 0) - (base.branch_coverage || 0),
    };
  }, [baseline, compare, coverageList]);

  const showEmptyState = !progress.active && runs.length === 0 && projectId;

  const handleProjectChange = (event: SelectChangeEvent<string>) => {
    setManualProjectId(parseProjectId(event.target.value));
  };

  const handleDaysChange = (event: SelectChangeEvent<string>) => {
    const parsed = Number(event.target.value);
    if (parsed === 30 || parsed === 90) {
      setDays(parsed);
    }
  };

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h4">Testing</Typography>
        <FormControl size="small" sx={{ minWidth: 200 }}>
          <InputLabel>Project</InputLabel>
          <Select<string>
            label="Project"
            value={projectId === '' ? '' : String(projectId)}
            onChange={handleProjectChange}
          >
            {projects.map((p)=> (<MenuItem key={p.id} value={String(p.id)}>{p.name}</MenuItem>))}
          </Select>
        </FormControl>
      </Box>

      <Paper sx={{ mb: 2 }}>
        <Tabs value={activeTab} onChange={handleTabChange} variant="fullWidth">
          <Tab icon={<ScienceIcon />} label="Test Runs & Coverage" iconPosition="start" />
          <Tab icon={<AssessmentIcon />} label="Analytics Dashboard" iconPosition="start" />
        </Tabs>
      </Paper>

      <TabPanel value={activeTab} index={0}>
        <Box display="flex" justifyContent="flex-end" gap={2} alignItems="center" mb={2}>
          <ToggleButtonGroup size="small" exclusive value={provider} onChange={handleProviderChange}>
            <ToggleButton value="all">All</ToggleButton>
            <ToggleButton value="github">GitHub</ToggleButton>
            <ToggleButton value="gitlab">GitLab</ToggleButton>
            <ToggleButton value="generic">Generic</ToggleButton>
          </ToggleButtonGroup>
          <FormControl size="small" sx={{ minWidth: 140 }}>
            <InputLabel>Range</InputLabel>
            <Select<string> label="Range" value={String(days)} onChange={handleDaysChange}>
              <MenuItem value="30">Last 30 days</MenuItem>
              <MenuItem value="90">Last 90 days</MenuItem>
            </Select>
          </FormControl>
        </Box>

      {progress.active && (
        <Paper sx={{ p: 2, mb: 2, display: 'flex', justifyContent: 'center' }}>
          <CircularProgressWithLabel value={progress.percent} label={progress.step} />
        </Paper>
      )}

      {showEmptyState && (
        <Box sx={{ my: 4 }}>
          <EmptyState
            icon={<ScienceIcon sx={{ fontSize: 80 }} />}
            title="Start Tracking Test Results"
            description="Upload JUnit XML reports or connect CI/CD pipeline to monitor test health automatically"
            primaryAction={{
              label: 'Upload Test Results',
              onClick: () => alert('Test upload functionality coming soon'),
            }}
            secondaryAction={{
              label: 'Configure CI/CD Webhook',
              onClick: () => window.location.href = '/settings',
            }}
            benefits={[
              'Track test trends over time',
              'Detect flaky tests automatically',
              'Monitor coverage changes',
              'Analyze test duration patterns',
            ]}
            setupSteps={[
              'Upload JUnit XML test reports manually, OR',
              'Configure CI/CD webhook in Settings for automatic import',
              'Test results will appear here with analytics',
            ]}
          />
        </Box>
      )}

      <Paper sx={{ p: 2, mb: 3 }}>
        <Typography variant="h6" gutterBottom>Latest Test Runs</Typography>
        <div style={{ height: 420, width: '100%' }}>
          <DataGrid
            rows={runs}
            getRowId={(r)=> `${r.provider}-${r.commit_sha || 'na'}-${r.pr_number || 0}`}
            columns={runColumns}
            pageSizeOptions={[10, 25, 50, 100]}
            initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
            disableRowSelectionOnClick
          />
        </div>
        <Box display="flex" gap={1} mt={1}>
          <Button size="small" variant="outlined" onClick={()=>{
            // Export test results (current 'results' state) as CSV
            const rows = results;
            const headers = ['provider','commit_sha','pr_number','suite','classname','name','status','duration','message','created_at'];
            const csv = [headers.join(',')].concat(rows.map((r) => {
              const row = toRecord(r);
              return headers.map(h => JSON.stringify(row[h] ?? '')).join(',');
            })).join('\n');
            const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a'); a.href = url; a.download = 'test_results.csv'; a.click(); URL.revokeObjectURL(url);
          }}>Export Results CSV</Button>
          <Button size="small" variant="outlined" disabled={!expandedCommit || !(filesForCommit[expandedCommit]?.length)} onClick={()=>{
            const files = filesForCommit[expandedCommit] || [];
            const headers = ['file_path','line_coverage','branch_coverage','lines_covered','lines_total'];
            const csv = [headers.join(',')].concat(files.map((f) => {
              const row = toRecord(f);
              return headers.map(h => JSON.stringify(row[h] ?? '')).join(',');
            })).join('\n');
            const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a'); a.href = url; a.download = `coverage_files_${expandedCommit.slice(0,8)}.csv`; a.click(); URL.revokeObjectURL(url);
          }}>Export Coverage CSV</Button>
        </Box>
      </Paper>

      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>Test Trend</Typography>
            <Box height={300}>
              <Line data={testTrendData} options={lineChartOptions} />
            </Box>
          </Paper>
        </Grid>
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>Coverage Trend</Typography>
            <Box height={300}>
              <Line data={coverageTrendData} options={lineChartOptions} />
            </Box>
          </Paper>
        </Grid>
      </Grid>

      <Grid container spacing={2} sx={{ mt: 1 }}>
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>Duration Trend</Typography>
            <Box height={300}>
              <Line data={durationTrendData} options={lineChartOptions} />
            </Box>
          </Paper>
        </Grid>
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>Flaky Tests (Top)</Typography>
            <div style={{ maxHeight: 300, overflow: 'auto' }}>
              {flaky.length === 0 ? (
                <Typography variant="body2" color="text.secondary">No flaky tests detected.</Typography>
              ) : (
                flaky.map((t)=> (
                  <Box key={t.id} sx={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid #eee', py: 0.5 }}>
                    <Typography variant="body2" sx={{ pr: 1, maxWidth: '70%' }}>{t.classname}::{t.name}</Typography>
                    <Box display="flex" gap={1}>
                      <Chip size="small" label={`runs: ${t.runs}`} />
                      <Chip size="small" color={t.failRate>0.5?'error':'warning'} label={`fail: ${(t.failRate*100).toFixed(0)}%`} />
                      <Chip size="small" color={t.score>0.6?'warning':'info'} label={`flaky: ${(t.score*100).toFixed(0)}%`} />
                    </Box>
                  </Box>
                ))
              )}
            </div>
          </Paper>
        </Grid>
      </Grid>

      <Grid container spacing={2} sx={{ mt: 1 }}>
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>Coverage by Commit</Typography>
            <Box display="flex" flexDirection="column" gap={1}>
              {coverageList.slice(0, 10).map((c) => (
                <Box key={`${c.provider}-${c.commit_sha}`}>
                  <Box display="flex" justifyContent="space-between">
                    <Typography variant="caption"><code>{(c.commit_sha || '').slice(0,8)}</code></Typography>
                    <Typography variant="caption">{new Date(c.created_at).toLocaleString()}</Typography>
                  </Box>
                  <Typography variant="caption">Line</Typography>
                  <Box display="flex" alignItems="center" gap={1}>
                    <Box sx={{ flex: 1, mr: 1 }}>
                      <div style={{ height: 6, background: '#eee', borderRadius: 4 }}>
                        <div style={{ height: 6, borderRadius: 4, width: `${Math.round((c.line_coverage || 0)*100)}%`, background: 'rgba(54,162,235,0.8)' }} />
                      </div>
                    </Box>
                    <Typography variant="caption">{Math.round((c.line_coverage||0)*1000)/10}%</Typography>
                  </Box>
                  <Typography variant="caption">Branch</Typography>
                  <Box display="flex" alignItems="center" gap={1}>
                    <Box sx={{ flex: 1, mr: 1 }}>
                      <div style={{ height: 6, background: '#eee', borderRadius: 4 }}>
                        <div style={{ height: 6, borderRadius: 4, width: `${Math.round((c.branch_coverage || 0)*100)}%`, background: 'rgba(255,206,86,0.8)' }} />
                      </div>
                    </Box>
                    <Typography variant="caption">{Math.round((c.branch_coverage||0)*1000)/10}%</Typography>
                  </Box>
                  <Box sx={{ mt: 0.5 }}>
                    <Button size="small" onClick={async()=>{
                      const key = c.commit_sha;
                      setExpandedCommit(expandedCommit === key ? '' : key);
                      if (!filesForCommit[key]) {
                        try {
                          const f = await getCoverageFiles(key);
                          setFilesForCommit((m) => ({ ...m, [key]: f.data || [] }));
                        } catch (err) {
                          console.debug('Failed to load coverage files', err);
                        }
                      }
                    }}>{expandedCommit === c.commit_sha ? 'Hide Files' : 'Show Files'}</Button>
                  </Box>
                  {expandedCommit === c.commit_sha && (
                    <Box sx={{ pl: 1 }}>
                      {(filesForCommit[c.commit_sha] || []).slice(0, 50).map((f) => (
                        <Box key={f.file_path} sx={{ mb: 0.5 }}>
                          <Typography variant="caption">{f.file_path}</Typography>
                          <Box display="flex" alignItems="center" gap={1}>
                            <Box sx={{ flex: 1, mr: 1 }}>
                              <div style={{ height: 6, background: '#eee', borderRadius: 4 }}>
                                <div style={{ height: 6, borderRadius: 4, width: `${Math.round((f.line_coverage || 0)*100)}%`, background: 'rgba(76,175,80,0.9)' }} />
                              </div>
                            </Box>
                            <Typography variant="caption">{Math.round((f.line_coverage||0)*1000)/10}%</Typography>
                          </Box>
                        </Box>
                      ))}
                    </Box>
                  )}
                </Box>
              ))}
            </Box>
          </Paper>
        </Grid>
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>Coverage Diff</Typography>
            <Box display="flex" gap={1} alignItems="center" mb={1}>
              <FormControl size="small" sx={{ minWidth: 140 }}>
                <InputLabel>Baseline</InputLabel>
                <Select label="Baseline" value={baseline} onChange={handleBaselineChange}>
                  {coverageList.slice(0,20).map((c) => (
                    <MenuItem key={c.commit_sha} value={c.commit_sha}>{(c.commit_sha||'').slice(0,8)}</MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl size="small" sx={{ minWidth: 140 }}>
                <InputLabel>Compare</InputLabel>
                <Select label="Compare" value={compare} onChange={handleCompareChange}>
                  {coverageList.slice(0,20).map((c) => (
                    <MenuItem key={c.commit_sha} value={c.commit_sha}>{(c.commit_sha||'').slice(0,8)}</MenuItem>
                  ))}
                </Select>
              </FormControl>
              <Typography variant="caption" color="text.secondary">Delta computed below</Typography>
            </Box>
            <Box>
              <Typography variant="body2">Line Coverage Delta: {Math.round(((coverageDelta.line||0)*1000))/10}%</Typography>
              <div style={{ height: 8, background: '#eee', borderRadius: 4 }}>
                <div style={{ height: 8, borderRadius: 4, width: `${Math.min(100, Math.abs((coverageDelta.line||0)*100))}%`, background: (coverageDelta.line||0) >= 0 ? 'rgba(76,175,80,0.9)' : 'rgba(244,67,54,0.9)' }} />
              </div>
              <Typography variant="body2" sx={{ mt: 1 }}>Branch Coverage Delta: {Math.round(((coverageDelta.branch||0)*1000))/10}%</Typography>
              <div style={{ height: 8, background: '#eee', borderRadius: 4 }}>
                <div style={{ height: 8, borderRadius: 4, width: `${Math.min(100, Math.abs((coverageDelta.branch||0)*100))}%`, background: (coverageDelta.branch||0) >= 0 ? 'rgba(76,175,80,0.9)' : 'rgba(244,67,54,0.9)' }} />
              </div>
              {(coverageDelta.line||0) < -0.05 || (coverageDelta.branch||0) < -0.05 ? (
                <Typography variant="caption" color="error" sx={{ mt: 1, display: 'block' }}>Alert: Significant coverage drop detected (&gt;5%).</Typography>
              ) : null}
            </Box>
          </Paper>
        </Grid>
      </Grid>
      </TabPanel>

      <TabPanel value={activeTab} index={1}>
        {typeof projectId === 'number' ? (
          <TestAnalyticsDashboard projectId={projectId} />
        ) : (
          <Typography variant="body2" color="text.secondary">
            Select a project to view test analytics.
          </Typography>
        )}
      </TabPanel>

      <Dialog open={failedOpen} onClose={()=> setFailedOpen(false)} fullWidth maxWidth="md">
        <DialogTitle>Failed Tests</DialogTitle>
        <DialogContent>
          {failedDetails.length === 0 ? (
            <Typography variant="body2">No failed tests found.</Typography>
          ) : (
            failedDetails.map((r, idx) => (
              <Box key={idx} sx={{ mb: 2, p: 1, border: '1px solid #eee', borderRadius: 1 }}>
                <Typography variant="subtitle2">{r.classname} — {r.name}</Typography>
                <Typography variant="caption" color="error">{r.message}</Typography>
                {r.raw && (
                  <pre style={{ whiteSpace: 'pre-wrap', background: '#fafafa', padding: 8, borderRadius: 4, overflowX: 'auto' }}>{JSON.stringify(r.raw, null, 2)}</pre>
                )}
              </Box>
            ))
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={()=> setFailedOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default Testing;
