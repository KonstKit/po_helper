import React from 'react';
import { Box, Card, CardContent, Grid, LinearProgress, Typography } from '@mui/material';
import { Line, Doughnut } from 'react-chartjs-2';
import type { ChartData, ChartOptions } from 'chart.js';
import VelocityChart, { type VelocityDataPoint } from '../../components/VelocityChart';

interface DashboardChartsSectionProps {
  isLoading: boolean;
  hasTasks: boolean;
  showVelocity: boolean;
  showBurndown: boolean;
  showDistribution: boolean;
  velocityData: VelocityDataPoint[];
  targetVelocity?: number;
  velocityShowTrend?: boolean;
  velocityTrendLabel?: string;
  burndownData: ChartData<'line', number[], string>;
  burndownLoading: boolean;
  burndownAvailable: boolean;
  burndownUnavailableMessage: string;
  burndownModeLabel?: string;
  taskDistributionData: ChartData<'doughnut', number[], string>;
  lineChartOptions: ChartOptions<'line'>;
  doughnutChartOptions: ChartOptions<'doughnut'>;
}

const DashboardChartsSection: React.FC<DashboardChartsSectionProps> = ({
  isLoading,
  hasTasks,
  showVelocity,
  showBurndown,
  showDistribution,
  velocityData,
  targetVelocity,
  velocityShowTrend = true,
  velocityTrendLabel,
  burndownData,
  burndownLoading,
  burndownAvailable,
  burndownUnavailableMessage,
  burndownModeLabel,
  taskDistributionData,
  lineChartOptions,
  doughnutChartOptions,
}) => {
  const hasVelocityData = velocityData.some((item) => item.value > 0);
  const hasDistributionData = (taskDistributionData.datasets?.[0]?.data ?? []).some(
    (value) => Number(value) > 0
  );

  return (
    <Grid container spacing={3} data-testid="dashboard-section-charts">
      {showVelocity && (
        <Grid item xs={12} md={showBurndown ? 6 : 12}>
          <Card data-testid="dashboard-chart-velocity">
            <CardContent>
              <Typography variant="h6" gutterBottom fontWeight={600}>
                Weekly Velocity
                {targetVelocity !== undefined && (
                  <Typography component="span" variant="body2" color="text.secondary" sx={{ ml: 1 }}>
                    (Target: {targetVelocity}h)
                  </Typography>
                )}
                {velocityTrendLabel && (
                  <Typography component="span" variant="body2" color="text.secondary" sx={{ ml: 1 }}>
                    (Trend: {velocityTrendLabel})
                  </Typography>
                )}
              </Typography>
              {isLoading ? (
                <Box height={250} display="flex" alignItems="center" justifyContent="center">
                  <LinearProgress sx={{ width: '80%' }} />
                </Box>
              ) : !hasVelocityData ? (
                <Box height={250} display="flex" alignItems="center" justifyContent="center">
                  <Typography variant="body2" color="text.secondary">
                    Not enough sprint completion data to render velocity.
                  </Typography>
                </Box>
              ) : (
                <VelocityChart
                  data={velocityData}
                  targetVelocity={targetVelocity}
                  showTrend={velocityShowTrend}
                  height={250}
                />
              )}
            </CardContent>
          </Card>
        </Grid>
      )}

      {showBurndown && (
        <Grid item xs={12} md={showVelocity ? 6 : 12}>
          <Card data-testid="dashboard-chart-burndown">
            <CardContent>
              <Typography variant="h6" gutterBottom fontWeight={600}>
                Sprint Burndown
                {burndownModeLabel && (
                  <Typography component="span" variant="body2" color="text.secondary" sx={{ ml: 1 }}>
                    ({burndownModeLabel})
                  </Typography>
                )}
              </Typography>
              {burndownLoading ? (
                <Box height={250} display="flex" alignItems="center" justifyContent="center">
                  <LinearProgress sx={{ width: '80%' }} />
                </Box>
              ) : !burndownAvailable ? (
                <Box height={250} display="flex" alignItems="center" justifyContent="center">
                  <Typography variant="body2" color="text.secondary">
                    {burndownUnavailableMessage}
                  </Typography>
                </Box>
              ) : (
                <Box height={250}>
                  <Line data={burndownData} options={lineChartOptions} />
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>
      )}

      {showDistribution && (
        <Grid item xs={12} md={showVelocity || showBurndown ? 6 : 12}>
          <Card data-testid="dashboard-chart-distribution" sx={{ height: '100%' }}>
            <CardContent>
              <Typography variant="h6" gutterBottom fontWeight={600}>
                Task Distribution
              </Typography>
              {isLoading ? (
                <Box height={250} display="flex" alignItems="center" justifyContent="center">
                  <LinearProgress sx={{ width: '80%' }} />
                </Box>
              ) : !hasTasks || !hasDistributionData ? (
                <Box height={250} display="flex" alignItems="center" justifyContent="center">
                  <Typography variant="body2" color="text.secondary">
                    No tasks available for distribution.
                  </Typography>
                </Box>
              ) : (
                <Box height={250} display="flex" justifyContent="center" alignItems="center">
                  <Doughnut data={taskDistributionData} options={doughnutChartOptions} />
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>
      )}
    </Grid>
  );
};

DashboardChartsSection.displayName = 'DashboardChartsSection';

export default React.memo(DashboardChartsSection);
