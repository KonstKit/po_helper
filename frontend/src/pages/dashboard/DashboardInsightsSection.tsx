import React from 'react';
import {
  Box,
  Card,
  CardContent,
  Chip,
  Grid,
  LinearProgress,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Typography,
} from '@mui/material';
import type { RiskItem, UpcomingTaskItem } from './dashboardDerivations';
import { DASHBOARD_TEST_IDS } from './dashboardContract';

interface DashboardInsightsSectionProps {
  isLoading: boolean;
  riskItems: RiskItem[];
  upcomingTasks: UpcomingTaskItem[];
}

const DashboardInsightsSection: React.FC<DashboardInsightsSectionProps> = ({
  isLoading,
  riskItems,
  upcomingTasks,
}) => {
  const rowSx = {
    borderLeft: 4,
    mb: 1,
    borderRadius: 1,
    bgcolor: 'action.hover',
  };

  return (
    <Grid container spacing={3} data-testid={DASHBOARD_TEST_IDS.sectionInsights}>
      <Grid item xs={12} md={6}>
        <Card data-testid={DASHBOARD_TEST_IDS.riskPanel} sx={{ height: '100%' }}>
          <CardContent>
            <Typography variant="h6" gutterBottom fontWeight={600}>
              Risk Alerts
            </Typography>
            {isLoading ? (
              <Box>
                <LinearProgress sx={{ mb: 1 }} />
              </Box>
            ) : (
              <List dense>
                {riskItems.map((item, index) => {
                  const content = (
                    <ListItemText
                      primaryTypographyProps={{ component: 'div' }}
                      primary={
                        <Box display="flex" alignItems="center" gap={1}>
                          <Chip
                            label={item.level}
                            size="small"
                            color={
                              item.color === 'error.main'
                                ? 'error'
                                : item.color === 'warning.main'
                                  ? 'warning'
                                  : 'success'
                            }
                          />
                          <Typography variant="body2">{item.message}</Typography>
                        </Box>
                      }
                    />
                  );

                  if (item.onClick) {
                    return (
                      <ListItem key={index} disablePadding>
                        <ListItemButton
                          data-testid={DASHBOARD_TEST_IDS.riskItem}
                          onClick={item.onClick}
                          sx={{ ...rowSx, borderColor: item.color }}
                        >
                          {content}
                        </ListItemButton>
                      </ListItem>
                    );
                  }

                  return (
                    <ListItem
                      key={index}
                      data-testid={DASHBOARD_TEST_IDS.riskItem}
                      sx={{ ...rowSx, borderColor: item.color }}
                    >
                      {content}
                    </ListItem>
                  );
                })}
              </List>
            )}
          </CardContent>
        </Card>
      </Grid>

      <Grid item xs={12} md={6}>
        <Card data-testid={DASHBOARD_TEST_IDS.upcomingPanel} sx={{ height: '100%' }}>
          <CardContent>
            <Typography variant="h6" gutterBottom fontWeight={600}>
              Upcoming Tasks
            </Typography>
            {isLoading ? (
              <Box>
                <LinearProgress sx={{ mb: 1 }} />
              </Box>
            ) : upcomingTasks.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                No upcoming tasks.
              </Typography>
            ) : (
              <List dense>
                {upcomingTasks.map(({ row, daysRemaining }, index) => (
                  <ListItem data-testid={DASHBOARD_TEST_IDS.upcomingItem} key={row.id || index} sx={{ py: 0.5 }}>
                    <ListItemText
                      primaryTypographyProps={{ component: 'div' }}
                      secondaryTypographyProps={{ component: 'div' }}
                      primary={
                        <Typography variant="body2" noWrap>
                          {row.key || row.summary || 'Untitled'}
                        </Typography>
                      }
                      secondary={
                        daysRemaining !== null ? (
                          <Chip
                            label={
                              daysRemaining > 0
                                ? `${daysRemaining}d left`
                                : daysRemaining === 0
                                  ? 'Due today'
                                  : `${Math.abs(daysRemaining)}d overdue`
                            }
                            size="small"
                            color={daysRemaining < 0 ? 'error' : daysRemaining <= 3 ? 'warning' : 'default'}
                            sx={{ fontSize: '0.7rem', height: 18 }}
                          />
                        ) : (
                          <Typography variant="caption" color="text.secondary">
                            No due date
                          </Typography>
                        )
                      }
                    />
                  </ListItem>
                ))}
              </List>
            )}
          </CardContent>
        </Card>
      </Grid>
    </Grid>
  );
};

DashboardInsightsSection.displayName = 'DashboardInsightsSection';

export default React.memo(DashboardInsightsSection);
