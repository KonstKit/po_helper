import React from 'react';
import { Box, Card, CardContent, Grid, Skeleton, Paper } from '@mui/material';

const DashboardSkeleton: React.FC = () => {
  return (
    <Box>
      {/* KPI Bar Skeleton */}
      <Paper
        elevation={0}
        sx={{
          background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
          p: 3,
          mb: 3,
          borderRadius: 2,
        }}
      >
        <Grid container spacing={3}>
          {[1, 2, 3, 4].map((i) => (
            <Grid item xs={12} sm={6} md={3} key={i}>
              <Skeleton
                variant="text"
                width="60%"
                height={20}
                sx={{ bgcolor: 'rgba(255,255,255,0.2)' }}
              />
              <Skeleton
                variant="text"
                width="40%"
                height={48}
                sx={{ bgcolor: 'rgba(255,255,255,0.3)', mt: 1 }}
              />
              <Skeleton
                variant="text"
                width="50%"
                height={16}
                sx={{ bgcolor: 'rgba(255,255,255,0.15)', mt: 1 }}
              />
            </Grid>
          ))}
        </Grid>
      </Paper>

      {/* Main Grid Skeleton */}
      <Grid container spacing={3}>
        {/* Velocity Chart */}
        <Grid item xs={12} md={6}>
          <Card>
            <CardContent>
              <Skeleton variant="text" width="40%" height={32} sx={{ mb: 2 }} />
              <Skeleton variant="rectangular" width="100%" height={250} sx={{ borderRadius: 1 }} />
            </CardContent>
          </Card>
        </Grid>

        {/* Burndown Chart */}
        <Grid item xs={12} md={6}>
          <Card>
            <CardContent>
              <Skeleton variant="text" width="40%" height={32} sx={{ mb: 2 }} />
              <Skeleton variant="rectangular" width="100%" height={250} sx={{ borderRadius: 1 }} />
            </CardContent>
          </Card>
        </Grid>

        {/* Task Distribution */}
        <Grid item xs={12} md={4}>
          <Card>
            <CardContent>
              <Skeleton variant="text" width="60%" height={32} sx={{ mb: 2 }} />
              <Box display="flex" justifyContent="center">
                <Skeleton variant="circular" width={200} height={200} />
              </Box>
            </CardContent>
          </Card>
        </Grid>

        {/* Risk Alerts */}
        <Grid item xs={12} md={4}>
          <Card>
            <CardContent>
              <Skeleton variant="text" width="50%" height={32} sx={{ mb: 2 }} />
              {[1, 2, 3].map((i) => (
                <Box key={i} mb={2}>
                  <Skeleton variant="text" width="30%" height={24} />
                  <Skeleton variant="text" width="90%" height={20} />
                </Box>
              ))}
            </CardContent>
          </Card>
        </Grid>

        {/* Upcoming Tasks */}
        <Grid item xs={12} md={4}>
          <Card>
            <CardContent>
              <Skeleton variant="text" width="50%" height={32} sx={{ mb: 2 }} />
              {[1, 2, 3, 4].map((i) => (
                <Box key={i} mb={1.5} display="flex" gap={1}>
                  <Skeleton variant="circular" width={24} height={24} />
                  <Box flex={1}>
                    <Skeleton variant="text" width="80%" />
                    <Skeleton variant="text" width="40%" height={16} />
                  </Box>
                </Box>
              ))}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
};

DashboardSkeleton.displayName = 'DashboardSkeleton';

export default React.memo(DashboardSkeleton);
