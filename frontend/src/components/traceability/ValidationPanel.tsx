import React from 'react';
import {
  Box,
  Alert,
  AlertTitle,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Collapse,
  Button,
  Paper,
} from '@mui/material';
import {
  Error as ErrorIcon,
  Warning as WarningIcon,
  ExpandMore as ExpandIcon,
  ExpandLess as CollapseIcon,
} from '@mui/icons-material';
import { ValidationResult } from '../../utils/ruleValidation';

interface ValidationPanelProps {
  validation: ValidationResult;
  onNodeClick?: (nodeId: string) => void;
}

const ValidationPanel: React.FC<ValidationPanelProps> = ({ validation, onNodeClick }) => {
  const [showErrors, setShowErrors] = React.useState(true);
  const [showWarnings, setShowWarnings] = React.useState(true);

  if (validation.valid && validation.warnings.length === 0) {
    return (
      <Alert data-testid="validation-panel" severity="success" sx={{ m: 2 }}>
        <AlertTitle>Rule is Valid</AlertTitle>
        This rule has no errors or warnings and is ready to use.
      </Alert>
    );
  }

  return (
    <Paper data-testid="validation-panel" sx={{ m: 2, p: 2 }}>
      <Box sx={{ mb: 2 }}>
        {validation.errors.length > 0 && (
          <>
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                mb: 1,
                cursor: 'pointer',
              }}
              onClick={() => setShowErrors(!showErrors)}
            >
              <Alert severity="error" sx={{ flex: 1, mr: 1 }}>
                <AlertTitle>
                  {validation.errors.length} Error{validation.errors.length !== 1 ? 's' : ''}
                </AlertTitle>
              </Alert>
              <Button size="small">
                {showErrors ? <CollapseIcon /> : <ExpandIcon />}
              </Button>
            </Box>
            <Collapse in={showErrors}>
              <List dense>
                {validation.errors.map((error, index) => (
                  <ListItem
                    key={index}
                    sx={{
                      bgcolor: 'error.lighter',
                      mb: 1,
                      borderRadius: 1,
                      cursor: error.nodeId ? 'pointer' : 'default',
                    }}
                    onClick={() => error.nodeId && onNodeClick?.(error.nodeId)}
                  >
                    <ListItemIcon>
                      <ErrorIcon color="error" />
                    </ListItemIcon>
                    <ListItemText
                      primary={error.message}
                      secondary={error.nodeId ? `Node: ${error.nodeId}` : undefined}
                    />
                  </ListItem>
                ))}
              </List>
            </Collapse>
          </>
        )}

        {validation.warnings.length > 0 && (
          <>
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                mb: 1,
                cursor: 'pointer',
                mt: validation.errors.length > 0 ? 2 : 0,
              }}
              onClick={() => setShowWarnings(!showWarnings)}
            >
              <Alert severity="warning" sx={{ flex: 1, mr: 1 }}>
                <AlertTitle>
                  {validation.warnings.length} Warning{validation.warnings.length !== 1 ? 's' : ''}
                </AlertTitle>
              </Alert>
              <Button size="small">
                {showWarnings ? <CollapseIcon /> : <ExpandIcon />}
              </Button>
            </Box>
            <Collapse in={showWarnings}>
              <List dense>
                {validation.warnings.map((warning, index) => (
                  <ListItem
                    key={index}
                    sx={{
                      bgcolor: 'warning.lighter',
                      mb: 1,
                      borderRadius: 1,
                      cursor: warning.nodeId ? 'pointer' : 'default',
                    }}
                    onClick={() => warning.nodeId && onNodeClick?.(warning.nodeId)}
                  >
                    <ListItemIcon>
                      <WarningIcon color="warning" />
                    </ListItemIcon>
                    <ListItemText
                      primary={warning.message}
                      secondary={warning.nodeId ? `Node: ${warning.nodeId}` : undefined}
                    />
                  </ListItem>
                ))}
              </List>
            </Collapse>
          </>
        )}
      </Box>
    </Paper>
  );
};

export default ValidationPanel;
