import React, { useEffect, useState } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Box,
  Typography,
  LinearProgress,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import ErrorIcon from '@mui/icons-material/Error';

interface SyncStep {
  id: string;
  label: string;
  status: 'pending' | 'in_progress' | 'completed' | 'error';
  count?: number;
  total?: number;
  error?: string;
}

interface SyncProgressDialogProps {
  open: boolean;
  onClose: () => void;
  onCancel?: () => void;
  title?: string;
  steps: SyncStep[];
  estimatedTimeSeconds?: number;
}

const SyncProgressDialogComponent: React.FC<SyncProgressDialogProps> = ({
  open,
  onClose,
  onCancel,
  title = 'Syncing Data',
  steps,
  estimatedTimeSeconds,
}) => {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  useEffect(() => {
    if (!open) {
      setElapsedSeconds(0);
      return;
    }

    const interval = setInterval(() => {
      setElapsedSeconds((prev) => prev + 1);
    }, 1000);

    return () => clearInterval(interval);
  }, [open]);

  const completedSteps = steps.filter((s) => s.status === 'completed').length;
  const totalSteps = steps.length;
  const progress = totalSteps > 0 ? (completedSteps / totalSteps) * 100 : 0;

  const allCompleted = completedSteps === totalSteps;
  const hasError = steps.some((s) => s.status === 'error');

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
  };

  const remainingTime = estimatedTimeSeconds
    ? Math.max(0, estimatedTimeSeconds - elapsedSeconds)
    : null;

  const getStepIcon = (step: SyncStep) => {
    switch (step.status) {
      case 'completed':
        return <CheckCircleIcon color="success" />;
      case 'error':
        return <ErrorIcon color="error" />;
      case 'in_progress':
        return <HourglassEmptyIcon color="primary" />;
      default:
        return <HourglassEmptyIcon color="disabled" />;
    }
  };

  const getStepText = (step: SyncStep) => {
    if (step.status === 'error') {
      return step.error || 'Failed';
    }
    if (step.status === 'in_progress' && step.count !== undefined && step.total !== undefined) {
      return `${step.count} / ${step.total}`;
    }
    if (step.status === 'completed' && step.count !== undefined) {
      return `Processed ${step.count} items`;
    }
    return '';
  };

  return (
    <Dialog open={open} onClose={allCompleted || hasError ? onClose : undefined} maxWidth="sm" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <Box mb={3}>
          <Box display="flex" justifyContent="space-between" alignItems="center" mb={1}>
            <Typography variant="body2" color="text.secondary">
              Progress: {completedSteps} / {totalSteps} steps
            </Typography>
            {remainingTime !== null && remainingTime > 0 && (
              <Typography variant="body2" color="text.secondary">
                ~{formatTime(remainingTime)} remaining
              </Typography>
            )}
          </Box>
          <LinearProgress
            variant="determinate"
            value={progress}
            sx={{
              height: 8,
              borderRadius: 4,
              bgcolor: 'action.hover',
            }}
          />
          <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
            Elapsed: {formatTime(elapsedSeconds)}
          </Typography>
        </Box>

        <List dense>
          {steps.map((step) => (
            <ListItem
              key={step.id}
              sx={{
                bgcolor: step.status === 'in_progress' ? 'action.hover' : 'transparent',
                borderRadius: 1,
                mb: 0.5,
              }}
            >
              <ListItemIcon>{getStepIcon(step)}</ListItemIcon>
              <ListItemText
                primary={step.label}
                secondary={getStepText(step)}
                primaryTypographyProps={{
                  fontWeight: step.status === 'in_progress' ? 600 : 400,
                }}
              />
            </ListItem>
          ))}
        </List>

        {allCompleted && (
          <Box mt={2} p={2} bgcolor="success.light" borderRadius={1}>
            <Typography variant="body2" color="success.dark" fontWeight={600}>
              ✓ Sync completed successfully!
            </Typography>
          </Box>
        )}

        {hasError && (
          <Box mt={2} p={2} bgcolor="error.light" borderRadius={1}>
            <Typography variant="body2" color="error.dark" fontWeight={600}>
              ✗ Sync encountered errors
            </Typography>
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        {!allCompleted && !hasError && onCancel && (
          <Button onClick={onCancel} color="error">
            Cancel
          </Button>
        )}
        {(allCompleted || hasError) && (
          <Button onClick={onClose} variant="contained">
            Close
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
};

SyncProgressDialogComponent.displayName = 'SyncProgressDialog';

export const SyncProgressDialog = React.memo(SyncProgressDialogComponent);
