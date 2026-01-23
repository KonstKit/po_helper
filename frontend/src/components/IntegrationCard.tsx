import React from 'react';
import {
  Box,
  Typography,
  TextField,
  Button,
  Grid,
  Divider,
} from '@mui/material';
import { Save as SaveIcon, Science as TestIcon } from '@mui/icons-material';

interface IntegrationCardProps {
  title: string;
  description?: string;
  fields: Array<{
    name: string;
    label: string;
    type?: string;
    value: string;
    onChange: (value: string) => void;
    placeholder?: string;
    helperText?: string;
    disabled?: boolean;
  }>;
  hasToken?: boolean;
  onSave: () => void;
  onTest?: () => void;
  isLast?: boolean;
}

export const IntegrationCard: React.FC<IntegrationCardProps> = ({
  title,
  description,
  fields,
  hasToken,
  onSave,
  onTest,
  isLast,
}) => {
  return (
    <Box mb={isLast ? 0 : 4}>
      <Typography variant="h6" gutterBottom>
        {title}
      </Typography>
      {description && (
        <Typography variant="body2" color="text.secondary" gutterBottom sx={{ mb: 2 }}>
          {description}
        </Typography>
      )}
      <Grid container spacing={3}>
        {fields.map((field, idx) => (
          <Grid item xs={12} sm={field.name === 'baseUrl' ? 12 : 6} key={idx}>
            <TextField
              fullWidth
              label={field.label}
              type={field.type || 'text'}
              value={field.value}
              onChange={(e) => field.onChange(e.target.value)}
              placeholder={field.placeholder}
              helperText={field.helperText}
              disabled={field.disabled}
            />
            {field.type === 'password' && hasToken && !field.value && (
              <Typography variant="caption" color="text.secondary">
                Token is saved on server and hidden for security
              </Typography>
            )}
          </Grid>
        ))}
        <Grid item xs={12}>
          <Box display="flex" gap={2}>
            {onTest && (
              <Button variant="outlined" startIcon={<TestIcon />} onClick={onTest}>
                Test Connection
              </Button>
            )}
            <Button variant="contained" startIcon={<SaveIcon />} onClick={onSave}>
              Save {title}
            </Button>
          </Box>
        </Grid>
      </Grid>
      {!isLast && <Divider sx={{ mt: 4 }} />}
    </Box>
  );
};
