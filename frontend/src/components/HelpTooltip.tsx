import React from 'react';
import { Tooltip, IconButton, Box, Typography } from '@mui/material';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';

interface HelpTooltipProps {
  title: string;
  description?: string;
  icon?: 'help' | 'info';
  placement?: 'top' | 'bottom' | 'left' | 'right';
  size?: 'small' | 'medium';
}

const HelpTooltipComponent: React.FC<HelpTooltipProps> = ({
  title,
  description,
  icon = 'help',
  placement = 'top',
  size = 'small',
}) => {
  const tooltipContent = description ? (
    <Box>
      <Typography variant="body2" fontWeight={600} gutterBottom>
        {title}
      </Typography>
      <Typography variant="body2" sx={{ whiteSpace: 'pre-line' }}>
        {description}
      </Typography>
    </Box>
  ) : (
    title
  );

  return (
    <Tooltip
      title={tooltipContent}
      placement={placement}
      arrow
      enterDelay={200}
      leaveDelay={0}
    >
      <IconButton
        size={size}
        sx={{
          color: 'action.active',
          '&:hover': {
            color: 'primary.main',
            backgroundColor: 'action.hover',
          },
          ml: 0.5,
        }}
      >
        {icon === 'info' ? (
          <InfoOutlinedIcon fontSize={size} />
        ) : (
          <HelpOutlineIcon fontSize={size} />
        )}
      </IconButton>
    </Tooltip>
  );
};

HelpTooltipComponent.displayName = 'HelpTooltip';

export const HelpTooltip = React.memo(HelpTooltipComponent);
