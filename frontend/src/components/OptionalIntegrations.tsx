import React, { useState } from 'react';
import {
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Box,
  Typography,
  Chip,
  Stack,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import RadioButtonUncheckedIcon from '@mui/icons-material/RadioButtonUnchecked';

interface OptionalIntegrationsProps {
  children: React.ReactNode;
  connectedIntegrations: {
    confluence: boolean;
    github: boolean;
    gitlab: boolean;
    testrail: boolean;
  };
}

export const OptionalIntegrations: React.FC<OptionalIntegrationsProps> = ({
  children,
  connectedIntegrations,
}) => {
  const [expanded, setExpanded] = useState(false);

  const connectedCount = Object.values(connectedIntegrations).filter(Boolean).length;
  const totalCount = Object.keys(connectedIntegrations).length;

  return (
    <Accordion
      expanded={expanded}
      onChange={() => setExpanded(!expanded)}
      sx={{
        border: '1px solid',
        borderColor: 'divider',
        boxShadow: 'none',
        '&:before': { display: 'none' },
        mb: 2,
      }}
    >
      <AccordionSummary
        expandIcon={<ExpandMoreIcon />}
        sx={{
          backgroundColor: 'action.hover',
          '&:hover': {
            backgroundColor: 'action.selected',
          },
        }}
      >
        <Box display="flex" alignItems="center" gap={2} width="100%">
          <Typography variant="subtitle1" fontWeight={500}>
            Optional Integrations
          </Typography>
          <Chip
            label={`${connectedCount}/${totalCount} connected`}
            size="small"
            color={connectedCount > 0 ? 'success' : 'default'}
            variant="outlined"
          />
          <Box flex={1} />
          <Stack direction="row" spacing={1} sx={{ mr: 2 }}>
            {Object.entries(connectedIntegrations).map(([name, connected]) => (
              <Chip
                key={name}
                label={name.charAt(0).toUpperCase() + name.slice(1)}
                size="small"
                icon={
                  connected ? (
                    <CheckCircleIcon fontSize="small" />
                  ) : (
                    <RadioButtonUncheckedIcon fontSize="small" />
                  )
                }
                color={connected ? 'success' : 'default'}
                variant={connected ? 'filled' : 'outlined'}
              />
            ))}
          </Stack>
        </Box>
      </AccordionSummary>
      <AccordionDetails sx={{ pt: 3 }}>
        <Typography variant="body2" color="text.secondary" gutterBottom sx={{ mb: 3 }}>
          These integrations enhance your workflow but are not required. Configure only what you need.
        </Typography>
        {children}
      </AccordionDetails>
    </Accordion>
  );
};
