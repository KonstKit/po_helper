import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
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
  Tooltip,
  Typography,
} from '@mui/material';
import type { SelectChangeEvent } from '@mui/material/Select';
import { Refresh as RefreshIcon } from '@mui/icons-material';
import SearchOffIcon from '@mui/icons-material/SearchOff';
import {
  claimReviewItem,
  listReviewItems,
  rejectReviewItem,
  resolveReviewItem,
} from '../services/api';
import type { ReviewItem, ReviewItemStatus } from '../services/api';
import { getErrorMessage } from '../utils/errorUtils';
import { useSelectedProject } from '../hooks/useSelectedProject';
import EmptyState from '../components/common/EmptyState';

type StatusFilter = 'all' | ReviewItemStatus;

const STATUS_OPTIONS: ReviewItemStatus[] = ['pending', 'claimed', 'resolved', 'rejected'];
const STATUS_SET = new Set<string>(STATUS_OPTIONS);

const statusColor = (
  status: ReviewItemStatus
): 'default' | 'warning' | 'info' | 'success' | 'error' => {
  switch (status) {
    case 'pending':
      return 'warning';
    case 'claimed':
      return 'info';
    case 'resolved':
      return 'success';
    case 'rejected':
      return 'error';
    default:
      return 'default';
  }
};

/**
 * Manual review queue (plan_70). Operators triage artifacts a rule flagged for
 * review: claim, resolve, or reject items with a durable, auditable lifecycle.
 */
const ReviewQueue: React.FC = () => {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('pending');
  // Project comes from the single global selector in the header (UX review C5),
  // not a free-text "Project ID" field the user has to remember and type.
  const { projectId, currentProject, loading: projectsLoading } = useSelectedProject();
  const [busyId, setBusyId] = useState<number | null>(null);

  const fetchItems = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await listReviewItems({
        status: statusFilter === 'all' ? undefined : statusFilter,
        projectId: projectId && projectId > 0 ? projectId : undefined,
        limit: 100,
      });
      setItems(response.items);
      setTotal(response.total);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to load review items'));
    } finally {
      setLoading(false);
    }
  }, [statusFilter, projectId]);

  useEffect(() => {
    // Codex m-1: don't fire an unscoped request before the global project
    // resolves on cold load (it would flash/err for non-admins). Once the
    // project list has loaded, projectId is stable and we always fetch.
    if (projectId == null && projectsLoading) return;
    void fetchItems();
  }, [fetchItems, projectId, projectsLoading]);

  const handleStatusFilterChange = (event: SelectChangeEvent<string>) => {
    const value = event.target.value;
    setStatusFilter(value !== 'all' && STATUS_SET.has(value) ? (value as ReviewItemStatus) : 'all');
  };

  const runAction = async (id: number, fn: () => Promise<unknown>) => {
    setBusyId(id);
    setActionError(null);
    try {
      await fn();
      await fetchItems();
    } catch (err: unknown) {
      setActionError(getErrorMessage(err, 'Action failed'));
    } finally {
      setBusyId(null);
    }
  };

  if (loading) {
    return (
      <Box sx={{ width: '100%', mt: 2 }} data-testid="review-loading">
        <LinearProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error" action={<Button onClick={() => void fetchItems()}>Retry</Button>}>
          {error}
        </Alert>
      </Box>
    );
  }

  return (
    <Box sx={{ p: 3 }}>
      <Box sx={{ mb: 3, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography variant="h4">Review Queue</Typography>
        <Tooltip title="Refresh">
          <IconButton onClick={() => void fetchItems()} aria-label="Refresh review items">
            <RefreshIcon />
          </IconButton>
        </Tooltip>
      </Box>

      {actionError && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setActionError(null)}>
          {actionError}
        </Alert>
      )}

      <Box sx={{ mb: 2, display: 'flex', gap: 2, alignItems: 'center' }}>
        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel>Status</InputLabel>
          <Select value={statusFilter} label="Status" onChange={handleStatusFilterChange}>
            <MenuItem value="all">All</MenuItem>
            {STATUS_OPTIONS.map((s) => (
              <MenuItem key={s} value={s}>
                {s.charAt(0).toUpperCase() + s.slice(1)}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        {currentProject && (
          <Chip size="small" variant="outlined" label={`Project: ${currentProject.name}`} />
        )}
      </Box>

      {items.length === 0 ? (
        <EmptyState
          icon={<SearchOffIcon />}
          title="No review items"
          description={
            statusFilter === 'all'
              ? 'Nothing is queued for manual review in this project. Items land here when a traceability rule with a "queue for review" action flags an artifact.'
              : `No ${statusFilter} review items. Try the "All" status filter, or switch project in the header.`
          }
        />
      ) : (
        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Artifact</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Priority</TableCell>
                <TableCell>Reason</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {items.map((item) => {
                const externalId =
                  item.meta && typeof item.meta.external_id === 'string'
                    ? item.meta.external_id
                    : `#${item.artifact_id}`;
                const isOpen = item.status === 'pending' || item.status === 'claimed';
                return (
                  <TableRow key={item.id} data-testid={`review-row-${item.id}`}>
                    <TableCell>{externalId}</TableCell>
                    <TableCell>
                      <Chip label={item.status} color={statusColor(item.status)} size="small" />
                    </TableCell>
                    <TableCell>{item.priority}</TableCell>
                    <TableCell>{item.reason ?? '—'}</TableCell>
                    <TableCell align="right">
                      {item.status === 'pending' && (
                        <Button
                          size="small"
                          disabled={busyId === item.id}
                          onClick={() => void runAction(item.id, () => claimReviewItem(item.id))}
                        >
                          Claim
                        </Button>
                      )}
                      <Button
                        size="small"
                        color="success"
                        disabled={!isOpen || busyId === item.id}
                        onClick={() => void runAction(item.id, () => resolveReviewItem(item.id))}
                      >
                        Resolve
                      </Button>
                      <Button
                        size="small"
                        color="error"
                        disabled={!isOpen || busyId === item.id}
                        onClick={() => void runAction(item.id, () => rejectReviewItem(item.id))}
                      >
                        Reject
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <Typography variant="caption" sx={{ mt: 2, display: 'block' }}>
        {total} item(s) total
      </Typography>
    </Box>
  );
};

export default ReviewQueue;
