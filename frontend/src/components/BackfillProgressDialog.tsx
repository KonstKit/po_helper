import React, { useEffect, useState } from 'react';
import {
  Box,
  Dialog,
  DialogContent,
  DialogTitle,
  LinearProgress,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Typography,
} from '@mui/material';
import {
  CheckCircle as CheckCircleIcon,
  HourglassEmpty as HourglassIcon,
  Circle as CircleIcon,
} from '@mui/icons-material';

export interface BackfillStep {
  id: string;
  label: string;
  status: 'pending' | 'in_progress' | 'completed';
  count?: number; // e.g., number of artifacts processed
  total?: number; // e.g., total artifacts to process
}

export interface BackfillProgressDialogProps {
  open: boolean;
  steps: BackfillStep[];
  onClose?: () => void;
}

/**
 * Progress dialog for traceability backfill operations.
 * Shows multi-step progress with visual status indicators.
 */
const BackfillProgressDialog: React.FC<BackfillProgressDialogProps> = ({
  open,
  steps,
  onClose,
}) => {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  // Track elapsed time
  useEffect(() => {
    if (!open) return;
    const startedAt = Date.now();
    const resetId = setTimeout(() => setElapsedSeconds(0), 0);
    const interval = setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);

    return () => {
      clearTimeout(resetId);
      clearInterval(interval);
    };
  }, [open]);

  // Calculate overall progress
  const completedSteps = steps.filter((s) => s.status === 'completed').length;
  const totalSteps = steps.length;
  const overallProgress = totalSteps > 0 ? (completedSteps / totalSteps) * 100 : 0;

  // Format elapsed time
  const formatTime = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    if (mins > 0) {
      return `${mins}m ${secs}s`;
    }
    return `${secs}s`;
  };

  // Get step icon based on status
  const getStepIcon = (status: BackfillStep['status']) => {
    switch (status) {
      case 'completed':
        return <CheckCircleIcon sx={{ color: 'success.main' }} />;
      case 'in_progress':
        return <HourglassIcon sx={{ color: 'primary.main' }} />;
      case 'pending':
      default:
        return <CircleIcon sx={{ color: 'text.disabled', fontSize: 16 }} />;
    }
  };

  // Get step text based on status and counts
  const getStepText = (step: BackfillStep): string => {
    if (step.status === 'completed') {
      if (step.total !== undefined) {
        return `✓ ${step.label} (${step.total} processed)`;
      }
      return `✓ ${step.label}`;
    }

    if (step.status === 'in_progress') {
      if (step.count !== undefined && step.total !== undefined) {
        return `⏳ ${step.label} (${step.count}/${step.total})...`;
      }
      return `⏳ ${step.label}...`;
    }

    return step.label;
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="sm"
      fullWidth
      disableEscapeKeyDown={!onClose} // Prevent closing if no onClose handler
    >
      <DialogTitle>
        <Box display="flex" alignItems="center" justifyContent="space-between">
          <Typography variant="h6" component="span" fontWeight={600}>
            Analyzing Artifacts
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {formatTime(elapsedSeconds)}
          </Typography>
        </Box>
      </DialogTitle>

      <DialogContent>
        {/* Overall Progress */}
        <Box mb={3}>
          <Box display="flex" justifyContent="space-between" mb={1}>
            <Typography variant="body2" color="text.secondary">
              Overall Progress
            </Typography>
            <Typography variant="body2" fontWeight={600}>
              {completedSteps} / {totalSteps} steps
            </Typography>
          </Box>
          <LinearProgress
            variant="determinate"
            value={overallProgress}
            sx={{
              height: 8,
              borderRadius: 4,
              backgroundColor: 'rgba(0, 0, 0, 0.1)',
              '& .MuiLinearProgress-bar': {
                borderRadius: 4,
                backgroundColor: 'success.main',
              },
            }}
          />
        </Box>

        {/* Step List */}
        <List disablePadding>
          {steps.map((step, index) => (
            <ListItem
              key={step.id}
              sx={{
                py: 1.5,
                px: 0,
                borderBottom:
                  index < steps.length - 1 ? '1px solid rgba(0, 0, 0, 0.08)' : 'none',
              }}
            >
              <ListItemIcon sx={{ minWidth: 40 }}>
                {getStepIcon(step.status)}
              </ListItemIcon>
              <ListItemText
                primary={
                  <Typography
                    variant="body2"
                    fontWeight={step.status === 'in_progress' ? 600 : 400}
                    color={
                      step.status === 'completed'
                        ? 'success.main'
                        : step.status === 'in_progress'
                        ? 'primary.main'
                        : 'text.secondary'
                    }
                  >
                    {getStepText(step)}
                  </Typography>
                }
                secondary={
                  step.status === 'in_progress' && step.count !== undefined && step.total !== undefined && (
                    <LinearProgress
                      variant="determinate"
                      value={(step.count / step.total) * 100}
                      sx={{ mt: 1, height: 4, borderRadius: 2 }}
                    />
                  )
                }
              />
            </ListItem>
          ))}
        </List>

        {/* Bottom Info */}
        <Box mt={3} p={2} bgcolor="rgba(0, 0, 0, 0.02)" borderRadius={1}>
          <Typography variant="caption" color="text.secondary" display="block">
            💡 This process analyzes Jira issues, Confluence pages, and Git commits to build
            traceability links. Large projects may take several minutes.
          </Typography>
        </Box>
      </DialogContent>
    </Dialog>
  );
};

BackfillProgressDialog.displayName = 'BackfillProgressDialog';

export default React.memo(BackfillProgressDialog);
