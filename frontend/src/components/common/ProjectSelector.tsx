import React from 'react';
import { FormControl, Select, MenuItem, Box, Typography, SelectChangeEvent } from '@mui/material';
import FolderOutlinedIcon from '@mui/icons-material/FolderOutlined';
import { useSelectedProject } from '../../hooks/useSelectedProject';

/**
 * The single global project selector (UX review C4), mounted in the app header.
 *
 * Replaces the four divergent per-page mechanisms (Dashboard chips, Analytics
 * dropdown, Quality/Visualization dropdowns, the free-text "Project ID" field in
 * Review). It reads/writes the shared `currentProject` via {@link useSelectedProject},
 * so a choice made here carries across every screen and survives reloads.
 */
export default function ProjectSelector({ compact = false }: { compact?: boolean }) {
  const { projects, projectId, selectProject } = useSelectedProject();

  const handleChange = (e: SelectChangeEvent<number>) => {
    const val = e.target.value;
    selectProject(typeof val === 'number' ? val : Number(val));
  };

  if (!projects || projects.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ display: { xs: 'none', sm: 'block' } }}>
        No projects
      </Typography>
    );
  }

  return (
    <FormControl size="small" sx={{ minWidth: compact ? 160 : 220 }}>
      <Select
        value={projectId ?? ''}
        onChange={handleChange}
        displayEmpty
        aria-label="Selected project"
        renderValue={(val) => {
          const p = projects.find((x) => x.id === val);
          return (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
              <FolderOutlinedIcon fontSize="small" color="action" />
              <Typography variant="body2" noWrap fontWeight={600}>
                {p ? p.name : 'Select project'}
              </Typography>
            </Box>
          );
        }}
        sx={{ '& .MuiSelect-select': { py: 0.75 } }}
      >
        {projects.map((p) => (
          <MenuItem key={p.id} value={p.id}>
            <Box sx={{ display: 'flex', flexDirection: 'column' }}>
              <Typography variant="body2" fontWeight={600} noWrap>
                {p.name}
              </Typography>
              {p.jira_key && (
                <Typography variant="caption" color="text.secondary">
                  {p.jira_key}
                </Typography>
              )}
            </Box>
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}
