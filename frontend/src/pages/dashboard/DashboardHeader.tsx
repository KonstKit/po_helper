import React from 'react';
import { Box, Button, Typography } from '@mui/material';
import { DASHBOARD_TEST_IDS } from './dashboardContract';

interface DashboardHeaderProps {
  hasProject: boolean;
  onOpenProjectDetails?: () => void;
}

const DashboardHeader: React.FC<DashboardHeaderProps> = ({ hasProject, onOpenProjectDetails }) => (
  <Box
    data-testid={DASHBOARD_TEST_IDS.header}
    display="flex"
    justifyContent="space-between"
    alignItems="center"
    mb={3}
  >
    <Typography variant="h4" fontWeight={700}>
      Dashboard
    </Typography>
    {hasProject && onOpenProjectDetails && (
      <Button
        data-testid={DASHBOARD_TEST_IDS.viewDetails}
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
