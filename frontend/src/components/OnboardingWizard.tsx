import React, { useState, useEffect } from 'react';
import {
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Dialog,
  DialogContent,
  FormControl,
  FormControlLabel,
  LinearProgress,
  Radio,
  RadioGroup,
  Step,
  StepLabel,
  Stepper,
  TextField,
  Typography,
  Alert,
  List,
  ListItem,
  ListItemText,
  CircularProgress,
  Stack,
} from '@mui/material';
import { Check as CheckIcon, Celebration as CelebrationIcon } from '@mui/icons-material';
import { analytics } from '../services/analytics';

interface OnboardingWizardProps {
  open: boolean;
  onComplete: () => void;
  onSkip: () => void;
}

interface OnboardingState {
  useCase: string;
  jiraUrl: string;
  jiraEmail: string;
  jiraToken: string;
  jiraProjects: any[];
  selectedProjectKey: string;
  integrationsEnabled: {
    confluence: boolean;
    github: boolean;
    gitlab: boolean;
    testRail: boolean;
  };
  syncInProgress: boolean;
  syncResults: {
    tasks: number;
    sprints: number;
    complete: boolean;
  } | null;
}

const STEPS = [
  'Welcome',
  'Connect Jira',
  'Select Project',
  'Optional Integrations',
  'Sync Data',
  'Complete',
];

