import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
  LinearProgress,
  MenuItem,
  Paper,
  Select,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import type { SelectChangeEvent } from '@mui/material/Select';
import {
  Add as AddIcon,
  ContentCopy as DuplicateIcon,
  Delete as DeleteIcon,
  Edit as EditIcon,
  PlayArrow as ExecuteIcon,
  Refresh as RefreshIcon,
} from '@mui/icons-material';
import {
  createRule,
  deleteRule,
  executeRule,
  getRules,
  updateRule,
} from '../services/api';
import type { TraceabilityRule } from '../services/api';
import { getErrorMessage } from '../utils/errorUtils';

type EnabledFilter = 'all' | 'enabled' | 'disabled';

/**
 * Standalone rules management page (plan_73).
 *
 * List-first operational view over the existing rule lifecycle endpoints:
 * search, enable/disable, duplicate, execute, delete (with the delete-cascade
 * contract surfaced as a 409 error), and routing into the visual builder for
 * flow editing.
 */
const RulesManagement: React.FC = () => {
  const navigate = useNavigate();
  const [rules, setRules] = useState<TraceabilityRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [enabledFilter, setEnabledFilter] = useState<EnabledFilter>('all');
  const [deleteTarget, setDeleteTarget] = useState<TraceabilityRule | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const fetchRules = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await getRules({ limit: 200 });
      // getRules normalizes to PaginatedResponse ({ data, meta }).
      setRules(response.data);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to load rules'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchRules();
  }, [fetchRules]);

  const handleEnabledFilterChange = (event: SelectChangeEvent<string>) => {
    const value = event.target.value;
    setEnabledFilter(value === 'enabled' || value === 'disabled' ? value : 'all');
  };

  const visibleRules = useMemo(() => {
    const term = search.trim().toLowerCase();
    return rules.filter((rule) => {
      if (enabledFilter === 'enabled' && !rule.enabled) return false;
      if (enabledFilter === 'disabled' && rule.enabled) return false;
      if (term && !rule.name.toLowerCase().includes(term)) return false;
      return true;
    });
  }, [rules, search, enabledFilter]);

  const runAction = async (id: number, fn: () => Promise<unknown>) => {
    setBusyId(id);
    setActionError(null);
    try {
      await fn();
      await fetchRules();
    } catch (err: unknown) {
      setActionError(getErrorMessage(err, 'Action failed'));
    } finally {
      setBusyId(null);
    }
  };

  const handleToggleEnabled = (rule: TraceabilityRule) =>
    runAction(rule.id, () => updateRule(rule.id, { enabled: !rule.enabled }));

  const handleDuplicate = (rule: TraceabilityRule) =>
    runAction(rule.id, () =>
      createRule({
        name: `${rule.name} (copy)`,
        description: rule.description ?? undefined,
        flow_json: rule.flow_json,
        enabled: false,
        category: rule.category,
        tags: rule.tags,
        project_id: rule.project_id ?? undefined,
      })
    );

  const handleExecute = (rule: TraceabilityRule) =>
    runAction(rule.id, () => executeRule(rule.id));

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    const target = deleteTarget;
    setDeleteTarget(null);
    await runAction(target.id, () => deleteRule(target.id));
  };

  if (loading) {
    return (
      <Box sx={{ width: '100%', mt: 2 }} data-testid="rules-loading">
        <LinearProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error" action={<Button onClick={() => void fetchRules()}>Retry</Button>}>
          {error}
        </Alert>
      </Box>
    );
  }

  return (
    <Box sx={{ p: 3 }}>
      <Box sx={{ mb: 3, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography variant="h4">Traceability Rules</Typography>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Tooltip title="Refresh">
            <IconButton onClick={() => void fetchRules()} aria-label="Refresh rules">
              <RefreshIcon />
            </IconButton>
          </Tooltip>
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => navigate('/traceability/flow-builder')}
          >
            New Rule
          </Button>
        </Box>
      </Box>

      {actionError && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setActionError(null)}>
          {actionError}
        </Alert>
      )}

      <Box sx={{ mb: 2, display: 'flex', gap: 2 }}>
        <TextField
          label="Search rules"
          size="small"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          inputProps={{ 'aria-label': 'Search rules' }}
        />
        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel>Status</InputLabel>
          <Select value={enabledFilter} label="Status" onChange={handleEnabledFilterChange}>
            <MenuItem value="all">All</MenuItem>
            <MenuItem value="enabled">Enabled</MenuItem>
            <MenuItem value="disabled">Disabled</MenuItem>
          </Select>
        </FormControl>
      </Box>

      {visibleRules.length === 0 ? (
        <Alert severity="info">No rules match the current filters.</Alert>
      ) : (
        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Automation</TableCell>
                <TableCell>Last Run</TableCell>
                <TableCell>Failures</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {visibleRules.map((rule) => (
                <TableRow key={rule.id} data-testid={`rule-row-${rule.id}`}>
                  <TableCell>{rule.name}</TableCell>
                  <TableCell>
                    <Chip
                      label={rule.enabled ? 'Enabled' : 'Disabled'}
                      color={rule.enabled ? 'success' : 'default'}
                      size="small"
                    />
                  </TableCell>
                  <TableCell>
                    {rule.schedule_enabled && (
                      <Chip label="Schedule" size="small" sx={{ mr: 0.5 }} />
                    )}
                    {rule.trigger_on_webhook && (
                      <Chip label="Webhook" size="small" sx={{ mr: 0.5 }} />
                    )}
                    {rule.execute_on_sync_complete && (
                      <Chip label="Post-sync" size="small" />
                    )}
                  </TableCell>
                  <TableCell>
                    {rule.last_executed_at
                      ? new Date(rule.last_executed_at).toLocaleString()
                      : '—'}
                  </TableCell>
                  <TableCell>{rule.failed_executions}</TableCell>
                  <TableCell align="right">
                    <Tooltip title="Edit in builder">
                      <IconButton
                        size="small"
                        aria-label={`Edit ${rule.name}`}
                        onClick={() =>
                          navigate(`/traceability/flow-builder?ruleId=${rule.id}`)
                        }
                      >
                        <EditIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Execute">
                      <span>
                        <IconButton
                          size="small"
                          aria-label={`Execute ${rule.name}`}
                          disabled={!rule.enabled || busyId === rule.id}
                          onClick={() => void handleExecute(rule)}
                        >
                          <ExecuteIcon fontSize="small" />
                        </IconButton>
                      </span>
                    </Tooltip>
                    <Tooltip title="Duplicate">
                      <span>
                        <IconButton
                          size="small"
                          aria-label={`Duplicate ${rule.name}`}
                          disabled={busyId === rule.id}
                          onClick={() => void handleDuplicate(rule)}
                        >
                          <DuplicateIcon fontSize="small" />
                        </IconButton>
                      </span>
                    </Tooltip>
                    <Button
                      size="small"
                      disabled={busyId === rule.id}
                      onClick={() => void handleToggleEnabled(rule)}
                    >
                      {rule.enabled ? 'Disable' : 'Enable'}
                    </Button>
                    <Tooltip title="Delete">
                      <span>
                        <IconButton
                          size="small"
                          color="error"
                          aria-label={`Delete ${rule.name}`}
                          disabled={busyId === rule.id}
                          onClick={() => setDeleteTarget(rule)}
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </span>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <Dialog open={deleteTarget !== null} onClose={() => setDeleteTarget(null)}>
        <DialogTitle>Delete rule?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Delete &quot;{deleteTarget?.name}&quot;? Its execution history is removed. Artifact
            links are kept. Deletion is blocked if unresolved review items reference this rule.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button color="error" onClick={() => void confirmDelete()}>
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default RulesManagement;
