import React, { useState } from 'react';
import {
  Button,
  IconButton,
  Tooltip,
  CircularProgress,
  Menu,
  MenuItem,
  ListItemIcon,
  ListItemText,
} from '@mui/material';
import {
  Sync as SyncIcon,
  Refresh as RefreshIcon,
  Code as CodeIcon,
  PullRequest as PullRequestIcon,
  MoreVert as MoreVertIcon,
} from '@mui/icons-material';

interface RepositorySyncButtonProps {
  repositoryId: number;
  onSync: (options: SyncOptions) => Promise<void>;
  variant?: 'button' | 'icon' | 'menu';
  size?: 'small' | 'medium' | 'large';
  disabled?: boolean;
}

export interface SyncOptions {
  includeCommits: boolean;
  includePullRequests: boolean;
  forceRefresh?: boolean;
}

const RepositorySyncButton: React.FC<RepositorySyncButtonProps> = ({
  repositoryId,
  onSync,
  variant = 'button',
  size = 'small',
  disabled = false,
}) => {
  const [syncing, setSyncing] = useState(false);
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);

  const handleSync = async (options?: Partial<SyncOptions>) => {
    const syncOptions: SyncOptions = {
      includeCommits: true,
      includePullRequests: true,
      forceRefresh: false,
      ...options,
    };

    setSyncing(true);
    setAnchorEl(null);
    try {
      await onSync(syncOptions);
    } finally {
      setSyncing(false);
    }
  };

  const handleMenuClick = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget);
  };

  const handleMenuClose = () => {
    setAnchorEl(null);
  };

  if (variant === 'icon') {
    return (
      <Tooltip title="Sync repository">
        <span>
          <IconButton
            size={size}
            onClick={() => handleSync()}
            disabled={disabled || syncing}
          >
            {syncing ? (
              <CircularProgress size={20} />
            ) : (
              <SyncIcon />
            )}
          </IconButton>
        </span>
      </Tooltip>
    );
  }

  if (variant === 'menu') {
    return (
      <>
        <Tooltip title="Sync options">
          <IconButton
            size={size}
            onClick={handleMenuClick}
            disabled={disabled || syncing}
          >
            {syncing ? (
              <CircularProgress size={20} />
            ) : (
              <MoreVertIcon />
            )}
          </IconButton>
        </Tooltip>
        <Menu
          anchorEl={anchorEl}
          open={Boolean(anchorEl)}
          onClose={handleMenuClose}
        >
          <MenuItem onClick={() => handleSync()}>
            <ListItemIcon>
              <SyncIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Sync All</ListItemText>
          </MenuItem>
          <MenuItem onClick={() => handleSync({ includePullRequests: true, includeCommits: false })}>
            <ListItemIcon>
              <PullRequestIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Sync Pull Requests Only</ListItemText>
          </MenuItem>
          <MenuItem onClick={() => handleSync({ includeCommits: true, includePullRequests: false })}>
            <ListItemIcon>
              <CodeIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Sync Commits Only</ListItemText>
          </MenuItem>
          <MenuItem onClick={() => handleSync({ forceRefresh: true })}>
            <ListItemIcon>
              <RefreshIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Force Refresh</ListItemText>
          </MenuItem>
        </Menu>
      </>
    );
  }

  return (
    <Button
      size={size}
      variant="outlined"
      startIcon={syncing ? <CircularProgress size={16} /> : <SyncIcon />}
      onClick={() => handleSync()}
      disabled={disabled || syncing}
    >
      {syncing ? 'Syncing...' : 'Sync'}
    </Button>
  );
};

export default RepositorySyncButton;