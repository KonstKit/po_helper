import React, { ReactNode } from 'react';
import { Box, Button, Paper, Typography, Stack } from '@mui/material';

export interface EmptyStateAction {
  label: string;
  onClick: () => void;
  variant?: 'contained' | 'outlined' | 'text';
}

export interface EmptyStateProps {
  icon: ReactNode;
  title: string;
  description: string | ReactNode;
  primaryAction?: EmptyStateAction;
  secondaryAction?: EmptyStateAction;
  benefits?: string[];
  setupSteps?: string[];
}

const EmptyState: React.FC<EmptyStateProps> = ({
  icon,
  title,
  description,
  primaryAction,
  secondaryAction,
  benefits,
  setupSteps,
}) => {
  return (
    <Paper
      elevation={0}
      sx={{
        border: '1px solid',
        borderColor: 'divider',
        borderRadius: 2,
        p: 4,
        textAlign: 'center',
        backgroundColor: 'background.paper',
      }}
    >
      <Box
        sx={{
          fontSize: '3rem',
          mb: 2,
          color: 'text.secondary',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
        }}
      >
        {icon}
      </Box>

      <Typography variant="h5" gutterBottom sx={{ fontWeight: 600, mb: 1 }}>
        {title}
      </Typography>

      <Typography
        variant="body1"
        color="text.secondary"
        sx={{ mb: 3, maxWidth: 600, mx: 'auto' }}
      >
        {description}
      </Typography>

      {setupSteps && setupSteps.length > 0 && (
        <Box sx={{ mb: 3, textAlign: 'left', maxWidth: 600, mx: 'auto' }}>
          <Typography variant="subtitle2" gutterBottom sx={{ fontWeight: 600 }}>
            Setup Required:
          </Typography>
          <Stack spacing={1} component="ol" sx={{ pl: 2 }}>
            {setupSteps.map((step, index) => (
              <Typography
                key={index}
                component="li"
                variant="body2"
                color="text.secondary"
              >
                {step}
              </Typography>
            ))}
          </Stack>
        </Box>
      )}

      <Stack
        direction="row"
        spacing={2}
        justifyContent="center"
        sx={{ mb: benefits && benefits.length > 0 ? 3 : 0 }}
      >
        {primaryAction && (
          <Button
            variant={primaryAction.variant || 'contained'}
            onClick={primaryAction.onClick}
            size="large"
          >
            {primaryAction.label}
          </Button>
        )}
        {secondaryAction && (
          <Button
            variant={secondaryAction.variant || 'outlined'}
            onClick={secondaryAction.onClick}
            size="large"
          >
            {secondaryAction.label}
          </Button>
        )}
      </Stack>

      {benefits && benefits.length > 0 && (
        <Box sx={{ mt: 3, textAlign: 'left', maxWidth: 600, mx: 'auto' }}>
          <Typography variant="subtitle2" gutterBottom sx={{ fontWeight: 600 }}>
            What you'll get:
          </Typography>
          <Stack spacing={1}>
            {benefits.map((benefit, index) => (
              <Box
                key={index}
                sx={{ display: 'flex', alignItems: 'flex-start' }}
              >
                <Box component="span" sx={{ mr: 1, color: 'success.main' }}>
                  ✓
                </Box>
                <Typography
                  variant="body2"
                  color="text.secondary"
                  component="span"
                >
                  {benefit}
                </Typography>
              </Box>
            ))}
          </Stack>
        </Box>
      )}
    </Paper>
  );
};

EmptyState.displayName = 'EmptyState';

export default React.memo(EmptyState);
