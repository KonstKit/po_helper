import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useDebouncedValue, DEBOUNCE_DELAYS } from '../hooks/useDebounce';
import {
  Box,
  Typography,
  Paper,
  Button,
  Chip,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Snackbar,
  Alert,
} from '@mui/material';
import type { SelectChangeEvent } from '@mui/material/Select';
import {
  Download as DownloadIcon,
  Refresh as RefreshIcon,
} from '@mui/icons-material';
import { DataGrid, GridColDef, GridToolbar, GridPaginationModel } from '@mui/x-data-grid';
import { listTasksPaginated, listProjects, setTaskBusinessValue, withRetry, type Project, type TaskItem } from '../services/api';
import { getErrorMessage } from '../utils/errorUtils';

/** Extended task row with computed display fields */
interface TaskRow extends TaskItem {
  assignee: string;
  project: string;
}

const defaultFilters = { status: '', assignee: '', project: '' };

const getStatusChipColor = (status: string): 'default' | 'primary' | 'secondary' | 'error' | 'info' | 'success' | 'warning' => {
  switch (status) {
    case 'Done':
      return 'success';
    case 'In Progress':
      return 'primary';
    case 'Review':
    case 'In Review':
      return 'warning';
    case 'Todo':
    case 'Backlog':
      return 'default';
    default:
      return 'info';
  }
};

const getPriorityChipColor = (priority?: string | null): 'default' | 'primary' | 'secondary' | 'error' | 'info' | 'success' | 'warning' => {
  switch ((priority || '').toLowerCase()) {
    case 'critical':
      return 'error';
    case 'high':
      return 'warning';
    case 'medium':
      return 'info';
    case 'low':
      return 'success';
    default:
      return 'default';
  }
};

