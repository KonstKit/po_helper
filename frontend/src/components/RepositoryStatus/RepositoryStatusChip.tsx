import React from 'react';
import { Chip, Tooltip, CircularProgress, Box } from '@mui/material';
import {
  CheckCircle as CheckCircleIcon,
  Error as ErrorIcon,
  Sync as SyncIcon,
  Schedule as ScheduleIcon,
} from '@mui/icons-material';

export interface RepositoryStatus {
  state: 'connected' | 'syncing' | 'error' | 'pending';
  lastSync?: Date | string;
  error?: string;
}

interface RepositoryStatusChipProps {
  status: RepositoryStatus;
  size?: 'small' | 'medium';
  showLabel?: boolean;
}

const RepositoryStatusChip: React.FC<RepositoryStatusChipProps> = ({
  status,
  size = 'small',
  showLabel = true,
}) => {
  const getStatusConfig = () => {
    const now = new Date();
    const lastSyncDate = status.lastSync ? new Date(status.lastSync) : null;
    const minutesAgo = lastSyncDate
      ? Math.floor((now.getTime() - lastSyncDate.getTime()) / (1000 * 60))
      : null;

    switch (status.state) {
      case 'connected':
        if (minutesAgo !== null && minutesAgo < 5) {
          return {
            color: 'success' as const,
            icon: <CheckCircleIcon fontSize="small" />,
            label: showLabel ? 'Synced' : '',
            tooltip: `Last synced ${minutesAgo} minute${minutesAgo !== 1 ? 's' : ''} ago`,
          };
        } else if (minutesAgo !== null && minutesAgo < 60) {
          return {
            color: 'warning' as const,
            icon: <ScheduleIcon fontSize="small" />,
            label: showLabel ? 'Stale' : '',
            tooltip: `Last synced ${minutesAgo} minutes ago`,
          };
        } else {
          return {
            color: 'default' as const,
            icon: <ScheduleIcon fontSize="small" />,
            label: showLabel ? 'Outdated' : '',
            tooltip: lastSyncDate
              ? `Last synced ${new Date(lastSyncDate).toLocaleString()}`
              : 'Never synced',
          };
        }

      case 'syncing':
        return {
          color: 'primary' as const,
          icon: (
            <Box display="inline-flex" alignItems="center">
              <CircularProgress size={16} thickness={4} />
            </Box>
          ),
          label: showLabel ? 'Syncing...' : '',
          tooltip: 'Synchronizing repository data',
        };

      case 'error':
        return {
          color: 'error' as const,
          icon: <ErrorIcon fontSize="small" />,
          label: showLabel ? 'Error' : '',
          tooltip: status.error || 'Connection error',
        };

      case 'pending':
      default:
        return {
          color: 'default' as const,
          icon: <SyncIcon fontSize="small" />,
          label: showLabel ? 'Not synced' : '',
          tooltip: 'Repository not yet synchronized',
        };
    }
  };

  const config = getStatusConfig();

  return (
    <Tooltip title={config.tooltip}>
      <Chip
        size={size}
        color={config.color}
        icon={config.icon}
        label={config.label}
        sx={{
          '& .MuiChip-icon': {
            ml: showLabel ? 0.5 : 0,
          },
          minWidth: showLabel ? 'auto' : 32,
        }}
      />
    </Tooltip>
  );
};

export default RepositoryStatusChip;