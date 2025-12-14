import React, { useEffect, useMemo, useState } from 'react';
import { Box, Grid, Paper, Typography, Card, CardContent, Chip, Button, FormControl, InputLabel, Select, MenuItem, ToggleButtonGroup, ToggleButton, Dialog, DialogTitle, DialogContent, DialogActions } from '@mui/material';
import { DataGrid, GridColDef } from '@mui/x-data-grid';
import { Science as ScienceIcon } from '@mui/icons-material';
import { listProjects, getTestTrend, getCoverageTrend, getCoverageFiles } from '../services/api';
import api, { } from '../services/api';
import CircularProgressWithLabel from '../components/CircularProgressWithLabel';
import EmptyState from '../components/EmptyState';
import { Line } from 'react-chartjs-2';

const Testing: React.FC = () => {
  const [projects, setProjects] = useState<any[]>([]);
  const [projectId, setProjectId] = useState<number | ''>('');
  const [progress, setProgress] = useState<{ active: boolean; percent: number; step: string }>({ active: false, percent: 0, step: '' });
  const [runs, setRuns] = useState<any[]>([]);
  const [results, setResults] = useState<any[]>([]);
  const [durationTrend, setDurationTrend] = useState<Array<{ day: string; avg: number }>>([]);
  const [flaky, setFlaky] = useState<Array<{ id: string; classname: string; name: string; runs: number; failRate: number; score: number }>>([]);
  const [coverageList, setCoverageList] = useState<any[]>([]);
  const [baseline, setBaseline] = useState<string>('');
  const [compare, setCompare] = useState<string>('');
  const [coverageDelta, setCoverageDelta] = useState<{ line?: number; branch?: number }>({});
  const [expandedCommit, setExpandedCommit] = useState<string>('');
  const [filesForCommit, setFilesForCommit] = useState<Record<string, any[]>>({});
  const [provider, setProvider] = useState<'all'|'github'|'gitlab'|'generic'>('all');
  const [days, setDays] = useState<30|90>(30);
  const [testTrend, setTestTrend] = useState<any[]>([]);
  const [coverageTrend, setCoverageTrend] = useState<any[]>([]);
  const [failedOpen, setFailedOpen] = useState(false);
  const [failedFor, setFailedFor] = useState<{provider?: string; commit_sha?: string; pr_number?: number}>({});
  const [failedDetails, setFailedDetails] = useState<any[]>([]);

  useEffect(() => { (async () => { const ps = await listProjects(); setProjects(ps); if (ps.length) setProjectId(ps[0].id); })(); }, []);
  useEffect(() => { (async () => {
    if (!projectId) return;
    setProgress({ active: true, percent: 5, step: 'Loading test runs...' });
    const params: any = { project_id: projectId };
    if (provider !== 'all') params.provider = provider;
    const { data: runsResp } = await api.get('/v1/testing/runs', { params });
    setRuns(runsResp.runs || []);
    setProgress({ active: true, percent: 35, step: 'Loading coverage history...' });
    const { data: covResp } = await api.get('/v1/testing/coverage/list', { params: { project_id: projectId } });
    setCoverageList(covResp.coverage || []);
    // default baseline/compare
    if ((covResp.coverage || []).length >= 2) {
      setBaseline(covResp.coverage[1].commit_sha || '');
      setCompare(covResp.coverage[0].commit_sha || '');
    }
    setProgress({ active: true, percent: 55, step: 'Loading test trend...' });
    try { const tt = await getTestTrend(Number(projectId), days); setTestTrend(tt.trend || []); } catch {}
    setProgress({ active: true, percent: 75, step: 'Loading coverage trend...' });
    try { const ct = await getCoverageTrend(Number(projectId), days); setCoverageTrend(ct.trend || []); } catch {}
    // Pull recent test results for advanced analytics
    try {
      const { data: resResp } = await api.get('/v1/testing/results', { params: { project_id: projectId, since_days: days, limit: 500 } });
      const arr = resResp.results || [];
      setResults(arr);
      // Duration trend by day (avg)
      const buckets: Record<string, { sum: number; n: number }> = {};
      arr.forEach((r:any) => {
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
      arr.forEach((r:any) => {
        const id = `${r.classname||''}::${r.name||''}`;
        if (!tests[id]) tests[id] = { classname: r.classname||'', name: r.name||'', runs: 0, fails: 0 };
        tests[id].runs += 1;
        const st = (r.status||'').toLowerCase();
        if (st === 'failed' || st === 'error') tests[id].fails += 1;
      });
      const fl = Object.entries(tests)
        .filter(([_, t]) => t.runs >= 3)
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
    } catch {}
    setProgress({ active: false, percent: 100, step: 'Ready' });
  })(); }, [projectId, provider, days]);

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
        setFailedFor({ provider: p.row.provider, commit_sha: p.row.commit_sha, pr_number: p.row.pr_number });
        setFailedOpen(true);
        try {
          const { data } = await api.get('/v1/testing/results', { params: { project_id: projectId, commit_sha: p.row.commit_sha } });
          const errs = (data.results || []).filter((r: any) => ['failed','error'].includes((r.status||'').toLowerCase()));
          setFailedDetails(errs);
        } catch {
          setFailedDetails([]);
        }
      }}>Failed Details</Button>
    )}
  ];

  const testTrendData = useMemo(() => ({
    labels: testTrend.map((d:any)=> d.day),
    datasets: [
      { label: 'Total', data: testTrend.map((d:any)=> d.total), borderColor: 'rgba(75,192,192,0.9)', backgroundColor:'rgba(75,192,192,0.2)' },
      { label: 'Failed', data: testTrend.map((d:any)=> d.failed), borderColor: 'rgba(255,99,132,0.9)', backgroundColor:'rgba(255,99,132,0.2)' },
    ]
  }), [testTrend]);

  const coverageTrendData = useMemo(() => ({
    labels: coverageTrend.map((d:any)=> d.day),
    datasets: [
      { label: 'Line %', data: coverageTrend.map((d:any)=> Math.round((d.avg_line||0)*1000)/10), borderColor: 'rgba(54,162,235,0.9)', backgroundColor: 'rgba(54,162,235,0.2)' },
      { label: 'Branch %', data: coverageTrend.map((d:any)=> Math.round((d.avg_branch||0)*1000)/10), borderColor: 'rgba(255,206,86,0.9)', backgroundColor: 'rgba(255,206,86,0.2)' },
    ]
  }), [coverageTrend]);

  const durationTrendData = useMemo(() => ({
    labels: durationTrend.map(d=> d.day),
    datasets: [
      { label: 'Avg Test Duration (s)', data: durationTrend.map(d=> Math.round((d.avg||0)*100)/100), borderColor:'rgba(153,102,255,0.9)', backgroundColor:'rgba(153,102,255,0.2)' }
    ]
  }), [durationTrend]);

  useEffect(() => {
    if (!baseline || !compare) { setCoverageDelta({}); return; }
    const base = coverageList.find((c)=> c.commit_sha === baseline);
    const comp = coverageList.find((c)=> c.commit_sha === compare);
    if (!base || !comp) { setCoverageDelta({}); return; }
    const dl = (comp.line_coverage || 0) - (base.line_coverage || 0);
    const db = (comp.branch_coverage || 0) - (base.branch_coverage || 0);
    setCoverageDelta({ line: dl, branch: db });
  }, [baseline, compare, coverageList]);

  const showEmptyState = !progress.active && runs.length === 0 && projectId;

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4">Testing Overview</Typography>
        <Box display="flex" gap={2} alignItems="center">
          <FormControl size="small" sx={{ minWidth: 200 }}>
            <InputLabel>Project</InputLabel>
            <Select label="Project" value={projectId} onChange={(e)=> setProjectId(e.target.value as any)}>
              {projects.map((p)=> (<MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>))}
            </Select>
          </FormControl>
          <ToggleButtonGroup size="small" exclusive value={provider} onChange={(_, v)=> v && setProvider(v)}>
            <ToggleButton value="all">All</ToggleButton>
            <ToggleButton value="github">GitHub</ToggleButton>
            <ToggleButton value="gitlab">GitLab</ToggleButton>
            <ToggleButton value="generic">Generic</ToggleButton>
          </ToggleButtonGroup>
          <FormControl size="small" sx={{ minWidth: 140 }}>
            <InputLabel>Range</InputLabel>
            <Select label="Range" value={days} onChange={(e)=> setDays(e.target.value as any)}>
              <MenuItem value={30}>Last 30 days</MenuItem>
              <MenuItem value={90}>Last 90 days</MenuItem>
            </Select>
          </FormControl>
        </Box>
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
            const csv = [headers.join(',')].concat(rows.map((r:any)=> headers.map(h=> JSON.stringify(r[h] ?? '')).join(','))).join('\n');
            const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a'); a.href = url; a.download = 'test_results.csv'; a.click(); URL.revokeObjectURL(url);
          }}>Export Results CSV</Button>
          <Button size="small" variant="outlined" disabled={!expandedCommit || !(filesForCommit[expandedCommit]?.length)} onClick={()=>{
            const files = filesForCommit[expandedCommit] || [];
            const headers = ['file_path','line_coverage','branch_coverage','lines_covered','lines_total'];
            const csv = [headers.join(',')].concat(files.map((f:any)=> headers.map(h=> JSON.stringify(f[h] ?? '')).join(','))).join('\n');
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
              <Line data={testTrendData as any} options={{ responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'top' as const } } }} />
            </Box>
          </Paper>
        </Grid>
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>Coverage Trend</Typography>
            <Box height={300}>
              <Line data={coverageTrendData as any} options={{ responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'top' as const } } }} />
            </Box>
          </Paper>
        </Grid>
      </Grid>

      <Grid container spacing={2} sx={{ mt: 1 }}>
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>Duration Trend</Typography>
            <Box height={300}>
              <Line data={durationTrendData as any} options={{ responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'top' as const } } }} />
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
              {coverageList.slice(0, 10).map((c:any) => (
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
                        try { const f = await getCoverageFiles(key); setFilesForCommit((m)=> ({ ...m, [key]: f.files || [] })); } catch {}
                      }
                    }}>{expandedCommit === c.commit_sha ? 'Hide Files' : 'Show Files'}</Button>
                  </Box>
                  {expandedCommit === c.commit_sha && (
                    <Box sx={{ pl: 1 }}>
                      {(filesForCommit[c.commit_sha] || []).slice(0, 50).map((f:any)=> (
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
                <Select label="Baseline" value={baseline} onChange={(e)=> setBaseline(e.target.value as string)}>
                  {coverageList.slice(0,20).map((c:any)=> (
                    <MenuItem key={c.commit_sha} value={c.commit_sha}>{(c.commit_sha||'').slice(0,8)}</MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl size="small" sx={{ minWidth: 140 }}>
                <InputLabel>Compare</InputLabel>
                <Select label="Compare" value={compare} onChange={(e)=> setCompare(e.target.value as string)}>
                  {coverageList.slice(0,20).map((c:any)=> (
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

      <Dialog open={failedOpen} onClose={()=> setFailedOpen(false)} fullWidth maxWidth="md">
        <DialogTitle>Failed Tests</DialogTitle>
        <DialogContent>
          {failedDetails.length === 0 ? (
            <Typography variant="body2">No failed tests found.</Typography>
          ) : (
            failedDetails.map((r:any, idx:number)=> (
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
