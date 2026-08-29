import React, { useEffect, useMemo, useState } from 'react';
import { Box, Paper, Typography, Chip, Button, FormControl, InputLabel, Select, MenuItem, TextField, ToggleButtonGroup, ToggleButton, Tabs, Tab } from '@mui/material';
import { DataGrid, GridColDef } from '@mui/x-data-grid';
import { VerifiedUser as VerifiedUserIcon, BugReport as BugReportIcon, Shield as ShieldIcon, Assessment as AssessmentIcon } from '@mui/icons-material';
import type { SelectChangeEvent } from '@mui/material/Select';
import {
  getProjectById,
  updateProject,
  listPullRequests,
  getQualityGateStatus,
  evaluateQualityGateAndCheck,
  getIntegrationsHealth,
  getMetricsText,
  type Project,
  type QualityPullRequest,
  type QualityGateResult,
  type QualityGateProvider,
} from '../services/api';
import { useProjects } from '../services/api/hooks';
import CircularProgressWithLabel from '../components/CircularProgressWithLabel';
import EmptyState from '../components/EmptyState';
import { QualityDashboard, QualityReportPanel } from '../components/quality';
import { normalizeQualityGateProvider } from '../utils/qualityGate';
import { getErrorMessage } from '../utils/errorUtils';

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

