import React, { useEffect, useState } from 'react';
import {
  Box,
  Typography,
  Card,
  TextField,
  Button,
  Grid,
  Divider,
  Switch,
  FormControlLabel,
  Alert,
  Tab,
  Tabs,
  Chip,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  FormHelperText,
  Autocomplete,
  InputAdornment,
} from '@mui/material';
import TabPanel from '../components/TabPanel';
import { Save as SaveIcon, Science as TestIcon, AutoAwesome as AutoAwesomeIcon } from '@mui/icons-material';
import { getJiraSettings, putJiraSettings, getConfluenceSettings, putConfluenceSettings, testJiraConnection, testConfluenceConnection, testGithubConnection, testGitlabConnection, testTestrailConnection, getGithubSettings, putGithubSettings, getGitlabSettings, putGitlabSettings, getTestrailSettings, putTestrailSettings } from '../services/api';
import { analytics } from '../services/analytics';
import { detectTimezone, detectCurrency, loadSmartDefaults, SmartDefaults } from '../utils/smartDefaults';
import { getErrorMessage } from '../utils/errorUtils';
import { OptionalIntegrations } from '../components/OptionalIntegrations';
import { IntegrationCard } from '../components/IntegrationCard';
import { ConfluenceSpaceMapping } from '../components/ConfluenceSpaceMapping';
import { HelpPanel } from '../components/HelpPanel';

type AuthMode = 'PAT' | 'Basic';

type JiraSettings = {
  baseUrl: string;
  email: string;
  apiToken: string;
};

type ConfluenceSettings = {
  baseUrl: string;
  email: string;
  apiToken: string;
};

type NotificationSettings = {
  emailNotifications: boolean;
  slackNotifications: boolean;
  riskAlerts: boolean;
  dailyReports: boolean;
};

type GeneralSettings = {
  sprintDuration: number;
  workingHoursPerDay: number;
  currency: string;
  timezone: string;
};

type MessageState = { type: 'success' | 'error'; text: string };

type GitProviderSettings = {
  baseUrl: string;
  apiToken: string;
  webhookSecret: string;
};

type TestRailSettings = {
  baseUrl: string;
  email: string;
  apiToken: string;
};

const DEFAULT_JIRA_BASE_URL = 'https://company.atlassian.net';
const DEFAULT_CONFLUENCE_BASE_URL = 'https://company.atlassian.net/wiki';

// Common currencies for the General settings selector (ISO 4217 codes)
const CURRENCY_OPTIONS: { code: string; label: string }[] = [
  { code: 'USD', label: 'USD — US Dollar' },
  { code: 'EUR', label: 'EUR — Euro' },
  { code: 'GBP', label: 'GBP — British Pound' },
  { code: 'JPY', label: 'JPY — Japanese Yen' },
  { code: 'CHF', label: 'CHF — Swiss Franc' },
  { code: 'CAD', label: 'CAD — Canadian Dollar' },
  { code: 'AUD', label: 'AUD — Australian Dollar' },
  { code: 'RUB', label: 'RUB — Russian Ruble' },
  { code: 'AMD', label: 'AMD — Armenian Dram' },
  { code: 'INR', label: 'INR — Indian Rupee' },
  { code: 'CNY', label: 'CNY — Chinese Yuan' },
];

// Fallback IANA timezones used when Intl.supportedValuesOf is unavailable
const FALLBACK_TIMEZONES = [
  'UTC',
  'Asia/Yerevan',
  'Europe/London',
  'Europe/Moscow',
  'America/New_York',
  'America/Los_Angeles',
];

function getTimezoneOptions(): string[] {
  try {
    const supportedValuesOf = (
      Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
    ).supportedValuesOf;
    if (typeof supportedValuesOf === 'function') {
      const zones = supportedValuesOf('timeZone');
      if (Array.isArray(zones) && zones.length > 0) {
        return zones;
      }
    }
  } catch {
    // Intl.supportedValuesOf not available — fall through to fallback list
  }
  return FALLBACK_TIMEZONES;
}

