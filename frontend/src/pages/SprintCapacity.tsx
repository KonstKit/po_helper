import React, { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  Grid,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Paper,
  Tabs,
  Tab,
} from '@mui/material';
import {
  People as PeopleIcon,
  Favorite as HealthIcon,
  Timeline as CFDIcon,
} from '@mui/icons-material';
import type { SelectChangeEvent } from '@mui/material/Select';
import { listProjects, listSprints, type Project, type Sprint } from '../services/api';
import { getCanonicalSprintId, isSprintActive, selectActiveSprint } from '../utils/sprintNormalization';
import {
  CapacitySettingsPanel,
  TeamHealthDashboard,
  CFDVisualization,
} from '../components/capacity';

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

const TabPanel: React.FC<TabPanelProps> = ({ children, value, index }) => (
  <div role="tabpanel" hidden={value !== index}>
    {value === index && <Box sx={{ pt: 3 }}>{children}</Box>}
  </div>
);

const SprintCapacity: React.FC = () => {
  const [projects, setProjects] = useState<Project[]>([]);
  const [sprints, setSprints] = useState<Sprint[]>([]);
  const [projectId, setProjectId] = useState<number | ''>('');
  const [sprintId, setSprintId] = useState<number | ''>('');
  const [activeTab, setActiveTab] = useState(0);

  const parseNumberValue = (value: string): number | '' => {
    if (value === '') return '';
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : '';
  };
  const handleProjectChange = (event: SelectChangeEvent<string>) => {
    setProjectId(parseNumberValue(event.target.value));
  };
  const handleSprintChange = (event: SelectChangeEvent<string>) => {
    setSprintId(parseNumberValue(event.target.value));
  };
  const handleTabChange = (_: React.SyntheticEvent, newValue: number) => {
    setActiveTab(newValue);
  };

  // Load projects on mount
  useEffect(() => {
    (async () => {
      try {
        const psResp = await listProjects({});
        const ps = psResp.data;
        setProjects(ps);
        if (ps.length > 0) {
          setProjectId(ps[0].id);
        }
      } catch (err) {
        console.error('Failed to load projects:', err);
      }
    })();
  }, []);

  // Load sprints when project changes
  useEffect(() => {
    if (!projectId) {
      const resetId = setTimeout(() => {
        setSprints([]);
        setSprintId('');
      }, 0);
      return () => clearTimeout(resetId);
    }
    (async () => {
      try {
        const sp = await listSprints({ projectId });
        setSprints(sp);
        const activeSprint = selectActiveSprint(sp);
        const activeSprintId = getCanonicalSprintId(activeSprint);
        if (activeSprintId !== null) {
          setSprintId(activeSprintId);
        } else if (sp.length > 0) {
          setSprintId(getCanonicalSprintId(sp[0]) ?? '');
        } else {
          setSprintId('');
        }
      } catch (err) {
        console.error('Failed to load sprints:', err);
        setSprints([]);
      }
    })();
  }, [projectId]);

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Sprint & Capacity Analytics
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Manage team capacity, track health metrics, and visualize workflow with Cumulative Flow Diagrams
      </Typography>

      {/* Project/Sprint Selectors */}
      <Paper sx={{ p: 2, mb: 3 }}>
        <Grid container spacing={2} alignItems="center">
          <Grid item xs={12} sm={4}>
            <FormControl fullWidth size="small">
              <InputLabel>Project</InputLabel>
              <Select
                value={projectId}
                label="Project"
                onChange={handleProjectChange}
              >
                {projects.map((p) => (
                  <MenuItem key={p.id} value={p.id}>
                    {p.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} sm={4}>
            <FormControl fullWidth size="small">
              <InputLabel>Sprint (optional)</InputLabel>
              <Select
                value={sprintId}
                label="Sprint (optional)"
                onChange={handleSprintChange}
                >
                  <MenuItem value="">All Sprints</MenuItem>
                  {sprints.map((s) => {
                    const sprintIdentifier = getCanonicalSprintId(s);
                    if (sprintIdentifier === null) return null;
                    return (
                      <MenuItem key={sprintIdentifier} value={sprintIdentifier}>
                        {s.name} {isSprintActive(s) ? '(Active)' : ''}
                      </MenuItem>
                    );
                  })}
                </Select>
              </FormControl>
            </Grid>
        </Grid>
      </Paper>

      {!projectId ? (
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <Typography color="text.secondary">
            Select a project to view capacity and health analytics
          </Typography>
        </Paper>
      ) : (
        <>
          {/* Tabs */}
          <Paper sx={{ mb: 2 }}>
            <Tabs
              value={activeTab}
              onChange={handleTabChange}
              variant="fullWidth"
              indicatorColor="primary"
              textColor="primary"
            >
              <Tab icon={<PeopleIcon />} label="Team Capacity" iconPosition="start" />
              <Tab icon={<HealthIcon />} label="Team Health" iconPosition="start" />
              <Tab icon={<CFDIcon />} label="Flow Diagram" iconPosition="start" />
            </Tabs>
          </Paper>

          {/* Tab Panels */}
          <TabPanel value={activeTab} index={0}>
            <CapacitySettingsPanel
              projectId={projectId}
              sprintId={sprintId || undefined}
            />
          </TabPanel>

          <TabPanel value={activeTab} index={1}>
            <TeamHealthDashboard
              projectId={projectId}
              sprintId={sprintId || undefined}
            />
          </TabPanel>

          <TabPanel value={activeTab} index={2}>
            <CFDVisualization
              projectId={projectId}
              sprintId={sprintId || undefined}
            />
          </TabPanel>
        </>
      )}
    </Box>
  );
};

export default SprintCapacity;
