import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Paper,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  IconButton,
  Button,
  Chip,
  Tooltip,
  LinearProgress,
  Alert,
  Stack,
  Card,
  CardContent,
  Checkbox,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Slider,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Skeleton,
} from '@mui/material';
import type { SelectChangeEvent } from '@mui/material/Select';
import {
  Check as ApproveIcon,
  Close as RejectIcon,
  Refresh as RefreshIcon,
  AutoAwesome as GenerateIcon,
  Link as LinkIcon,
  ArrowForward as ArrowIcon,
} from '@mui/icons-material';
import {
  SuggestedLink,
  SuggestedLinksStats,
  getSuggestedLinks,
  getSuggestedLinksStats,
  generateSuggestedLinks,
  approveSuggestedLink,
  rejectSuggestedLink,
  bulkApproveSuggestedLinks,
} from '../services/api';
import { getErrorMessage } from '../utils/errorUtils';

interface SuggestedLinksPanelProps {
  projectId?: number;
  onLinkCreated?: () => void;
}

const ARTIFACT_TYPE_COLORS: Record<string, string> = {
  requirement: '#1976d2',
  jira_issue: '#0052cc',
  commit: '#6f42c1',
  pr: '#238636',
  test_case: '#d73a49',
  confluence_page: '#ff9800',
};

const formatArtifactType = (type: string) => {
  return type
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
};

const SimilarityBar: React.FC<{ score: number }> = ({ score }) => {
  const percentage = Math.round(score * 100);
  const color = score >= 0.7 ? 'success' : score >= 0.5 ? 'warning' : 'error';

  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 120 }}>
      <LinearProgress
        variant="determinate"
        value={percentage}
        color={color}
        sx={{ flex: 1, height: 8, borderRadius: 4 }}
      />
      <Typography variant="body2" color="text.secondary" sx={{ minWidth: 40 }}>
        {percentage}%
      </Typography>
    </Box>
  );
};

