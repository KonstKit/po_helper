import React, { useState } from 'react';
import {
  Box,
  Paper,
  Typography,
  Button,
  TextField,
  Alert,
  LinearProgress,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Collapse,
  IconButton,
  Chip,
} from '@mui/material';
import {
  CheckCircle as CheckIcon,
  Cancel as CancelIcon,
  AutoFixHigh as AutoFixIcon,
  Settings as ManualIcon,
  Help as HelpIcon,
} from '@mui/icons-material';

interface QuickSetupPanelProps {
  projectKey: string;
  onProjectKeyChange: (key: string) => void;
  onAutoMap: () => Promise<void>;
  onManualSetup: () => void;
  mappedFields: {
    sprint: boolean;
    storyPoints: boolean;
    epicLink: boolean;
    businessValue: boolean;
  };
  isCalibrating: boolean;
}

type MappedFieldKey = keyof QuickSetupPanelProps['mappedFields'];

const ESSENTIAL_FIELDS: Array<{
  key: MappedFieldKey;
  label: string;
  description: string;
  required: boolean;
}> = [
  {
    key: 'sprint',
    label: 'Sprint',
    description: 'Required for burndown charts',
    required: true,
  },
  {
    key: 'storyPoints',
    label: 'Story Points',
    description: 'Required for velocity tracking',
    required: true,
  },
  {
    key: 'epicLink',
    label: 'Epic Link',
    description: 'Optional, enables epic views',
    required: false,
  },
  {
    key: 'businessValue',
    label: 'Business Value',
    description: 'Optional, enables ROI metrics',
    required: false,
  },
];

export const QuickSetupPanel: React.FC<QuickSetupPanelProps> = ({
  projectKey,
  onProjectKeyChange,
  onAutoMap,
  onManualSetup,
  mappedFields,
  isCalibrating,
}) => {
  const [showHelp, setShowHelp] = useState(false);

  const requiredFieldsMapped = mappedFields.sprint && mappedFields.storyPoints;
  const allFieldsMapped = Object.values(mappedFields).every((v) => v);
  const completionPercentage = Math.round(
    (Object.values(mappedFields).filter((v) => v).length / 4) * 100
  );

  return (
    <Paper variant="outlined" sx={{ p: 3, mb: 3, bgcolor: 'background.paper', borderColor: 'divider' }}>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h6" fontWeight={600} color="primary.main">
          Quick Setup (Recommended)
        </Typography>
        <IconButton onClick={() => setShowHelp(!showHelp)} size="small" color="primary">
          <HelpIcon />
        </IconButton>
      </Box>

      <Collapse in={showHelp}>
        <Alert severity="info" sx={{ mb: 2 }}>
          <Typography variant="body2" gutterBottom>
            <strong>Quick Setup automatically maps common Jira fields:</strong>
          </Typography>
          <Typography variant="body2" component="div">
            - <strong>Sprint:</strong> Links tasks to sprints for burndown tracking
            <br />
            - <strong>Story Points:</strong> Enables velocity calculation
            <br />
            - <strong>Epic Link:</strong> Groups tasks by epic
            <br />
            - <strong>Business Value:</strong> Tracks ROI
          </Typography>
        </Alert>
      </Collapse>

      {/* Progress Bar */}
      <Box mb={2}>
        <Box display="flex" justifyContent="space-between" mb={1}>
          <Typography variant="body2">Field Mapping Progress</Typography>
          <Typography variant="body2" fontWeight={600}>
            {completionPercentage}%
          </Typography>
        </Box>
        <LinearProgress
          variant="determinate"
          value={completionPercentage}
          sx={{ height: 8, borderRadius: 4 }}
        />
      </Box>

      {/* Essential Fields Status */}
      <Box mb={3}>
        <Typography variant="subtitle2" gutterBottom>
          Essential Fields
        </Typography>
        <List dense sx={{ bgcolor: 'background.default', borderRadius: 1 }}>
          {ESSENTIAL_FIELDS.map((field) => {
            const isMapped = mappedFields[field.key];
            return (
              <ListItem key={field.key}>
                <ListItemIcon>
                  {isMapped ? (
                    <CheckIcon color="success" />
                  ) : (
                    <CancelIcon color={field.required ? 'error' : 'disabled'} />
                  )}
                </ListItemIcon>
                <ListItemText
                  primary={
                    <Box display="flex" alignItems="center" gap={1}>
                      {field.label}
                      {field.required && (
                        <Chip label="Required" size="small" color="error" sx={{ height: 18 }} />
                      )}
                    </Box>
                  }
                  secondary={field.description}
                />
              </ListItem>
            );
          })}
        </List>
      </Box>

      {/* Auto-Map Section */}
      <Box display="flex" gap={2} alignItems="flex-start">
        <TextField
          label="Project Key"
          placeholder="e.g., WABA, PROJ"
          value={projectKey}
          onChange={(e) => onProjectKeyChange(e.target.value.toUpperCase())}
          size="small"
          sx={{ flex: '0 0 200px', bgcolor: 'background.paper' }}
          helperText="We'll analyze this project"
        />
        <Box flex={1} display="flex" gap={1}>
          <Button
            variant="contained"
            color="secondary"
            startIcon={<AutoFixIcon />}
            onClick={onAutoMap}
            disabled={!projectKey || isCalibrating}
            fullWidth
          >
            {isCalibrating ? 'Auto-Mapping...' : 'Auto-Map Common Fields'}
          </Button>
          <Button
            variant="outlined"
            startIcon={<ManualIcon />}
            onClick={onManualSetup}
            sx={{ minWidth: 140 }}
          >
            Manual Setup
          </Button>
        </Box>
      </Box>

      {isCalibrating && (
        <Box mt={2}>
          <LinearProgress />
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            Analyzing {projectKey} issues to detect field types...
          </Typography>
        </Box>
      )}

      {requiredFieldsMapped && (
        <Alert severity="success" sx={{ mt: 2 }}>
          <Typography variant="body2" fontWeight={600}>
            All required fields mapped!
          </Typography>
          <Typography variant="body2">
            {allFieldsMapped
              ? 'Your setup is complete. Analytics features are fully enabled.'
              : 'Basic analytics enabled. Map optional fields for advanced features.'}
          </Typography>
        </Alert>
      )}

      {!requiredFieldsMapped && !isCalibrating && (
        <Alert severity="warning" sx={{ mt: 2 }}>
          <Typography variant="body2">
            <strong>Required fields not mapped.</strong> Enter a project key and click &quot;Auto-Map&quot;
            to get started, or use &quot;Manual Setup&quot; to configure fields yourself.
          </Typography>
        </Alert>
      )}
    </Paper>
  );
};

