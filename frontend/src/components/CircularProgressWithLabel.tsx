import React from 'react';
import { Box, CircularProgress, Typography } from '@mui/material';

type Props = {
  value?: number; // 0..100; if undefined, show indeterminate
  label?: string;
  size?: number;
};

const CircularProgressWithLabel: React.FC<Props> = ({ value, label, size = 64 }) => {
  const determinate = typeof value === 'number' && !Number.isNaN(value);
  const clamped = determinate ? Math.max(0, Math.min(100, value as number)) : undefined;
  return (
    <Box display="inline-flex" flexDirection="column" alignItems="center" justifyContent="center">
      <Box position="relative" display="inline-flex">
        <CircularProgress variant={determinate ? 'determinate' : 'indeterminate'} value={clamped} size={size} />
        {determinate && (
          <Box
            top={0}
            left={0}
            bottom={0}
            right={0}
            position="absolute"
            display="flex"
            alignItems="center"
            justifyContent="center"
          >
            <Typography variant="caption" component="div" color="text.secondary">
              {`${Math.round(clamped!)}%`}
            </Typography>
          </Box>
        )}
      </Box>
      {label && (
        <Typography variant="caption" color="text.secondary" sx={{ mt: 1, maxWidth: 320, textAlign: 'center' }}>
          {label}
        </Typography>
      )}
    </Box>
  );
};

export default CircularProgressWithLabel;