const Tasks = () => {
  const [filters, setFilters] = useState(defaultFilters);
  const [rows, setRows] = useState<TaskRow[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<{ open: boolean; severity: 'success' | 'error' | 'info' | 'warning'; message: string }>({ open: false, severity: 'info', message: '' });
  const [businessDialog, setBusinessDialog] = useState<{ open: boolean; taskId: number | null; value: string }>({ open: false, taskId: null, value: '' });
  const [businessDialogError, setBusinessDialogError] = useState<string | null>(null);

  // Server-side pagination state
  const [paginationModel, setPaginationModel] = useState<GridPaginationModel>({ page: 0, pageSize: 25 });
  const [rowCount, setRowCount] = useState(0);

  // Debounce filters to prevent excessive API calls
  const debouncedFilters = useDebouncedValue(filters, DEBOUNCE_DELAYS.FILTER);

  const projectOptions = useMemo(() => projects.map((p) => ({ id: p.id, name: p.name })), [projects]);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const map = new Map(projects.map((p) => [p.id, p.name]));
      const selectedProject = projects.find((p) => p.name === debouncedFilters.project);
      const response = await withRetry(
        () => listTasksPaginated({
          status: debouncedFilters.status || undefined,
          assignee: debouncedFilters.assignee || undefined,
          projectId: selectedProject?.id,
          skip: paginationModel.page * paginationModel.pageSize,
          limit: paginationModel.pageSize,
        }, { timeout: 60000 }),
        { retries: 2, baseDelayMs: 500, maxDelayMs: 4000 }
      );
      setRows(
        response.data.map((task): TaskRow => ({
          ...task,
          assignee: task.assignee_name || '',
          project:
            typeof task.project_id === 'number'
              ? map.get(task.project_id) || ''
              : '',
        })),
      );
      setRowCount(response.meta.total);
    } catch (err) {
      console.error('Failed to load tasks', err);
      setToast({ open: true, severity: 'error', message: 'Failed to load tasks' });
    } finally {
      setLoading(false);
    }
  }, [debouncedFilters.assignee, debouncedFilters.project, debouncedFilters.status, projects, paginationModel]);

  useEffect(() => {
    (async () => {
      try {
        const psResp = await withRetry(
          () => listProjects(),
          { retries: 2, baseDelayMs: 300, maxDelayMs: 2000 }
        );
        setProjects(psResp.data);
      } catch (err) {
        console.error('Failed to load projects', err);
        setToast({ open: true, severity: 'error', message: 'Failed to load projects list' });
      }
    })();
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const openBusinessValueDialog = useCallback((task: TaskRow) => {
    setBusinessDialog({ open: true, taskId: task.id, value: task?.business_value != null ? String(task.business_value) : '' });
    setBusinessDialogError(null);
  }, []);

  const closeBusinessValueDialog = useCallback(() => {
    setBusinessDialog({ open: false, taskId: null, value: '' });
    setBusinessDialogError(null);
  }, []);

  const handleBusinessValueSave = async () => {
    if (!businessDialog.taskId) {
      closeBusinessValueDialog();
      return;
    }
    const raw = businessDialog.value.trim();
    const parsed = raw === '' ? NaN : Number(raw);
    if (!Number.isFinite(parsed) || parsed < 0) {
      setBusinessDialogError('Enter a non-negative number');
      return;
    }
    try {
      await setTaskBusinessValue(businessDialog.taskId, { businessValue: parsed });
      await reload();
      setToast({ open: true, severity: 'success', message: 'Business value updated' });
      closeBusinessValueDialog();
    } catch (err) {
      console.error(err);
      const detail = getErrorMessage(err, 'Failed to update business value');
      setToast({ open: true, severity: 'error', message: detail });
    }
  };

  const columns: GridColDef<TaskItem>[] = useMemo(() => [
    { field: 'key', headerName: 'Key', width: 120 },
    { field: 'summary', headerName: 'Summary', flex: 1, minWidth: 240 },
    {
      field: 'status',
      headerName: 'Status',
      width: 160,
      renderCell: (params) => (
        <Chip label={params.value || 'Unknown'} color={getStatusChipColor(params.value)} size="small" />
      ),
    },
    {
      field: 'priority',
      headerName: 'Priority',
      width: 130,
      renderCell: (params) => {
        const label = params.value ? String(params.value) : '--';
        return (
          <Chip label={label} color={getPriorityChipColor(params.value)} size="small" variant="outlined" />
        );
      },
    },
    { field: 'assignee', headerName: 'Assignee', width: 180 },
    { field: 'project', headerName: 'Project', width: 200 },
    {
      field: 'estimate_hours',
      headerName: 'Estimate',
      width: 120,
      type: 'number',
      valueFormatter: (params) => (params.value ? `${params.value}h` : '0h'),
    },
    {
      field: 'spent_hours',
      headerName: 'Spent',
      width: 120,
      type: 'number',
      valueFormatter: (params) => (params.value ? `${params.value}h` : '0h'),
    },
    {
      field: 'deviation',
      headerName: 'Deviation',
      width: 130,
      valueGetter: (params) => {
        const spent = params.row.spent_hours || 0;
        const estimate = params.row.estimate_hours || 0;
        return spent - estimate;
      },
      renderCell: (params) => {
        const deviation = params.value || 0;
        const color = deviation > 0 ? 'error.main' : deviation < 0 ? 'success.main' : 'text.secondary';
        return (
          <Typography color={color} variant="body2">
            {deviation > 0 ? '+' : ''}{deviation}h
          </Typography>
        );
      },
    },
    {
      field: 'due_date',
      headerName: 'Due Date',
      width: 150,
      valueGetter: (params) => (params.value ? new Date(params.value) : null),
      valueFormatter: (params) => (params.value ? new Date(params.value).toLocaleDateString() : ''),
    },
    {
      field: 'business_value_action',
      headerName: 'Business Value',
      width: 170,
      sortable: false,
      filterable: false,
      renderCell: (params) => (
        <Button size="small" variant="outlined" onClick={() => openBusinessValueDialog(params.row)}>Set</Button>
      ),
    },
  ], [openBusinessValueDialog]);

  const handleFilterChange = (field: keyof typeof defaultFilters, value: string) => {
    setFilters((prev) => ({ ...prev, [field]: value }));
    // Reset to first page when filters change
    setPaginationModel((prev) => ({ ...prev, page: 0 }));
  };
  const handleStatusFilterChange = (event: SelectChangeEvent<string>) => {
    handleFilterChange('status', event.target.value);
  };
  const handleProjectFilterChange = (event: SelectChangeEvent<string>) => {
    handleFilterChange('project', event.target.value);
  };

  const handleExport = () => {
    // TODO: Implement task export functionality
  };

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4">Tasks</Typography>
        <Box display="flex" gap={2}>
          <Button variant="outlined" startIcon={<RefreshIcon />} onClick={reload}>
            Refresh
          </Button>
          <Button variant="contained" startIcon={<DownloadIcon />} onClick={handleExport}>
            Export
          </Button>
        </Box>
      </Box>

      <Paper sx={{ p: 2, mb: 3 }}>
        <Box display="flex" gap={2} alignItems="center" flexWrap="wrap">
          <Typography variant="subtitle1">Filters:</Typography>
          <FormControl size="small" sx={{ minWidth: 150 }}>
            <InputLabel>Status</InputLabel>
            <Select value={filters.status} label="Status" onChange={handleStatusFilterChange}>
              <MenuItem value="">All</MenuItem>
              <MenuItem value="Todo">Todo</MenuItem>
              <MenuItem value="In Progress">In Progress</MenuItem>
              <MenuItem value="Review">Review</MenuItem>
              <MenuItem value="Done">Done</MenuItem>
            </Select>
          </FormControl>
          <TextField
            size="small"
            label="Assignee"
            value={filters.assignee}
            onChange={(e) => handleFilterChange('assignee', e.target.value)}
            sx={{ width: 180 }}
          />
          <FormControl size="small" sx={{ minWidth: 200 }}>
            <InputLabel>Project</InputLabel>
            <Select value={filters.project} label="Project" onChange={handleProjectFilterChange}>
              <MenuItem value="">All</MenuItem>
              {projectOptions.map((p) => (
                <MenuItem key={p.id} value={p.name}>
                  {p.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Button variant="text" onClick={() => {
            setFilters(defaultFilters);
            setPaginationModel((prev) => ({ ...prev, page: 0 }));
          }}>
            Clear Filters
          </Button>
        </Box>
      </Paper>

      <Paper sx={{ height: 600, width: '100%' }}>
        <DataGrid
          rows={rows}
          columns={columns}
          loading={loading}
          paginationMode="server"
          rowCount={rowCount}
          paginationModel={paginationModel}
          onPaginationModelChange={setPaginationModel}
          pageSizeOptions={[25, 50, 100]}
          checkboxSelection
          disableRowSelectionOnClick
          slots={{ toolbar: GridToolbar }}
          slotProps={{
            toolbar: {
              showQuickFilter: true,
              quickFilterProps: { debounceMs: 500 },
            },
          }}
        />
      </Paper>

      <Dialog open={businessDialog.open} onClose={closeBusinessValueDialog} fullWidth maxWidth="xs">
        <DialogTitle>Set Business Value</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            margin="dense"
            label="Business value (РІвЂ°Тђ 0)"
            type="number"
            fullWidth
            value={businessDialog.value}
            onChange={(e) => {
              setBusinessDialog((prev) => ({ ...prev, value: e.target.value }));
              if (businessDialogError) setBusinessDialogError(null);
            }}
            error={Boolean(businessDialogError)}
            helperText={businessDialogError || ' '}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={closeBusinessValueDialog}>Cancel</Button>
          <Button variant="contained" onClick={handleBusinessValueSave}>
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={toast.open}
        autoHideDuration={4000}
        onClose={() => setToast((prev) => ({ ...prev, open: false }))}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert
          severity={toast.severity}
          onClose={() => setToast((prev) => ({ ...prev, open: false }))}
          sx={{ width: '100%' }}
        >
          {toast.message}
        </Alert>
      </Snackbar>
    </Box>
  );
};

export default Tasks;