const Settings = () => {
  const [tabValue, setTabValue] = useState(0);
  const [jiraSettings, setJiraSettings] = useState<JiraSettings>({
    baseUrl: DEFAULT_JIRA_BASE_URL,
    email: '',
    apiToken: '',
  });
  const [jiraHasToken, setJiraHasToken] = useState(false);
  const [authMode, setAuthMode] = useState<AuthMode>('PAT');
  const [confluenceSettings, setConfluenceSettings] = useState<ConfluenceSettings>({
    baseUrl: DEFAULT_CONFLUENCE_BASE_URL,
    email: '',
    apiToken: '',
  });
  const [confluenceHasToken, setConfluenceHasToken] = useState(false);
  const [notificationSettings, setNotificationSettings] = useState<NotificationSettings>({
    emailNotifications: true,
    slackNotifications: false,
    riskAlerts: true,
    dailyReports: false,
  });
  const [smartDefaults] = useState<SmartDefaults | null>(() => loadSmartDefaults());
  const [generalSettings, setGeneralSettings] = useState<GeneralSettings>(() => {
    const defaults = loadSmartDefaults();
    if (defaults) {
      return {
        sprintDuration: defaults.sprintDuration,
        workingHoursPerDay: defaults.workingHoursPerDay,
        currency: defaults.currency,
        timezone: defaults.timezone,
      };
    }
    return {
      sprintDuration: 14,
      workingHoursPerDay: 8,
      currency: detectCurrency(),
      timezone: detectTimezone(),
    };
  });
  const [timezoneOptions] = useState<string[]>(() => getTimezoneOptions());
  const [message, setMessage] = useState<MessageState | null>(null);
  // Git providers
  const [githubSettings, setGithubSettings] = useState<GitProviderSettings>({ baseUrl: '', apiToken: '', webhookSecret: '' });
  const [githubHasToken, setGithubHasToken] = useState(false);
  const [gitlabSettings, setGitlabSettings] = useState<GitProviderSettings>({ baseUrl: '', apiToken: '', webhookSecret: '' });
  const [gitlabHasToken, setGitlabHasToken] = useState(false);
  // TestRail
  const [testrailSettings, setTestrailSettings] = useState<TestRailSettings>({ baseUrl: '', email: '', apiToken: '' });
  const [testrailHasToken, setTestrailHasToken] = useState(false);

  const handleTabChange = (event: React.SyntheticEvent, newValue: number) => {
    setTabValue(newValue);
  };

  useEffect(() => {
    (async () => {
      try {
        const j = await getJiraSettings();
        setJiraSettings({
          baseUrl: j.base_url || DEFAULT_JIRA_BASE_URL,
          email: j.email || '',
          apiToken: '', // masked on server; keep local empty
        });
        setJiraHasToken(!!j.has_token);
        setAuthMode(j.email ? 'Basic' : 'PAT');
      } catch (err) {
        console.warn('Failed to load Jira settings', err);
      }
      try {
        const c = await getConfluenceSettings();
        setConfluenceSettings({
          baseUrl: c.base_url || DEFAULT_CONFLUENCE_BASE_URL,
          email: c.email || '',
          apiToken: c.api_token || '',
        });
        setConfluenceHasToken(!!c.has_token);
      } catch (err) {
        console.warn('Failed to load Confluence settings', err);
      }
      try {
        const gh = await getGithubSettings();
        setGithubSettings({ baseUrl: gh.base_url || '', apiToken: '', webhookSecret: '' });
        setGithubHasToken(!!gh.has_token);
      } catch (err) {
        console.warn('Failed to load GitHub settings', err);
      }
      try {
        const gl = await getGitlabSettings();
        setGitlabSettings({ baseUrl: gl.base_url || '', apiToken: '', webhookSecret: '' });
        setGitlabHasToken(!!gl.has_token);
      } catch (err) {
        console.warn('Failed to load GitLab settings', err);
      }
      try {
        const tr = await getTestrailSettings();
        setTestrailSettings({ baseUrl: tr.base_url || '', email: tr.email || '', apiToken: '' });
        setTestrailHasToken(!!tr.has_token);
      } catch (err) {
        console.warn('Failed to load TestRail settings', err);
      }
    })();
  }, []);

  const handleJiraSettingsChange = <K extends keyof JiraSettings>(
    field: K,
    value: JiraSettings[K]
  ) => {
    setJiraSettings((prev) => ({ ...prev, [field]: value }));
  };

  const handleConfluenceSettingsChange = <K extends keyof ConfluenceSettings>(
    field: K,
    value: ConfluenceSettings[K]
  ) => {
    setConfluenceSettings((prev) => ({ ...prev, [field]: value }));
  };

  const handleNotificationChange = <K extends keyof NotificationSettings>(
    field: K,
    value: NotificationSettings[K]
  ) => {
    setNotificationSettings((prev) => ({ ...prev, [field]: value }));
  };

  const handleGeneralSettingsChange = <K extends keyof GeneralSettings>(
    field: K,
    value: GeneralSettings[K]
  ) => {
    setGeneralSettings((prev) => ({ ...prev, [field]: value }));
  };

  const testJiraConnectionHandler = async () => {
    try {
      await testJiraConnection({
        baseUrl: jiraSettings.baseUrl,
        email: authMode === 'Basic' ? jiraSettings.email : undefined,
        apiToken: jiraSettings.apiToken,
        usePat: authMode === 'PAT',
      });
      setMessage({ type: 'success', text: 'Jira connection successful!' });
    } catch (error) {
      const detail = getErrorMessage(error, 'Unknown error');
      setMessage({
        type: 'error',
        text: detail.toLowerCase().startsWith('failed to connect to jira')
          ? detail
          : `Failed to connect to Jira: ${detail}`,
      });
    }
  };

  const testConfluenceConnectionHandler = async () => {
    try {
      const payload: { baseUrl: string; apiToken: string; email?: string } = {
        baseUrl: confluenceSettings.baseUrl,
        apiToken: confluenceSettings.apiToken,
      };
      if (confluenceSettings.email) payload.email = confluenceSettings.email;
      await testConfluenceConnection(payload);
      setMessage({ type: 'success', text: 'Confluence connection successful!' });
    } catch (error) {
      const detail = getErrorMessage(error, 'Unknown error');
      setMessage({ type: 'error', text: `Failed to connect to Confluence: ${detail}` });
    }
  };
  const testGithubConnectionHandler = async () => {
    try {
      const response = await testGithubConnection({
        baseUrl: githubSettings.baseUrl || undefined,
        apiToken: githubSettings.apiToken || undefined,
      });
      const loginInfo = response?.login ? ` as ${response.login}` : '';
      const extraInfo = response?.message ? ` (${response.message})` : '';
      setMessage({ type: 'success', text: `GitHub connection successful${loginInfo}${extraInfo}`.trim() });
    } catch (error) {
      const detail = getErrorMessage(error, 'Unknown error');
      setMessage({ type: 'error', text: `Failed to connect to GitHub: ${detail}` });
    }
  };

  const testGitlabConnectionHandler = async () => {
    try {
      const response = await testGitlabConnection({
        baseUrl: gitlabSettings.baseUrl || undefined,
        apiToken: gitlabSettings.apiToken || undefined,
        webhookSecret: gitlabSettings.webhookSecret || undefined,
      });
      const name = response?.username || response?.name;
      const suffix = name ? ` as ${name}` : '';
      setMessage({ type: 'success', text: `GitLab connection successful${suffix}`.trim() });
    } catch (error) {
      const detail = getErrorMessage(error, 'Unknown error');
      setMessage({ type: 'error', text: `Failed to connect to GitLab: ${detail}` });
    }
  };

  const testTestrailConnectionHandler = async () => {
    try {
      const response = await testTestrailConnection({
        baseUrl: testrailSettings.baseUrl || undefined,
        email: testrailSettings.email || undefined,
        apiToken: testrailSettings.apiToken || undefined,
      });
      const extraInfo = typeof response?.status_count === 'number' ? ` (statuses: ${response.status_count})` : '';
      setMessage({ type: 'success', text: `TestRail connection successful${extraInfo}`.trim() });
    } catch (error) {
      const detail = getErrorMessage(error, 'Unknown error');
      setMessage({ type: 'error', text: `Failed to connect to TestRail: ${detail}` });
    }
  };

const saveJiraSettings = async () => {
    // Track Jira settings save
    analytics.track('integration_configured', { integration: 'jira', authMode });
    try {
      const r = await putJiraSettings({
        baseUrl: jiraSettings.baseUrl,
        email: authMode === 'Basic' ? jiraSettings.email : undefined,
        apiToken: jiraSettings.apiToken,
        usePat: authMode === 'PAT',
      });
      setJiraHasToken(!!r.has_token);
      setMessage({ type: 'success', text: 'Jira settings saved' });
    } catch {
      setMessage({ type: 'error', text: 'Failed to save Jira settings.' });
    }
  };

  const saveConfluenceSettings = async () => {
    analytics.track('integration_configured', { integration: 'confluence' });
    try {
      const r = await putConfluenceSettings({ baseUrl: confluenceSettings.baseUrl, email: confluenceSettings.email, apiToken: confluenceSettings.apiToken });
      setConfluenceHasToken(!!r.has_token);
      setMessage({ type: 'success', text: 'Confluence settings saved' });
    } catch {
      setMessage({ type: 'error', text: 'Failed to save Confluence settings.' });
    }
  };

  const saveNotificationSettings = async () => {
    setMessage({ type: 'success', text: 'Notification settings saved' });
  };

  const saveGeneralSettings = async () => {
    setMessage({ type: 'success', text: 'General settings saved' });
  };

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Settings
      </Typography>

      {message && (
        <Alert 
          severity={message.type} 
          onClose={() => setMessage(null)}
          sx={{ mb: 3 }}
        >
          {message.text}
        </Alert>
      )}

      <Card>
        <Tabs value={tabValue} onChange={handleTabChange}>
          <Tab label="General" />
          <Tab label="Notifications" />
          <Tab label="Jira Integration" />
          <Tab label="Optional Integrations" />
          <Tab label="Confluence Spaces" />
        </Tabs>

        <TabPanel value={tabValue} index={2}>
          <Typography variant="h6" gutterBottom>
            Jira Configuration
          </Typography>

          <HelpPanel
            title="🔑 How to Generate Jira API Token"
            variant="guide"
            steps={[
              { text: 'Go to https://id.atlassian.com/manage-profile/security/api-tokens' },
              { text: 'Click "Create API token"' },
              { text: 'Give it a label (e.g., "PO Helper")' },
              { text: 'Copy the token and paste it below' },
              { text: 'Important: Save the token somewhere safe - you won\'t be able to see it again!' },
            ]}
            docsUrl="https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/"
          />

          <Box display="flex" gap={2} mb={2}>
            <Button variant={authMode==='PAT'?'contained':'outlined'} onClick={()=>setAuthMode('PAT')}>PAT</Button>
            <Button variant={authMode==='Basic'?'contained':'outlined'} onClick={()=>setAuthMode('Basic')}>Basic</Button>
          </Box>
          <Grid container spacing={3}>
            <Grid item xs={12}>
              <TextField
                fullWidth
                label="Jira Base URL"
                placeholder="https://company.atlassian.net"
                value={jiraSettings.baseUrl}
                onChange={(e) => handleJiraSettingsChange('baseUrl', e.target.value)}
                helperText="Your Jira instance URL"
              />
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                label="Email"
                type="email"
                value={jiraSettings.email}
                onChange={(e) => handleJiraSettingsChange('email', e.target.value)}
                disabled={authMode==='PAT'}
                helperText="Your Jira account email"
              />
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                label="API Token"
                type="password"
                value={jiraSettings.apiToken}
                onChange={(e) => handleJiraSettingsChange('apiToken', e.target.value)}
                placeholder={jiraHasToken ? '•••••••• (stored)' : 'Enter token'}
                helperText={jiraHasToken ? 'Leave empty to keep the stored token (hidden for security)' : 'Generate from Jira Account Settings'}
              />
              {jiraHasToken && !jiraSettings.apiToken && (
                <Typography variant="caption" color="text.secondary">Token is saved on server and hidden for security</Typography>
              )}
            </Grid>
            <Grid item xs={12}>
              <Box display="flex" gap={2}>
                <Button
                  variant="outlined"
                  startIcon={<TestIcon />}
                  onClick={testJiraConnectionHandler}
                >
                  Test Connection
                </Button>
                <Button variant="contained" startIcon={<SaveIcon />} onClick={saveJiraSettings}>
                  Save Jira Settings
                </Button>
              </Box>
            </Grid>
          </Grid>
        </TabPanel>

        <TabPanel value={tabValue} index={3}>
          <OptionalIntegrations
            connectedIntegrations={{
              confluence: confluenceHasToken,
              github: githubHasToken,
              gitlab: gitlabHasToken,
              testrail: testrailHasToken,
            }}
          >
            <IntegrationCard
              title="Confluence Configuration"
              description="Connect to Confluence for documentation and requirements tracking"
              fields={[
                {
                  name: 'baseUrl',
                  label: 'Confluence Base URL',
                  value: confluenceSettings.baseUrl,
                  onChange: (val) => handleConfluenceSettingsChange('baseUrl', val),
                  placeholder: 'https://company.atlassian.net/wiki',
                  helperText: 'Your Confluence instance URL',
                },
                {
                  name: 'email',
                  label: 'Email',
                  type: 'email',
                  value: confluenceSettings.email,
                  onChange: (val) => handleConfluenceSettingsChange('email', val),
                  helperText: 'Your Confluence account email',
                },
                {
                  name: 'apiToken',
                  label: 'API Token',
                  type: 'password',
                  value: confluenceSettings.apiToken,
                  onChange: (val) => handleConfluenceSettingsChange('apiToken', val),
                  placeholder: confluenceHasToken ? '•••••••• (stored)' : 'Enter token',
                  helperText: confluenceHasToken
                    ? 'Leave empty to keep the stored token (hidden for security)'
                    : 'Same as Jira token if using Atlassian Cloud',
                },
              ]}
              hasToken={confluenceHasToken}
              onSave={saveConfluenceSettings}
              onTest={testConfluenceConnectionHandler}
            />

            <IntegrationCard
              title="GitHub Configuration"
              description="Link pull requests and commits to Jira tasks"
              fields={[
                {
                  name: 'baseUrl',
                  label: 'Base URL (optional)',
                  value: githubSettings.baseUrl,
                  onChange: (val) => setGithubSettings({ ...githubSettings, baseUrl: val }),
                  placeholder: 'https://api.github.com',
                },
                {
                  name: 'apiToken',
                  label: 'API Token',
                  type: 'password',
                  value: githubSettings.apiToken,
                  onChange: (val) => setGithubSettings({ ...githubSettings, apiToken: val }),
                  placeholder: githubHasToken ? '•••••••• (stored)' : 'Enter token',
                  helperText: githubHasToken
                    ? 'Leave empty to keep the stored token (hidden for security)'
                    : 'Personal Access Token',
                },
                {
                  name: 'webhookSecret',
                  label: 'Webhook Secret',
                  type: 'password',
                  value: githubSettings.webhookSecret,
                  onChange: (val) => setGithubSettings({ ...githubSettings, webhookSecret: val }),
                  placeholder: githubHasToken ? '•••••••• (stored)' : 'Enter secret',
                  helperText: 'Used to validate GitHub webhooks',
                },
              ]}
              hasToken={githubHasToken}
              onSave={async () => {
                const r = await putGithubSettings({
                  baseUrl: githubSettings.baseUrl || undefined,
                  apiToken: githubSettings.apiToken || undefined,
                  webhookSecret: githubSettings.webhookSecret || undefined,
                });
                setGithubHasToken(!!r.has_token);
                setMessage({ type: 'success', text: 'GitHub settings saved' });
              }}
              onTest={testGithubConnectionHandler}
            />

            <IntegrationCard
              title="GitLab Configuration"
              description="Link merge requests and commits to Jira tasks"
              fields={[
                {
                  name: 'baseUrl',
                  label: 'GitLab Base URL',
                  value: gitlabSettings.baseUrl,
                  onChange: (val) => setGitlabSettings({ ...gitlabSettings, baseUrl: val }),
                  placeholder: 'https://gitlab.example.com',
                },
                {
                  name: 'apiToken',
                  label: 'API Token',
                  type: 'password',
                  value: gitlabSettings.apiToken,
                  onChange: (val) => setGitlabSettings({ ...gitlabSettings, apiToken: val }),
                  placeholder: gitlabHasToken ? '•••••••• (stored)' : 'Enter token',
                  helperText: gitlabHasToken
                    ? 'Leave empty to keep the stored token (hidden for security)'
                    : 'Personal Access Token or Project Token',
                },
                {
                  name: 'webhookSecret',
                  label: 'Webhook Secret',
                  type: 'password',
                  value: gitlabSettings.webhookSecret,
                  onChange: (val) => setGitlabSettings({ ...gitlabSettings, webhookSecret: val }),
                  placeholder: gitlabHasToken ? '•••••••• (stored)' : 'Enter secret',
                  helperText: 'Used to validate GitLab webhooks',
                },
              ]}
              hasToken={gitlabHasToken}
              onSave={async () => {
                const r = await putGitlabSettings({
                  baseUrl: gitlabSettings.baseUrl || undefined,
                  apiToken: gitlabSettings.apiToken || undefined,
                  webhookSecret: gitlabSettings.webhookSecret || undefined,
                });
                setGitlabHasToken(!!r.has_token);
                setMessage({ type: 'success', text: 'GitLab settings saved' });
              }}
              onTest={testGitlabConnectionHandler}
            />

            <IntegrationCard
              title="TestRail Configuration"
              description="Sync test cases and results with Jira"
              fields={[
                {
                  name: 'baseUrl',
                  label: 'TestRail URL',
                  value: testrailSettings.baseUrl,
                  onChange: (val) => setTestrailSettings({ ...testrailSettings, baseUrl: val }),
                  placeholder: 'https://your.testrail.io',
                },
                {
                  name: 'email',
                  label: 'User (email)',
                  value: testrailSettings.email,
                  onChange: (val) => setTestrailSettings({ ...testrailSettings, email: val }),
                },
                {
                  name: 'apiToken',
                  label: 'API Key',
                  type: 'password',
                  value: testrailSettings.apiToken,
                  onChange: (val) => setTestrailSettings({ ...testrailSettings, apiToken: val }),
                  placeholder: testrailHasToken ? '?'.repeat(12) : 'Enter API key',
                  helperText: testrailHasToken
                    ? 'Leave empty to keep the stored key (hidden for security)'
                    : 'Generate in TestRail user settings',
                },
              ]}
              hasToken={testrailHasToken}
              onSave={async () => {
                try {
                  const r = await putTestrailSettings({
                    baseUrl: testrailSettings.baseUrl || undefined,
                    email: testrailSettings.email || undefined,
                    apiToken: testrailSettings.apiToken || undefined,
                  });
                  setTestrailHasToken(!!r.has_token);
                  setMessage({ type: 'success', text: 'TestRail settings saved' });
                } catch {
                  setMessage({ type: 'error', text: 'Failed to save TestRail settings.' });
                }
              }}
              onTest={testTestrailConnectionHandler}
              isLast
            />
          </OptionalIntegrations>
        </TabPanel>

        <TabPanel value={tabValue} index={4}>
          <ConfluenceSpaceMapping />
        </TabPanel>

        <TabPanel value={tabValue} index={1}>
          <Typography variant="h6" gutterBottom>
            Notification Preferences
          </Typography>
          <Grid container spacing={3}>
            <Grid item xs={12}>
              <FormControlLabel
                control={
                  <Switch
                    checked={notificationSettings.emailNotifications}
                    onChange={(e) => handleNotificationChange('emailNotifications', e.target.checked)}
                  />
                }
                label="Email Notifications"
              />
              <Typography variant="body2" color="text.secondary">
                Receive email notifications for important updates
              </Typography>
            </Grid>
            <Grid item xs={12}>
              <FormControlLabel
                control={
                  <Switch
                    checked={notificationSettings.slackNotifications}
                    onChange={(e) => handleNotificationChange('slackNotifications', e.target.checked)}
                  />
                }
                label="Slack Notifications"
              />
              <Typography variant="body2" color="text.secondary">
                Send notifications to Slack workspace
              </Typography>
            </Grid>
            <Grid item xs={12}>
              <FormControlLabel
                control={
                  <Switch
                    checked={notificationSettings.riskAlerts}
                    onChange={(e) => handleNotificationChange('riskAlerts', e.target.checked)}
                  />
                }
                label="Risk Alerts"
              />
              <Typography variant="body2" color="text.secondary">
                Get notified when risks are detected in projects
              </Typography>
            </Grid>
            <Grid item xs={12}>
              <FormControlLabel
                control={
                  <Switch
                    checked={notificationSettings.dailyReports}
                    onChange={(e) => handleNotificationChange('dailyReports', e.target.checked)}
                  />
                }
                label="Daily Reports"
              />
              <Typography variant="body2" color="text.secondary">
                Receive daily project status reports
              </Typography>
            </Grid>
            <Grid item xs={12}>
              <Button variant="contained" startIcon={<SaveIcon />} onClick={saveNotificationSettings}>
                Save Notification Settings
              </Button>
            </Grid>
          </Grid>
        </TabPanel>

        <TabPanel value={tabValue} index={0}>
          <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
            <Typography variant="h6">
              General Settings
            </Typography>
            {smartDefaults && (
              <Chip
                icon={<AutoAwesomeIcon />}
                label="Smart Defaults Applied"
                color="success"
                size="small"
              />
            )}
          </Box>

          <Alert severity="info" sx={{ mb: 3 }}>
            <Typography variant="body2">
              <strong>Smart Defaults:</strong> Values below are automatically detected from your
              browser and project data. You can adjust them if needed.
            </Typography>
          </Alert>

          <Grid container spacing={3}>
            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                label="Default Sprint Duration"
                type="number"
                value={generalSettings.sprintDuration}
                onChange={(e) =>
                  handleGeneralSettingsChange(
                    'sprintDuration',
                    parseInt(e.target.value) || 14
                  )
                }
                helperText={
                  smartDefaults
                    ? `Auto-detected from project history (${smartDefaults.sprintDuration} days)`
                    : "Default sprint duration in days"
                }
                InputProps={{
                  endAdornment: smartDefaults && (
                    <AutoAwesomeIcon fontSize="small" color="action" sx={{ mr: 1 }} />
                  ),
                }}
              />
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                label="Working Hours per Day"
                type="number"
                value={generalSettings.workingHoursPerDay}
                onChange={(e) =>
                  handleGeneralSettingsChange(
                    'workingHoursPerDay',
                    parseInt(e.target.value) || 8
                  )
                }
                helperText="Standard workday for time calculations"
              />
            </Grid>
            <Grid item xs={12} sm={6}>
              <FormControl fullWidth>
                <InputLabel id="currency-select-label">Currency</InputLabel>
                <Select
                  labelId="currency-select-label"
                  label="Currency"
                  value={generalSettings.currency}
                  onChange={(e) => handleGeneralSettingsChange('currency', e.target.value)}
                  endAdornment={
                    smartDefaults ? (
                      <InputAdornment position="end" sx={{ mr: 3 }}>
                        <AutoAwesomeIcon fontSize="small" color="action" />
                      </InputAdornment>
                    ) : undefined
                  }
                >
                  {/* Preserve a previously saved value that isn't in the common list */}
                  {generalSettings.currency &&
                    !CURRENCY_OPTIONS.some((c) => c.code === generalSettings.currency) && (
                      <MenuItem value={generalSettings.currency}>
                        {generalSettings.currency}
                      </MenuItem>
                    )}
                  {CURRENCY_OPTIONS.map((c) => (
                    <MenuItem key={c.code} value={c.code}>
                      {c.label}
                    </MenuItem>
                  ))}
                </Select>
                <FormHelperText>
                  {smartDefaults
                    ? `Detected from browser locale (${smartDefaults.currency})`
                    : 'Currency for budget calculations'}
                </FormHelperText>
              </FormControl>
            </Grid>
            <Grid item xs={12} sm={6}>
              <Autocomplete
                options={
                  generalSettings.timezone &&
                  !timezoneOptions.includes(generalSettings.timezone)
                    ? [generalSettings.timezone, ...timezoneOptions]
                    : timezoneOptions
                }
                value={generalSettings.timezone || null}
                onChange={(_, newValue) =>
                  handleGeneralSettingsChange('timezone', newValue ?? '')
                }
                autoHighlight
                renderInput={(params) => (
                  <TextField
                    {...params}
                    label="Timezone"
                    helperText={
                      smartDefaults
                        ? `Detected from browser (${smartDefaults.timezone})`
                        : 'Your local timezone'
                    }
                  />
                )}
              />
            </Grid>
            <Grid item xs={12}>
              <Divider sx={{ my: 3 }} />
              <Button variant="contained" startIcon={<SaveIcon />} onClick={saveGeneralSettings}>
                Save General Settings
              </Button>
            </Grid>
          </Grid>
        </TabPanel>
      </Card>
    </Box>
  );
};

export default Settings;
