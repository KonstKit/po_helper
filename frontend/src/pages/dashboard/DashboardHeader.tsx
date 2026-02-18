import React from 'react';
import { Box, Button, Typography } from '@mui/material';

interface DashboardHeaderProps {
  hasProject: boolean;
  onOpenProjectDetails?: () => void;
}

const DashboardHeader: React.FC<DashboardHeaderProps> = ({ hasProject, onOpenProjectDetails }) => (
  <Box data-testid="dashboard-header" display="flex" justifyContent="space-between" alignItems="center" mb={3}>
    <Typography variant="h4" fontWeight={700}>
      Dashboard
    </Typography>
    {hasProject && onOpenProjectDetails && (
      <Button
        data-testid="dashboard-view-details"
        variant="outlined"
        size="small"
        onClick={onOpenProjectDetails}
      >
        View Details
      </Button>
    )}
  </Box>
);

DashboardHeader.displayName = 'DashboardHeader';

export default React.memo(DashboardHeader);
