import React from 'react';
import {
  Box,
  Button,
  CircularProgress,
  FormControl,
  FormControlLabel,
  InputLabel,
  LinearProgress,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  Typography,
} from '@mui/material';
import type { SelectChangeEvent } from '@mui/material/Select';
import RefreshIcon from '@mui/icons-material/Refresh';
import SyncIcon from '@mui/icons-material/Sync';
import DownloadIcon from '@mui/icons-material/Download';
import type { Project } from '../../services/api';

interface ProjectScopePanelProps {
  projects: Project[];
  projectId: number | 'all';
  projectsLoading: boolean;
  includeConfluence: boolean;
  includeGit: boolean;
  backfillRunning: boolean;
  matrixLoading: boolean;
  selectedProject?: Project;
  onProjectChange: (event: SelectChangeEvent<string>) => void;
  onIncludeConfluenceChange: (checked: boolean) => void;
  onIncludeGitChange: (checked: boolean) => void;
  onBackfill: () => void;
  onRefresh: () => void;
  onExport: () => void;
}

/**
 * Project scope card (project selector, repair source switches,
 * repair/refresh/export actions) extracted from pages/Traceability.tsx.
 */
const ProjectScopePanel: React.FC<ProjectScopePanelProps> = ({
  projects,
  projectId,
  projectsLoading,
  includeConfluence,
  includeGit,
  backfillRunning,
  matrixLoading,
  selectedProject,
  onProjectChange,
  onIncludeConfluenceChange,
  onIncludeGitChange,
  onBackfill,
  onRefresh,
  onExport,
}) => {
  const selectedProjectLastSync = typeof selectedProject?.meta?.last_sync_at === 'string'
    ? selectedProject.meta.last_sync_at
    : null;

  return (
  <Paper sx={{ p: 2, display: 'flex', flexDirection: 'column', gap: 2, height: '100%' }}>
    <Box>
      <Typography variant="h6" gutterBottom>
        Project scope
      </Typography>
      <FormControl size="small" fullWidth disabled={projectsLoading || projects.length === 0}>
        <InputLabel id="traceability-project-label">Project</InputLabel>
        <Select
          labelId="traceability-project-label"
          label="Project"
          value={projects.length === 0 ? 'all' : String(projectId)}
          onChange={onProjectChange}
        >
          <MenuItem value="all">All projects</MenuItem>
          {projects.map(project => (
            <MenuItem key={project.id} value={String(project.id)}>
              {project.name || project.jira_key || `Project ${project.id}`}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
      {projectsLoading && <LinearProgress sx={{ mt: 2 }} />}
    </Box>

    <FormControlLabel
      control={
        <Switch
          size="small"
          checked={includeConfluence}
          onChange={event => onIncludeConfluenceChange(event.target.checked)}
          disabled={backfillRunning}
        />
      }
      label="Include Confluence pages"
    />
    <FormControlLabel
      control={
        <Switch
          size="small"
          checked={includeGit}
          onChange={event => onIncludeGitChange(event.target.checked)}
          disabled={backfillRunning}
        />
      }
      label="Include Git repositories"
    />

    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
      <Button
        variant="contained"
        color="primary"
        fullWidth
        startIcon={backfillRunning ? <CircularProgress size={18} color="inherit" /> : <SyncIcon />}
        onClick={onBackfill}
        disabled={backfillRunning || typeof projectId !== 'number'}
      >
        Run traceability repair
      </Button>
      <Button
        variant="outlined"
        fullWidth
        startIcon={<RefreshIcon />}
        onClick={onRefresh}
        disabled={matrixLoading}
      >
        Refresh
      </Button>
      <Button
        variant="outlined"
        fullWidth
        startIcon={<DownloadIcon />}
        onClick={() => onExport()}
        disabled={typeof projectId !== 'number' || matrixLoading}
      >
        Export
      </Button>
    </Stack>

    {selectedProject && (
      <Typography variant="caption" color="text.secondary">
        Jira key: {selectedProject.jira_key}
        {selectedProjectLastSync
          ? ` • Last source sync: ${new Date(selectedProjectLastSync).toLocaleString()}`
          : ''}
      </Typography>
    )}
    {typeof projectId !== 'number' && (
      <Typography variant="caption" color="text.secondary">
        Select a project to enable traceability repair and deeper analysis.
      </Typography>
    )}
  </Paper>
  );
};

export default ProjectScopePanel;