export default function SuggestedLinksPanel({ projectId, onLinkCreated }: SuggestedLinksPanelProps) {
  const [suggestions, setSuggestions] = useState<SuggestedLink[]>([]);
  const [stats, setStats] = useState<SuggestedLinksStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [minScoreFilter, setMinScoreFilter] = useState(0.3);
  const [statusFilter, setStatusFilter] = useState<string>('pending');

  // Dialog states
  const [noteDialogOpen, setNoteDialogOpen] = useState(false);
  const [noteDialogAction, setNoteDialogAction] = useState<'approve' | 'reject'>('approve');
  const [noteDialogSuggestionId, setNoteDialogSuggestionId] = useState<number | null>(null);
  const [reviewNote, setReviewNote] = useState('');

  const handleStatusChange = (event: SelectChangeEvent) => {
    setStatusFilter(event.target.value);
  };

  const handleMinScoreChange = (_: Event, value: number | number[]) => {
    if (!Array.isArray(value)) {
      setMinScoreFilter(value);
    }
  };

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [suggestionsRes, statsRes] = await Promise.all([
        getSuggestedLinks({
          projectId,
          status: statusFilter || undefined,
          minScore: minScoreFilter,
          limit: 100,
        }),
        getSuggestedLinksStats({ projectId }),
      ]);
      setSuggestions(suggestionsRes.data);
      setStats(statsRes);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to load suggestions'));
    } finally {
      setLoading(false);
    }
  }, [projectId, statusFilter, minScoreFilter]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    try {
      await generateSuggestedLinks({
        projectId,
        minSimilarity: minScoreFilter,
      });
      // Reload after generation
      await loadData();
      setError(null);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to generate suggestions'));
    } finally {
      setGenerating(false);
    }
  };

  const handleApprove = async (suggestionId: number, note?: string) => {
    try {
      await approveSuggestedLink(suggestionId, note);
      await loadData();
      onLinkCreated?.();
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to approve suggestion'));
    }
  };

  const handleReject = async (suggestionId: number, note?: string) => {
    try {
      await rejectSuggestedLink(suggestionId, note);
      await loadData();
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to reject suggestion'));
    }
  };

  const handleBulkApprove = async () => {
    if (selectedIds.size === 0) return;
    try {
      await bulkApproveSuggestedLinks(Array.from(selectedIds));
      setSelectedIds(new Set());
      await loadData();
      onLinkCreated?.();
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to bulk approve'));
    }
  };

  const openNoteDialog = (action: 'approve' | 'reject', suggestionId: number) => {
    setNoteDialogAction(action);
    setNoteDialogSuggestionId(suggestionId);
    setReviewNote('');
    setNoteDialogOpen(true);
  };

  const handleNoteDialogConfirm = async () => {
    if (noteDialogSuggestionId === null) return;
    if (noteDialogAction === 'approve') {
      await handleApprove(noteDialogSuggestionId, reviewNote || undefined);
    } else {
      await handleReject(noteDialogSuggestionId, reviewNote || undefined);
    }
    setNoteDialogOpen(false);
  };

  const toggleSelection = (id: number) => {
    const newSelected = new Set(selectedIds);
    if (newSelected.has(id)) {
      newSelected.delete(id);
    } else {
      newSelected.add(id);
    }
    setSelectedIds(newSelected);
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === suggestions.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(suggestions.map((s) => s.id)));
    }
  };

  const pendingSuggestions = suggestions.filter((s) => s.status === 'pending');
  const highConfidencePending = pendingSuggestions.filter((s) => s.similarity_score >= 0.7);

  return (
    <Box>
      {/* Stats Cards */}
      {stats && (
        <Stack direction="row" spacing={2} sx={{ mb: 3 }} flexWrap="wrap" useFlexGap>
          <Card sx={{ minWidth: 140 }}>
            <CardContent sx={{ py: 1.5, '&:last-child': { pb: 1.5 } }}>
              <Typography color="text.secondary" variant="caption">
                Pending Review
              </Typography>
              <Typography variant="h5" color="warning.main">
                {stats.total_pending}
              </Typography>
            </CardContent>
          </Card>
          <Card sx={{ minWidth: 140 }}>
            <CardContent sx={{ py: 1.5, '&:last-child': { pb: 1.5 } }}>
              <Typography color="text.secondary" variant="caption">
                Approved
              </Typography>
              <Typography variant="h5" color="success.main">
                {stats.total_approved}
              </Typography>
            </CardContent>
          </Card>
          <Card sx={{ minWidth: 140 }}>
            <CardContent sx={{ py: 1.5, '&:last-child': { pb: 1.5 } }}>
              <Typography color="text.secondary" variant="caption">
                Rejected
              </Typography>
              <Typography variant="h5" color="error.main">
                {stats.total_rejected}
              </Typography>
            </CardContent>
          </Card>
          <Card sx={{ minWidth: 140 }}>
            <CardContent sx={{ py: 1.5, '&:last-child': { pb: 1.5 } }}>
              <Typography color="text.secondary" variant="caption">
                Avg Similarity
              </Typography>
              <Typography variant="h5">
                {Math.round(stats.avg_similarity_score * 100)}%
              </Typography>
            </CardContent>
          </Card>
        </Stack>
      )}

      {/* Actions Bar */}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
          <Button
            variant="contained"
            startIcon={<GenerateIcon />}
            onClick={handleGenerate}
            disabled={generating}
          >
            {generating ? 'Generating...' : 'Generate Suggestions'}
          </Button>

          <Button
            variant="outlined"
            startIcon={<RefreshIcon />}
            onClick={loadData}
            disabled={loading}
          >
            Refresh
          </Button>

          {selectedIds.size > 0 && (
            <Button
              variant="contained"
              color="success"
              startIcon={<ApproveIcon />}
              onClick={handleBulkApprove}
            >
              Approve Selected ({selectedIds.size})
            </Button>
          )}

          {highConfidencePending.length > 0 && (
            <Tooltip title={`Auto-approve ${highConfidencePending.length} suggestions with 70%+ similarity`}>
              <Button
                variant="outlined"
                color="success"
                onClick={() => {
                  setSelectedIds(new Set(highConfidencePending.map((s) => s.id)));
                }}
              >
                Select High Confidence ({highConfidencePending.length})
              </Button>
            </Tooltip>
          )}

          <Box sx={{ flexGrow: 1 }} />

          {/* Filters */}
          <FormControl size="small" sx={{ minWidth: 120 }}>
            <InputLabel>Status</InputLabel>
            <Select
              value={statusFilter}
              label="Status"
              onChange={handleStatusChange}
            >
              <MenuItem value="">All</MenuItem>
              <MenuItem value="pending">Pending</MenuItem>
              <MenuItem value="approved">Approved</MenuItem>
              <MenuItem value="rejected">Rejected</MenuItem>
            </Select>
          </FormControl>

          <Box sx={{ width: 200 }}>
            <Typography variant="caption" color="text.secondary">
              Min Similarity: {Math.round(minScoreFilter * 100)}%
            </Typography>
            <Slider
              size="small"
              value={minScoreFilter}
              onChange={handleMinScoreChange}
              onChangeCommitted={() => loadData()}
              min={0}
              max={1}
              step={0.1}
              marks={[
                { value: 0.3, label: '30%' },
                { value: 0.7, label: '70%' },
              ]}
            />
          </Box>
        </Stack>
      </Paper>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Suggestions Table */}
      <TableContainer component={Paper}>
        {loading && <LinearProgress />}
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell padding="checkbox">
                <Checkbox
                  indeterminate={selectedIds.size > 0 && selectedIds.size < suggestions.length}
                  checked={selectedIds.size === suggestions.length && suggestions.length > 0}
                  onChange={toggleSelectAll}
                />
              </TableCell>
              <TableCell>From</TableCell>
              <TableCell></TableCell>
              <TableCell>To</TableCell>
              <TableCell>Link Type</TableCell>
              <TableCell>Similarity</TableCell>
              <TableCell>Method</TableCell>
              <TableCell>Status</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {loading ? (
              // Skeleton loading
              Array.from({ length: 5 }).map((_, idx) => (
                <TableRow key={idx}>
                  <TableCell padding="checkbox">
                    <Skeleton variant="rectangular" width={24} height={24} />
                  </TableCell>
                  <TableCell><Skeleton width={150} /></TableCell>
                  <TableCell><Skeleton width={24} /></TableCell>
                  <TableCell><Skeleton width={150} /></TableCell>
                  <TableCell><Skeleton width={80} /></TableCell>
                  <TableCell><Skeleton width={120} /></TableCell>
                  <TableCell><Skeleton width={60} /></TableCell>
                  <TableCell><Skeleton width={70} /></TableCell>
                  <TableCell><Skeleton width={80} /></TableCell>
                </TableRow>
              ))
            ) : suggestions.length === 0 ? (
              <TableRow>
                <TableCell colSpan={9} align="center" sx={{ py: 4 }}>
                  <Typography color="text.secondary">
                    No suggestions found. Click &quot;Generate Suggestions&quot; to analyze artifacts.
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              suggestions.map((suggestion) => (
                <TableRow
                  key={suggestion.id}
                  hover
                  selected={selectedIds.has(suggestion.id)}
                  sx={{ opacity: suggestion.status !== 'pending' ? 0.6 : 1 }}
                >
                  <TableCell padding="checkbox">
                    <Checkbox
                      checked={selectedIds.has(suggestion.id)}
                      onChange={() => toggleSelection(suggestion.id)}
                      disabled={suggestion.status !== 'pending'}
                    />
                  </TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={1} alignItems="center">
                      <Chip
                        label={formatArtifactType(suggestion.from_artifact?.type || 'unknown')}
                        size="small"
                        sx={{
                          bgcolor: ARTIFACT_TYPE_COLORS[suggestion.from_artifact?.type || ''] || '#757575',
                          color: 'white',
                          fontSize: '0.7rem',
                        }}
                      />
                      <Tooltip title={suggestion.from_artifact?.title || ''}>
                        <Typography variant="body2" noWrap sx={{ maxWidth: 150 }}>
                          {suggestion.from_artifact?.display_key || suggestion.from_artifact?.external_id}
                        </Typography>
                      </Tooltip>
                    </Stack>
                  </TableCell>
                  <TableCell>
                    <ArrowIcon color="action" fontSize="small" />
                  </TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={1} alignItems="center">
                      <Chip
                        label={formatArtifactType(suggestion.to_artifact?.type || 'unknown')}
                        size="small"
                        sx={{
                          bgcolor: ARTIFACT_TYPE_COLORS[suggestion.to_artifact?.type || ''] || '#757575',
                          color: 'white',
                          fontSize: '0.7rem',
                        }}
                      />
                      <Tooltip title={suggestion.to_artifact?.title || ''}>
                        <Typography variant="body2" noWrap sx={{ maxWidth: 150 }}>
                          {suggestion.to_artifact?.display_key || suggestion.to_artifact?.external_id}
                        </Typography>
                      </Tooltip>
                    </Stack>
                  </TableCell>
                  <TableCell>
                    <Chip
                      icon={<LinkIcon />}
                      label={suggestion.suggested_link_type}
                      size="small"
                      variant="outlined"
                    />
                  </TableCell>
                  <TableCell>
                    <SimilarityBar score={suggestion.similarity_score} />
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={suggestion.method.toUpperCase()}
                      size="small"
                      variant="outlined"
                      color="info"
                    />
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={suggestion.status}
                      size="small"
                      color={
                        suggestion.status === 'approved'
                          ? 'success'
                          : suggestion.status === 'rejected'
                          ? 'error'
                          : 'warning'
                      }
                    />
                  </TableCell>
                  <TableCell align="right">
                    {suggestion.status === 'pending' && (
                      <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                        <Tooltip title="Approve">
                          <IconButton
                            size="small"
                            color="success"
                            onClick={() => openNoteDialog('approve', suggestion.id)}
                          >
                            <ApproveIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        <Tooltip title="Reject">
                          <IconButton
                            size="small"
                            color="error"
                            onClick={() => openNoteDialog('reject', suggestion.id)}
                          >
                            <RejectIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      </Stack>
                    )}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Note Dialog */}
      <Dialog open={noteDialogOpen} onClose={() => setNoteDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>
          {noteDialogAction === 'approve' ? 'Approve Suggestion' : 'Reject Suggestion'}
        </DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            margin="dense"
            label="Review Note (optional)"
            fullWidth
            multiline
            rows={3}
            value={reviewNote}
            onChange={(e) => setReviewNote(e.target.value)}
            placeholder="Add a note explaining your decision..."
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setNoteDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleNoteDialogConfirm}
            variant="contained"
            color={noteDialogAction === 'approve' ? 'success' : 'error'}
          >
            {noteDialogAction === 'approve' ? 'Approve' : 'Reject'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
