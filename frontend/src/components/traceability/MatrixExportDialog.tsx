/**
 * MatrixExportDialog - Dialog for exporting traceability matrix data.
 * Supports xlsx, csv, and pdf formats with progress tracking.
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  InputLabel,
  LinearProgress,
  MenuItem,
  Select,
  Stack,
  Switch,
  Typography,
} from '@mui/material';
import type { SelectChangeEvent } from '@mui/material/Select';
import DownloadIcon from '@mui/icons-material/Download';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';

import {
  createMatrixExport,
  getExportStatus,
  getExportDownloadUrl,
  ExportFormat,
  ExportTaskStatus,
  RTMExportFilters,
} from '../../services/api';

interface MatrixExportDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: number;
  projectName?: string;
  /** Optional filters to apply to the export (from current matrix view) */
  filters?: RTMExportFilters;
  /** Optional saved matrix config ID to use */
  matrixConfigId?: number;
}

const POLL_INTERVAL_MS = 1500;

const MatrixExportDialog: React.FC<MatrixExportDialogProps> = ({
  open,
  onClose,
  projectId,
  projectName,
  filters,
  matrixConfigId,
}) => {
  const [format, setFormat] = useState<ExportFormat>('xlsx');
  const [includeDetails, setIncludeDetails] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [exportTask, setExportTask] = useState<ExportTaskStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Reset state when dialog opens
  useEffect(() => {
    if (open) {
      setExportTask(null);
      setError(null);
      setIsSubmitting(false);
    }
  }, [open]);

  // Poll for export status while processing
  useEffect(() => {
    if (!exportTask || exportTask.status === 'completed' || exportTask.status === 'failed') {
      return;
    }

    const pollStatus = async () => {
      try {
        const status = await getExportStatus(exportTask.task_id);
        setExportTask(status);
      } catch (err) {
        console.error('Error polling export status:', err);
      }
    };

    const interval = setInterval(pollStatus, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [exportTask]);

  const handleFormatChange = useCallback((event: SelectChangeEvent<ExportFormat>) => {
    setFormat(event.target.value as ExportFormat);
  }, []);

  const handleSubmit = useCallback(async () => {
    setIsSubmitting(true);
    setError(null);

    try {
      const task = await createMatrixExport({
        project_id: projectId,
        format,
        include_details: includeDetails,
        filters,
        matrix_config_id: matrixConfigId,
      });
      setExportTask(task);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to start export';
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  }, [projectId, format, includeDetails, filters, matrixConfigId]);

  const handleDownload = useCallback(() => {
    if (!exportTask?.task_id) return;

    const url = getExportDownloadUrl(exportTask.task_id);
    window.open(url, '_blank');
  }, [exportTask]);

  const handleClose = useCallback(() => {
    // Only close if not in the middle of processing
    if (exportTask?.status === 'processing' || exportTask?.status === 'pending') {
      return;
    }
    onClose();
  }, [exportTask, onClose]);

  const renderContent = () => {
    // Show export result if we have a completed/failed task
    if (exportTask) {
      if (exportTask.status === 'completed') {
        return (
          <Stack spacing={2} alignItems="center" sx={{ py: 2 }}>
            <CheckCircleIcon color="success" sx={{ fontSize: 48 }} />
            <Typography variant="h6">Export Complete!</Typography>
            <Typography color="text.secondary">
              Your file is ready for download.
            </Typography>
            <Button
              variant="contained"
              startIcon={<DownloadIcon />}
              onClick={handleDownload}
              size="large"
            >
              Download {format.toUpperCase()}
            </Button>
          </Stack>
        );
      }

      if (exportTask.status === 'failed') {
        return (
          <Stack spacing={2} alignItems="center" sx={{ py: 2 }}>
            <ErrorIcon color="error" sx={{ fontSize: 48 }} />
            <Typography variant="h6">Export Failed</Typography>
            <Alert severity="error" sx={{ width: '100%' }}>
              {exportTask.error_message || 'An unexpected error occurred'}
            </Alert>
            <Button variant="outlined" onClick={() => setExportTask(null)}>
              Try Again
            </Button>
          </Stack>
        );
      }

      // Processing state
      return (
        <Stack spacing={2} alignItems="center" sx={{ py: 3 }}>
          <CircularProgress size={48} />
          <Typography variant="h6">
            {exportTask.status === 'pending' ? 'Starting export...' : 'Generating export...'}
          </Typography>
          <Box sx={{ width: '100%' }}>
            <LinearProgress
              variant="determinate"
              value={exportTask.progress_pct}
              sx={{ height: 8, borderRadius: 4 }}
            />
            <Typography variant="caption" color="text.secondary" sx={{ mt: 1 }}>
              {Math.round(exportTask.progress_pct)}% complete
            </Typography>
          </Box>
          <Typography variant="body2" color="text.secondary">
            Please wait while we prepare your file...
          </Typography>
        </Stack>
      );
    }

    // Initial form
    return (
      <Stack spacing={3}>
        {error && (
          <Alert severity="error" onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        <Typography variant="body2" color="text.secondary">
          Export the traceability matrix data for{' '}
          <strong>{projectName || `Project #${projectId}`}</strong>.
        </Typography>

        <FormControl fullWidth>
          <InputLabel id="format-label">Export Format</InputLabel>
          <Select
            labelId="format-label"
            value={format}
            label="Export Format"
            onChange={handleFormatChange}
          >
            <MenuItem value="xlsx">
              <Stack direction="row" spacing={1} alignItems="center">
                <span>Excel (.xlsx)</span>
                <Typography variant="caption" color="text.secondary">
                  - Multiple sheets with formatting
                </Typography>
              </Stack>
            </MenuItem>
            <MenuItem value="csv">
              <Stack direction="row" spacing={1} alignItems="center">
                <span>CSV (.csv)</span>
                <Typography variant="caption" color="text.secondary">
                  - Simple text format
                </Typography>
              </Stack>
            </MenuItem>
            <MenuItem value="pdf">
              <Stack direction="row" spacing={1} alignItems="center">
                <span>PDF (.pdf)</span>
                <Typography variant="caption" color="text.secondary">
                  - Printable document
                </Typography>
              </Stack>
            </MenuItem>
          </Select>
        </FormControl>

        <FormControlLabel
          control={
            <Switch
              checked={includeDetails}
              onChange={(e) => setIncludeDetails(e.target.checked)}
            />
          }
          label={
            <Stack>
              <Typography>Include link details</Typography>
              <Typography variant="caption" color="text.secondary">
                Add columns for link types and confidence scores
              </Typography>
            </Stack>
          }
        />
      </Stack>
    );
  };

  const isProcessing = exportTask?.status === 'processing' || exportTask?.status === 'pending';
  const isComplete = exportTask?.status === 'completed';

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      maxWidth="sm"
      fullWidth
      disableEscapeKeyDown={isProcessing}
    >
      <DialogTitle>Export Traceability Matrix</DialogTitle>
      <DialogContent>{renderContent()}</DialogContent>
      <DialogActions>
        {!exportTask && (
          <>
            <Button onClick={onClose} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button
              variant="contained"
              onClick={handleSubmit}
              disabled={isSubmitting}
              startIcon={isSubmitting ? <CircularProgress size={16} /> : <DownloadIcon />}
            >
              {isSubmitting ? 'Starting...' : 'Export'}
            </Button>
          </>
        )}
        {isComplete && (
          <Button onClick={onClose}>Close</Button>
        )}
      </DialogActions>
    </Dialog>
  );
};

export default MatrixExportDialog;