const parseProjectId = (value: string): number | '' => {
  if (value === '') {
    return '';
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : '';
};

const isQualityGateProvider = (value: string): value is QualityGateProvider =>
  value === 'github' || value === 'gitlab' || value === 'generic';

const TabPanel: React.FC<TabPanelProps> = ({ children, value, index }) => (
  <Box role="tabpanel" hidden={value !== index} sx={{ py: 2 }}>
    {value === index && children}
  </Box>
);

const Quality: React.FC = () => {
  const [activeTab, setActiveTab] = useState(0);
  // projects come from the shared React Query cache (E1), not local state
  // only the user's explicit choice lives in state; the default is derived
  const [manualProjectId, setManualProjectId] = useState<number | ''>('');
  const [prs, setPRs] = useState<QualityPullRequest[]>([]);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState<{ active: boolean; percent: number; step: string }>({ active: false, percent: 0, step: '' });
  const [thresholds, setThresholds] = useState<{ min_line?: number; min_branch?: number }>({});
  const [gateMap, setGateMap] = useState<Record<number, QualityGateResult>>({});
  const [provider, setProvider] = useState<'all' | QualityGateProvider>('all');
  const [statusFilter, setStatusFilter] = useState<'all'|'pass'|'fail'>('all');
  const [days, setDays] = useState<30|90>(30);
  const [webhookInfo, setWebhookInfo] = useState<string>('');

  const handleStatusFilterChange = (event: SelectChangeEvent<string>) => {
    const value = event.target.value;
    if (value === 'all' || value === 'pass' || value === 'fail') {
      setStatusFilter(value);
    }
  };

  const handleDaysChange = (event: SelectChangeEvent<string>) => {
    const parsed = Number(event.target.value);
    if (parsed === 30 || parsed === 90) {
      setDays(parsed);
    }
  };

  const handleProjectChange = (event: SelectChangeEvent<string>) => {
    setManualProjectId(parseProjectId(event.target.value));
  };
  const handleTabChange = (_: React.SyntheticEvent, newValue: number) => {
    setActiveTab(newValue);
  };
  const handleProviderChange = (_: React.MouseEvent<HTMLElement>, value: string | null) => {
    if (!value) {
      return;
    }
    if (value === 'all' || isQualityGateProvider(value)) {
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
    (async () => {
      if (!projectId) return;
      try {
        setLoading(true);
        setProgress({ active: true, percent: 5, step: 'Loading Pull Requests...' });
        const pr = await listPullRequests({ projectId: Number(projectId), limit: 100 });
        setPRs(pr.pull_requests || []);
        setProgress({ active: true, percent: 35, step: 'Loading project thresholds...' });
        try {
          const p = await getProjectById(Number(projectId));
          const t = p.quality_thresholds || {};
          setThresholds({ min_line: t.min_line ?? 0.8, min_branch: t.min_branch ?? undefined });
        } catch (err) {
          console.warn('Failed to load project thresholds', err);
        }
        // Preload gate status for each PR
        setProgress({ active: true, percent: 60, step: 'Evaluating current gate statuses...' });
        const gm: Record<number, QualityGateResult> = {};
        let done = 0;
        for (const item of (pr.pull_requests || [])) {
          try {
            const st = await getQualityGateStatus(item.number, { projectId: Number(projectId) });
            gm[item.number] = st;
          } catch (err) {
            console.debug('Failed to load gate status', err);
          }
          done++;
          setProgress({ active: true, percent: 60 + Math.round((done / Math.max(1, pr.pull_requests.length)) * 35), step: `Evaluating gates... ${done}/${pr.pull_requests.length}` });
        }
        setGateMap(gm);
      } finally {
        setLoading(false);
        setProgress({ active: false, percent: 100, step: 'Ready' });
      }
    })();
  }, [projectId]);

  useEffect(() => {
    (async () => {
      try {
        const health = await getIntegrationsHealth();
        let info = health?.jira?.configured || health?.github ? 'Integrations OK' : 'Integrations: check settings';
        // Parse metrics for webhook activity
        const txt = await getMetricsText();
        const m = /webhook_received_total\{provider="github", event="([^"]+)"\} (\d+)/g;
        let total = 0; let match;
        while ((match = m.exec(txt)) !== null) { total += Number(match[2] || 0); }
        info = `GitHub Webhooks: ${total}`;
        setWebhookInfo(info);
      } catch (err) {
        console.warn('Failed to load integration metrics', err);
      }
    })();
  }, []);

  const handleSaveThresholds = async () => {
    if (!projectId) return;
    try {
      await updateProject(Number(projectId), { quality_thresholds: thresholds });
    } catch (e) {
      console.error(e);
    }
  };

  const checkGate = async (number: number, provider?: QualityGateProvider) => {
    if (!projectId) return;
    setGateMap((m) => ({ ...m, [number]: { ...m[number], checking: true } }));
    try {
      const providerType = normalizeQualityGateProvider(provider);
      const res = await evaluateQualityGateAndCheck({ prNumber: number, projectId: Number(projectId), provider: providerType });
      setGateMap((m) => ({ ...m, [number]: { ...(m[number] || {}), checking: false, result: res } }));
    } catch (e) {
      const errorMessage = getErrorMessage(e, 'Failed to evaluate quality gate');
      setGateMap((m) => ({ ...m, [number]: { ...(m[number] || {}), checking: false, error: errorMessage } }));
    }
  };

  const GateChip: React.FC<{ st: QualityGateResult | undefined }> = ({ st }) => {
    if (!st) return <Chip size="small" label="N/A" />;
    const pass = st.pass ?? st?.result?.pass;
    const label = pass ? 'PASS' : 'FAIL';
    return <Chip size="small" color={pass ? 'success' : 'error'} label={label} />;
  };

  const filteredPRs = useMemo(() => {
    let list = prs.slice();
    if (provider !== 'all') list = list.filter((p) => (p.provider || '').toLowerCase() === provider);
    if (days) {
      const since = Date.now() - days * 24 * 3600 * 1000;
      list = list.filter((p) => {
        const t = p.opened_at ? new Date(p.opened_at).getTime() : 0;
        return !t || t >= since;
      });
    }
    if (statusFilter !== 'all') {
      list = list.filter((p) => {
        const st = gateMap[p.number];
        const pass = st?.pass ?? st?.result?.pass;
        return statusFilter === 'pass' ? !!pass : pass === false;
      });
    }
    return list;
  }, [prs, provider, statusFilter, days, gateMap]);

  const columns: GridColDef[] = [
    { field: 'number', headerName: 'PR #', width: 90 },
    { field: 'title', headerName: 'Title', flex: 1, minWidth: 200 },
    { field: 'provider', headerName: 'Provider', width: 110, valueGetter: (p) => (p.row.provider || '').toUpperCase() },
    { field: 'state', headerName: 'State', width: 110 },
    { field: 'gate', headerName: 'Gate', width: 100, renderCell: (params) => <GateChip st={gateMap[params.row.number]} /> },
    { field: 'cycle_time_hours', headerName: 'Cycle (h)', width: 110, valueFormatter: (p) => (p.value ? p.value.toFixed(1) : '0.0') },
    { field: 'lead_time_hours', headerName: 'Lead (h)', width: 110, valueFormatter: (p) => (p.value ? p.value.toFixed(1) : '0.0') },
    { field: 'time_to_first_review_hours', headerName: 'TtFR (h)', width: 120, valueFormatter: (p) => (p.value ? p.value.toFixed(1) : '0.0') },
    { field: 'rework_count', headerName: 'Rework', width: 100, renderCell: (params) => (
      <Box sx={{ color: (Number(params.value || 0) > 2) ? 'error.main' : 'text.primary' }}>
        {params.value ?? 0}
      </Box>
    ) },
    { field: 'files_changed', headerName: 'Files', width: 90 },
    { field: 'lines', headerName: 'Lines', width: 140, valueGetter: (p)=> `+${p.row.lines_added||0}/-${p.row.lines_deleted||0}` },
    { field: 'actions', headerName: 'Actions', width: 160, sortable: false, renderCell: (params) => {
      const checkUrl = gateMap[params.row.number]?.result?.github_check?.response?.html_url;
      return (
        <Box display="flex" gap={1}>
          <Button size="small" variant="outlined" onClick={() => checkGate(params.row.number, params.row.provider)} disabled={gateMap[params.row.number]?.checking}>Check</Button>
          {checkUrl && (
            <Button size="small" href={checkUrl} target="_blank">Check Run</Button>
          )}
        </Box>
      );
    } },
  ];

  const showEmptyState = !loading && prs.length === 0 && projectId;

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h4">Quality & Testing</Typography>
        <FormControl size="small" sx={{ minWidth: 220 }}>
          <InputLabel>Project</InputLabel>
          <Select<string>
            label="Project"
            value={projectId === '' ? '' : String(projectId)}
            onChange={handleProjectChange}
          >
            {projects.map((p)=> (
              <MenuItem key={p.id} value={String(p.id)}>{p.name}</MenuItem>
            ))}
          </Select>
        </FormControl>
      </Box>

      <Paper sx={{ mb: 3 }}>
        <Tabs value={activeTab} onChange={handleTabChange} variant="fullWidth">
          <Tab icon={<VerifiedUserIcon />} label="PR Quality Gates" iconPosition="start" />
          <Tab icon={<BugReportIcon />} label="Escaped Defects" iconPosition="start" />
          <Tab icon={<ShieldIcon />} label="Quality Dashboard" iconPosition="start" />
          <Tab icon={<AssessmentIcon />} label="Reports" iconPosition="start" />
        </Tabs>
      </Paper>

      <TabPanel value={activeTab} index={0}>
      {showEmptyState && (
        <Box sx={{ my: 4 }}>
          <EmptyState
            icon={<VerifiedUserIcon sx={{ fontSize: 80 }} />}
            title="No Pull Requests Found"
            description="Quality Gates monitor PR coverage automatically once you connect your Git provider"
            primaryAction={{
              label: 'Setup GitHub',
              onClick: () => window.location.href = '/settings',
            }}
            secondaryAction={{
              label: 'Setup GitLab',
              onClick: () => window.location.href = '/settings',
            }}
            benefits={[
              'Automatic PR quality checks',
              'Code coverage validation',
              'Customizable quality thresholds',
              'GitHub/GitLab status checks integration',
            ]}
            setupSteps={[
              'Configure GitHub or GitLab integration in Settings',
              'Add webhook to your repositories',
              'PRs will appear here automatically after webhook setup',
            ]}
          />
        </Box>
      )}

      {progress.active && (
        <Paper sx={{ p: 2, mb: 2, display: 'flex', justifyContent: 'center' }}>
          <CircularProgressWithLabel value={progress.percent} label={progress.step} />
        </Paper>
      )}

      <Paper sx={{ p: 2, mb: 3 }}>
        <Typography variant="h6" gutterBottom>Project Thresholds</Typography>
        <Box display="flex" gap={2} alignItems="center" flexWrap="wrap">
          <TextField type="number" label="Min Line Coverage" value={thresholds.min_line ?? ''} onChange={(e)=> setThresholds((t)=> ({ ...t, min_line: e.target.value === '' ? undefined : Number(e.target.value) }))} size="small" inputProps={{ step: 0.01, min: 0, max: 1 }} />
          <TextField type="number" label="Min Branch Coverage" value={thresholds.min_branch ?? ''} onChange={(e)=> setThresholds((t)=> ({ ...t, min_branch: e.target.value === '' ? undefined : Number(e.target.value) }))} size="small" inputProps={{ step: 0.01, min: 0, max: 1 }} />
          <Button variant="contained" onClick={handleSaveThresholds}>Save</Button>
          <Box display="flex" gap={1}>
            <Button size="small" onClick={()=> setThresholds({ min_line: 0.9, min_branch: 0.8 })}>Strict</Button>
            <Button size="small" onClick={()=> setThresholds({ min_line: 0.8, min_branch: 0.7 })}>Normal</Button>
            <Button size="small" onClick={()=> setThresholds({ min_line: 0.7, min_branch: 0.6 })}>Lenient</Button>
          </Box>
          <Chip size="small" label={webhookInfo} />
        </Box>
      </Paper>

      <Paper sx={{ p: 2 }}>
        <Box display="flex" gap={2} alignItems="center" flexWrap="wrap" mb={2}>
          <FormControl size="small" sx={{ minWidth: 160 }}>
            <InputLabel>Status</InputLabel>
            <Select label="Status" value={statusFilter} onChange={handleStatusFilterChange}>
              <MenuItem value="all">All</MenuItem>
              <MenuItem value="pass">PASS</MenuItem>
              <MenuItem value="fail">FAIL</MenuItem>
            </Select>
          </FormControl>
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
          <Button size="small" variant="outlined" onClick={async()=>{
            // Bulk check displayed PRs
            for (const pr of filteredPRs) {
              await checkGate(pr.number, pr.provider);
            }
          }}>Bulk Check</Button>
        </Box>
        <div style={{ height: 520, width: '100%' }}>
          <DataGrid
            rows={filteredPRs}
            getRowId={(r) => `${r.provider}-${r.number}`}
            columns={columns}
            pageSizeOptions={[10, 25, 50, 100]}
            initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
            disableRowSelectionOnClick
            loading={loading}
          />
        </div>
      </Paper>
      </TabPanel>

      <TabPanel value={activeTab} index={1}>
        {projectId ? (
          <QualityDashboard projectId={Number(projectId)} />
        ) : (
          <Paper sx={{ p: 4, textAlign: 'center' }}>
            <Typography color="text.secondary">Select a project to view escaped defects</Typography>
          </Paper>
        )}
      </TabPanel>

      <TabPanel value={activeTab} index={2}>
        {projectId ? (
          <QualityDashboard projectId={Number(projectId)} />
        ) : (
          <Paper sx={{ p: 4, textAlign: 'center' }}>
            <Typography color="text.secondary">Select a project to view quality dashboard</Typography>
          </Paper>
        )}
      </TabPanel>

      <TabPanel value={activeTab} index={3}>
        <QualityReportPanel
          projectId={projectId ? Number(projectId) : undefined}
        />
      </TabPanel>
    </Box>
  );
};

export default Quality;
