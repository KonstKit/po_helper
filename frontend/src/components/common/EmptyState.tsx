import React from 'react';
import { Box, Typography, Stack, Paper } from '@mui/material';
import InboxOutlinedIcon from '@mui/icons-material/InboxOutlined';

export interface EmptyStateProps {
  /** Large illustrative icon. Defaults to an inbox glyph. */
  icon?: React.ReactNode;
  /** Headline, e.g. "No review items yet". */
  title: string;
  /** Supporting sentence explaining the state / why it is empty. */
  description?: React.ReactNode;
  /** Optional ordered "how to get started" steps (the Quality/Testing pattern). */
  steps?: React.ReactNode[];
  /** Optional call-to-action buttons (e.g. <Button>Setup GitHub</Button>). */
  actions?: React.ReactNode;
  /** Render inside a bordered Paper card (default true) or bare. */
  bordered?: boolean;
  /** Compact spacing for inline/table empty states. */
  dense?: boolean;
}

/**
 * Standardized empty-state used across the app (UX review M4 / theme 03).
 *
 * Review and Knowledge previously showed bare "No rows" plaques with no path
 * forward, while Quality/Testing set the gold standard (icon, title, numbered
 * setup steps, explicit CTAs). This component generalizes that gold standard so
 * every empty surface tells the user what is happening and what to do next.
 */
export default function EmptyState({
  icon,
  title,
  description,
  steps,
  actions,
  bordered = true,
  dense = false,
}: EmptyStateProps) {
  const content = (
    <Stack
      spacing={dense ? 1 : 2}
      alignItems="center"
      textAlign="center"
      sx={{ py: dense ? 3 : 6, px: 3, mx: 'auto', maxWidth: 520 }}
    >
      <Box sx={{ color: 'text.disabled', '& svg': { fontSize: dense ? 40 : 56 } }}>
        {icon ?? <InboxOutlinedIcon fontSize="inherit" />}
      </Box>
      <Typography variant={dense ? 'subtitle1' : 'h6'} fontWeight={600}>
        {title}
      </Typography>
      {description && (
        <Typography variant="body2" color="text.secondary">
          {description}
        </Typography>
      )}
      {steps && steps.length > 0 && (
        <Box
          component="ol"
          sx={{
            textAlign: 'left',
            m: 0,
            pl: 3,
            color: 'text.secondary',
            '& li': { mb: 0.5 },
          }}
        >
          {steps.map((step, i) => (
            <Typography component="li" variant="body2" key={i}>
              {step}
            </Typography>
          ))}
        </Box>
      )}
      {actions && (
        <Stack direction="row" spacing={1.5} flexWrap="wrap" justifyContent="center" sx={{ pt: 1 }}>
          {actions}
        </Stack>
      )}
    </Stack>
  );

  if (!bordered) return content;
  return (
    <Paper variant="outlined" sx={{ borderStyle: 'dashed', bgcolor: 'transparent' }}>
      {content}
    </Paper>
  );
}