const OnboardingWizard: React.FC<OnboardingWizardProps> = ({ open, onComplete, onSkip }) => {
  const [activeStep, setActiveStep] = useState(0);
  const [state, setState] = useState<OnboardingState>({
    useCase: 'all',
    jiraUrl: '',
    jiraEmail: '',
    jiraToken: '',
    jiraProjects: [],
    selectedProjectKey: '',
    integrationsEnabled: {
      confluence: false,
      github: false,
      gitlab: false,
      testRail: false,
    },
    syncInProgress: false,
    syncResults: null,
  });
  const [testingConnection, setTestingConnection] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [connectionSuccess, setConnectionSuccess] = useState(false);

  // Load saved progress from localStorage and track onboarding start
  useEffect(() => {
    const saved = localStorage.getItem('onboarding_progress');
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        setState(prev => ({ ...prev, ...parsed }));
      } catch (e) {
        console.error('Failed to parse onboarding progress', e);
      }
    }

    // Track onboarding started
    if (open) {
      analytics.trackOnboarding('started', { totalSteps: STEPS.length });
    }
  }, [open]);

  // Save progress to localStorage
  useEffect(() => {
    localStorage.setItem('onboarding_progress', JSON.stringify(state));
  }, [state]);

  const handleNext = () => {
    // Track step completion
    analytics.trackOnboarding('step_completed', { step: activeStep, stepName: STEPS[activeStep] });
    setActiveStep(prev => Math.min(prev + 1, STEPS.length - 1));
  };

  const handleBack = () => {
    setActiveStep(prev => Math.max(prev - 1, 0));
  };

  const handleTestConnection = async () => {
    setTestingConnection(true);
    setConnectionError(null);
    setConnectionSuccess(false);

    try {
      // First, test connection using /jira/connect endpoint (query params required, not body)
      const params: Record<string, string> = {
        base_url: state.jiraUrl,
        api_token: state.jiraToken,
        save: 'false',  // Don't save during onboarding test
      };

      // Only add email if provided, otherwise use PAT mode
      if (state.jiraEmail) {
        params.email = state.jiraEmail;
        params.use_pat = 'false';
      } else {
        params.use_pat = 'true';
      }

      const queryString = new URLSearchParams(params).toString();

      const connectResponse = await fetch(
        `${import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'}/api/v1/jira/connect?${queryString}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        }
      );

      if (!connectResponse.ok) {
        const error = await connectResponse.json();
        throw new Error(error.detail || 'Connection failed');
      }

      // If connection successful, fetch projects
      const projectsResponse = await fetch(`${import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'}/api/v1/jira/projects`);

      if (!projectsResponse.ok) {
        throw new Error('Failed to fetch projects');
      }

      const projectsData = await projectsResponse.json();
      setState(prev => ({ ...prev, jiraProjects: projectsData.projects || [] }));
      setConnectionSuccess(true);

      // Track Jira connection success
      analytics.trackTimeToValue('jiraConnectedAt');
      analytics.track('jira_connected', { projectCount: projectsData.projects?.length || 0 });
    } catch (error: any) {
      setConnectionError(error.message || 'Failed to connect to Jira');
    } finally {
      setTestingConnection(false);
    }
  };

  const handleStartSync = async () => {
    setState(prev => ({ ...prev, syncInProgress: true }));

    try {
      // Simulate sync progress
      await new Promise(resolve => setTimeout(resolve, 1000));
      setState(prev => ({ ...prev, syncResults: { tasks: 0, sprints: 0, complete: false } }));

      // Call backend to start sync
      const response = await fetch(`${import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'}/api/v1/jira/sync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_key: state.selectedProjectKey,
        }),
      });

      if (!response.ok) {
        throw new Error('Sync failed');
      }

      const data = await response.json();
      setState(prev => ({
        ...prev,
        syncInProgress: false,
        syncResults: {
          tasks: data.tasks_synced || 0,
          sprints: data.sprints_synced || 0,
          complete: true,
        },
      }));

      // Track first sync completion - time to first value
      analytics.trackTimeToValue('firstSyncAt');
      analytics.track('first_sync_completed', {
        taskCount: data.tasks_synced || 0,
        sprintCount: data.sprints_synced || 0,
      });

      // Auto-advance to final step
      setTimeout(() => handleNext(), 1500);
    } catch (error) {
      console.error('Sync failed', error);
      setState(prev => ({ ...prev, syncInProgress: false }));
    }
  };

  const handleComplete = () => {
    // Track onboarding completion
    analytics.trackOnboarding('completed', {
      totalSteps: STEPS.length,
      useCase: state.useCase,
      jiraConnected: connectionSuccess,
      projectSelected: !!state.selectedProjectKey,
    });

    localStorage.setItem('onboarding_completed', 'true');
    localStorage.removeItem('onboarding_progress');
    onComplete();
  };

  const renderStepContent = () => {
    switch (activeStep) {
      case 0: // Welcome & Use Case Selection
        return (
          <Box>
            <Typography variant="h4" gutterBottom align="center" sx={{ mb: 3 }}>
              Welcome to PO Helper! 👋
            </Typography>
            <Typography variant="body1" color="text.secondary" align="center" sx={{ mb: 4 }}>
              What's your primary goal?
            </Typography>
            <FormControl component="fieldset" fullWidth>
              <RadioGroup
                value={state.useCase}
                onChange={(e) => setState(prev => ({ ...prev, useCase: e.target.value }))}
              >
                <Card sx={{ mb: 2, cursor: 'pointer' }} onClick={() => setState(prev => ({ ...prev, useCase: 'velocity' }))}>
                  <CardContent>
                    <FormControlLabel
                      value="velocity"
                      control={<Radio />}
                      label={
                        <Box>
                          <Typography variant="subtitle1" fontWeight={600}>Track team velocity and sprint metrics</Typography>
                          <Typography variant="body2" color="text.secondary">Monitor story points, burndown, and team performance</Typography>
                        </Box>
                      }
                    />
                  </CardContent>
                </Card>
                <Card sx={{ mb: 2, cursor: 'pointer' }} onClick={() => setState(prev => ({ ...prev, useCase: 'traceability' }))}>
                  <CardContent>
                    <FormControlLabel
                      value="traceability"
                      control={<Radio />}
                      label={
                        <Box>
                          <Typography variant="subtitle1" fontWeight={600}>Ensure requirements traceability</Typography>
                          <Typography variant="body2" color="text.secondary">Link requirements to code, tests, and deployments</Typography>
                        </Box>
                      }
                    />
                  </CardContent>
                </Card>
                <Card sx={{ mb: 2, cursor: 'pointer' }} onClick={() => setState(prev => ({ ...prev, useCase: 'quality' }))}>
                  <CardContent>
                    <FormControlLabel
                      value="quality"
                      control={<Radio />}
                      label={
                        <Box>
                          <Typography variant="subtitle1" fontWeight={600}>Monitor code quality and test coverage</Typography>
                          <Typography variant="body2" color="text.secondary">Track quality gates, test trends, and coverage metrics</Typography>
                        </Box>
                      }
                    />
                  </CardContent>
                </Card>
                <Card sx={{ mb: 2, cursor: 'pointer', border: 2, borderColor: 'primary.main' }} onClick={() => setState(prev => ({ ...prev, useCase: 'all' }))}>
                  <CardContent>
                    <FormControlLabel
                      value="all"
                      control={<Radio />}
                      label={
                        <Box>
                          <Typography variant="subtitle1" fontWeight={600}>All of the above (recommended)</Typography>
                          <Typography variant="body2" color="text.secondary">Get comprehensive product management insights</Typography>
                        </Box>
                      }
                    />
                  </CardContent>
                </Card>
              </RadioGroup>
            </FormControl>
          </Box>
        );

      case 1: // Jira Connection
        return (
          <Box>
            <Typography variant="h5" gutterBottom>Connect Your Jira Instance</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
              This is required to import your projects and tasks
            </Typography>

            <Stack spacing={3}>
              <TextField
                fullWidth
                label="Jira Base URL"
                placeholder="https://company.atlassian.net"
                value={state.jiraUrl}
                onChange={(e) => setState(prev => ({ ...prev, jiraUrl: e.target.value }))}
                helperText="Your Jira instance URL"
              />
              <TextField
                fullWidth
                label="Email (Optional for PAT)"
                type="email"
                placeholder="user@company.com"
                value={state.jiraEmail}
                onChange={(e) => setState(prev => ({ ...prev, jiraEmail: e.target.value }))}
                helperText="Your Jira account email (not required for Personal Access Token)"
              />
              <TextField
                fullWidth
                label="API Token"
                type="password"
                value={state.jiraToken}
                onChange={(e) => setState(prev => ({ ...prev, jiraToken: e.target.value }))}
                helperText={
                  <span>
                    Generate at{' '}
                    <a href="https://id.atlassian.com/manage-profile/security/api-tokens" target="_blank" rel="noopener noreferrer">
                      Atlassian API tokens
                    </a>
                  </span>
                }
              />

              <Box>
                <Button
                  variant="contained"
                  onClick={handleTestConnection}
                  disabled={!state.jiraUrl || !state.jiraToken || testingConnection}
                  startIcon={testingConnection ? <CircularProgress size={20} /> : undefined}
                >
                  {testingConnection ? 'Testing...' : 'Test Connection'}
                </Button>
              </Box>

              {connectionError && (
                <Alert severity="error">{connectionError}</Alert>
              )}

              {connectionSuccess && (
                <Alert severity="success" icon={<CheckIcon />}>
                  ✓ Connected to Jira! Found {state.jiraProjects.length} projects
                </Alert>
              )}
            </Stack>
          </Box>
        );

      case 2: // Select Project
        return (
          <Box>
            <Typography variant="h5" gutterBottom>Which project would you like to start with?</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
              Selected project will sync first. You can add more projects later from Settings.
            </Typography>

            {state.jiraProjects.length === 0 ? (
              <Alert severity="warning">
                No projects found. Please go back and test your Jira connection.
              </Alert>
            ) : (
              <FormControl component="fieldset" fullWidth>
                <RadioGroup
                  value={state.selectedProjectKey}
                  onChange={(e) => setState(prev => ({ ...prev, selectedProjectKey: e.target.value }))}
                >
                  {state.jiraProjects.map((project) => (
                    <Card key={project.key} sx={{ mb: 2, cursor: 'pointer' }} onClick={() => setState(prev => ({ ...prev, selectedProjectKey: project.key }))}>
                      <CardContent>
                        <FormControlLabel
                          value={project.key}
                          control={<Radio />}
                          label={
                            <Box>
                              <Typography variant="subtitle1" fontWeight={600}>
                                {project.key} - {project.name}
                              </Typography>
                              <Typography variant="body2" color="text.secondary">
                                Project type: {project.projectTypeKey || 'Unknown'}
                              </Typography>
                            </Box>
                          }
                        />
                      </CardContent>
                    </Card>
                  ))}
                </RadioGroup>
              </FormControl>
            )}
          </Box>
        );

      case 3: // Optional Integrations
        return (
          <Box>
            <Typography variant="h5" gutterBottom>Enhance Your Experience (Optional)</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
              You can configure these later in Settings
            </Typography>

            <Stack spacing={2}>
              <Card>
                <CardContent>
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={state.integrationsEnabled.confluence}
                        onChange={(e) => setState(prev => ({
                          ...prev,
                          integrationsEnabled: { ...prev.integrationsEnabled, confluence: e.target.checked }
                        }))}
                      />
                    }
                    label={
                      <Box>
                        <Typography variant="subtitle1" fontWeight={600}>Confluence</Typography>
                        <Typography variant="body2" color="text.secondary">Link requirements to tasks</Typography>
                      </Box>
                    }
                  />
                </CardContent>
              </Card>

              <Card>
                <CardContent>
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={state.integrationsEnabled.github}
                        onChange={(e) => setState(prev => ({
                          ...prev,
                          integrationsEnabled: { ...prev.integrationsEnabled, github: e.target.checked }
                        }))}
                      />
                    }
                    label={
                      <Box>
                        <Typography variant="subtitle1" fontWeight={600}>GitHub</Typography>
                        <Typography variant="body2" color="text.secondary">Track commits and PRs</Typography>
                      </Box>
                    }
                  />
                </CardContent>
              </Card>

              <Card>
                <CardContent>
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={state.integrationsEnabled.gitlab}
                        onChange={(e) => setState(prev => ({
                          ...prev,
                          integrationsEnabled: { ...prev.integrationsEnabled, gitlab: e.target.checked }
                        }))}
                      />
                    }
                    label={
                      <Box>
                        <Typography variant="subtitle1" fontWeight={600}>GitLab</Typography>
                        <Typography variant="body2" color="text.secondary">Track commits and PRs</Typography>
                      </Box>
                    }
                  />
                </CardContent>
              </Card>

              <Card>
                <CardContent>
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={state.integrationsEnabled.testRail}
                        onChange={(e) => setState(prev => ({
                          ...prev,
                          integrationsEnabled: { ...prev.integrationsEnabled, testRail: e.target.checked }
                        }))}
                      />
                    }
                    label={
                      <Box>
                        <Typography variant="subtitle1" fontWeight={600}>TestRail</Typography>
                        <Typography variant="body2" color="text.secondary">Import test cases</Typography>
                      </Box>
                    }
                  />
                </CardContent>
              </Card>
            </Stack>
          </Box>
        );

      case 4: // First Sync
        return (
          <Box>
            <Typography variant="h5" gutterBottom align="center">
              {state.syncInProgress ? 'Syncing Your Data... 📥' : 'Ready to Sync'}
            </Typography>

            {!state.syncInProgress && !state.syncResults?.complete && (
              <Box sx={{ textAlign: 'center', my: 4 }}>
                <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
                  We'll import tasks, sprints, and calculate metrics from project: <strong>{state.selectedProjectKey}</strong>
                </Typography>
                <Button variant="contained" size="large" onClick={handleStartSync}>
                  Start Sync
                </Button>
              </Box>
            )}

            {state.syncInProgress && (
              <Box sx={{ my: 4 }}>
                <List>
                  <ListItem>
                    <ListItemText
                      primary={state.syncResults ? `✓ Loaded ${state.syncResults.tasks} tasks from ${state.selectedProjectKey}` : '⏳ Loading tasks...'}
                    />
                  </ListItem>
                  <ListItem>
                    <ListItemText
                      primary={state.syncResults ? `✓ Loaded ${state.syncResults.sprints} sprints` : '⏳ Loading sprints...'}
                    />
                  </ListItem>
                  <ListItem>
                    <ListItemText primary="⏳ Analyzing velocity..." />
                  </ListItem>
                  <ListItem>
                    <ListItemText primary="⏳ Calculating metrics..." />
                  </ListItem>
                </List>

                <LinearProgress sx={{ my: 2 }} />

                <Typography variant="body2" color="text.secondary" align="center">
                  This usually takes 1-2 minutes
                </Typography>
              </Box>
            )}

            {state.syncResults?.complete && (
              <Box sx={{ textAlign: 'center', my: 4 }}>
                <CheckIcon sx={{ fontSize: 80, color: 'success.main', mb: 2 }} />
                <Typography variant="h6" gutterBottom>
                  Sync Complete!
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Successfully imported {state.syncResults.tasks} tasks and {state.syncResults.sprints} sprints
                </Typography>
              </Box>
            )}
          </Box>
        );

      case 5: // Success & Next Steps
        return (
          <Box sx={{ textAlign: 'center' }}>
            <CelebrationIcon sx={{ fontSize: 100, color: 'primary.main', mb: 2 }} />
            <Typography variant="h4" gutterBottom>All Set! 🎉</Typography>

            <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
              Your dashboard is ready with:
            </Typography>

            <List sx={{ textAlign: 'left', maxWidth: 500, mx: 'auto', mb: 3 }}>
              <ListItem>
                <ListItemText
                  primary={`✓ ${state.syncResults?.tasks || 0} tasks from ${state.selectedProjectKey} project`}
                />
              </ListItem>
              <ListItem>
                <ListItemText primary={`✓ ${state.syncResults?.sprints || 0} sprints of velocity data`} />
              </ListItem>
              <ListItem>
                <ListItemText primary="✓ Team performance metrics" />
              </ListItem>
            </List>

            <Typography variant="subtitle2" gutterBottom sx={{ mb: 2 }}>
              Recommended Next Steps:
            </Typography>
            <List sx={{ textAlign: 'left', maxWidth: 500, mx: 'auto', mb: 4 }}>
              <ListItem>
                <ListItemText primary="1. Map Jira custom fields for better analytics" secondary="Settings → Jira Fields" />
              </ListItem>
              <ListItem>
                <ListItemText primary="2. Run traceability backfill" secondary="Traceability → Run Backfill" />
              </ListItem>
              <ListItem>
                <ListItemText primary="3. Connect Git for commit tracking" secondary="Settings → GitHub/GitLab" />
              </ListItem>
            </List>

            <Stack direction="row" spacing={2} justifyContent="center">
              <Button variant="outlined" size="large">
                Show Me Around
              </Button>
              <Button variant="contained" size="large" onClick={handleComplete}>
                Go to Dashboard
              </Button>
            </Stack>
          </Box>
        );

      default:
        return null;
    }
  };

  const canProceed = () => {
    switch (activeStep) {
      case 0:
        return state.useCase !== '';
      case 1:
        return connectionSuccess;
      case 2:
        return state.selectedProjectKey !== '';
      case 3:
        return true; // Optional step
      case 4:
        return state.syncResults?.complete;
      case 5:
        return true;
      default:
        return false;
    }
  };

  return (
    <Dialog open={open} maxWidth="md" fullWidth disableEscapeKeyDown>
      <DialogContent sx={{ p: 4 }}>
        <Stepper activeStep={activeStep} sx={{ mb: 4 }}>
          {STEPS.map((label) => (
            <Step key={label}>
              <StepLabel>{label}</StepLabel>
            </Step>
          ))}
        </Stepper>

        <Box sx={{ minHeight: 400 }}>
          {renderStepContent()}
        </Box>

        <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 4 }}>
          <Button
            onClick={() => {
              analytics.trackOnboarding('skipped', { step: activeStep });
              onSkip();
            }}
            disabled={activeStep === 5}
          >
            Skip Setup
          </Button>
          <Box>
            <Button onClick={handleBack} disabled={activeStep === 0 || activeStep === 5} sx={{ mr: 1 }}>
              Back
            </Button>
            {activeStep < 5 && (
              <Button
                variant="contained"
                onClick={handleNext}
                disabled={!canProceed()}
              >
                {activeStep === STEPS.length - 2 ? 'Finish' : 'Continue'}
              </Button>
            )}
          </Box>
        </Box>

        <Box sx={{ textAlign: 'center', mt: 2 }}>
          <Typography variant="caption" color="text.secondary">
            Step {activeStep + 1} of {STEPS.length}
          </Typography>
        </Box>
      </DialogContent>
    </Dialog>
  );
};

export default OnboardingWizard;
