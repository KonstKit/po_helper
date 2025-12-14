import React from 'react';
import {
  Box,
  Drawer,
  Typography,
  IconButton,
  Divider,
  List,
  ListItem,
  ListItemText,
  Chip,
} from '@mui/material';
import { Close as CloseIcon } from '@mui/icons-material';
import { Node } from 'reactflow';

interface PropertiesPanelProps {
  selectedNode: Node | null;
  onClose: () => void;
}

const PropertiesPanel: React.FC<PropertiesPanelProps> = ({ selectedNode, onClose }) => {
  if (!selectedNode) return null;

  const renderNodeProperties = () => {
    const { data } = selectedNode;

    return (
      <Box sx={{ p: 2 }}>
        {/* Node ID */}
        <Typography variant="caption" color="text.secondary">
          Node ID
        </Typography>
        <Typography variant="body2" sx={{ mb: 2 }}>
          {selectedNode.id}
        </Typography>

        {/* Node Type */}
        <Typography variant="caption" color="text.secondary">
          Node Type
        </Typography>
        <Typography variant="body2" sx={{ mb: 2 }}>
          {selectedNode.type}
        </Typography>

        <Divider sx={{ my: 2 }} />

        {/* Node Label */}
        <Typography variant="caption" color="text.secondary">
          Label
        </Typography>
        <Typography variant="body2" sx={{ mb: 2 }}>
          {data.label || 'Untitled'}
        </Typography>

        {/* Filters (for Source nodes) */}
        {data.filters && (
          <>
            <Divider sx={{ my: 2 }} />
            <Typography variant="caption" color="text.secondary">
              Filters
            </Typography>
            <List dense>
              {Object.entries(data.filters).map(([key, value]) => {
                if (!value || (Array.isArray(value) && value.length === 0)) return null;

                const displayValue = Array.isArray(value) ? value.join(', ') : String(value);

                return (
                  <ListItem key={key} sx={{ px: 0 }}>
                    <ListItemText
                      primary={key}
                      secondary={displayValue}
                      primaryTypographyProps={{ variant: 'body2', fontWeight: 500 }}
                      secondaryTypographyProps={{ variant: 'caption' }}
                    />
                  </ListItem>
                );
              })}
            </List>
          </>
        )}

        {/* Config (for Processor/Action nodes) */}
        {data.config && (
          <>
            <Divider sx={{ my: 2 }} />
            <Typography variant="caption" color="text.secondary">
              Configuration
            </Typography>
            <List dense>
              {Object.entries(data.config).map(([key, value]) => {
                if (value === null || value === undefined) return null;

                let displayValue: React.ReactNode;

                if (Array.isArray(value)) {
                  displayValue = value.join(', ');
                } else if (typeof value === 'boolean') {
                  displayValue = (
                    <Chip
                      label={value ? 'Yes' : 'No'}
                      size="small"
                      color={value ? 'success' : 'default'}
                    />
                  );
                } else {
                  displayValue = String(value);
                }

                return (
                  <ListItem key={key} sx={{ px: 0 }}>
                    <ListItemText
                      primary={key}
                      secondary={displayValue}
                      primaryTypographyProps={{ variant: 'body2', fontWeight: 500 }}
                      secondaryTypographyProps={{ variant: 'caption' }}
                    />
                  </ListItem>
                );
              })}
            </List>
          </>
        )}

        {/* Position */}
        <Divider sx={{ my: 2 }} />
        <Typography variant="caption" color="text.secondary">
          Position
        </Typography>
        <Typography variant="body2">
          X: {Math.round(selectedNode.position.x)}, Y: {Math.round(selectedNode.position.y)}
        </Typography>
      </Box>
    );
  };

  return (
    <Drawer
      anchor="right"
      open={!!selectedNode}
      onClose={onClose}
      variant="persistent"
      sx={{
        width: 320,
        flexShrink: 0,
        '& .MuiDrawer-paper': {
          width: 320,
          mt: '64px',
          height: 'calc(100% - 64px)',
        },
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', p: 2, bgcolor: 'background.paper' }}>
        <Typography variant="h6" sx={{ flex: 1 }}>
          Properties
        </Typography>
        <IconButton size="small" onClick={onClose}>
          <CloseIcon />
        </IconButton>
      </Box>
      <Divider />
      {renderNodeProperties()}
    </Drawer>
  );
};

export default PropertiesPanel;
