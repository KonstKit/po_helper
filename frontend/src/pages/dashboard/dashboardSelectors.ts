import { createSelector } from '@reduxjs/toolkit';
import type { BurndownResponse, VelocityResponse } from '../../services/api';
import type { Task } from '../../store/taskSlice';
import {
  buildActiveBlockers,
  buildBurndownData,
  buildDashboardStats,
  buildEnhancedVelocityData,
  buildOverdueTasks,
  buildStaleInProgressTasks,
  buildTargetVelocity,
  buildTaskDistribution,
  buildUpcomingTasks,
  buildVelocityDataFromApi,
  buildVelocitySeries,
  buildVelocityTrend,
  filterTasksByDateRange,
} from './dashboardDerivations';
import type { DateRangeOption } from './dashboardContract';
import { getUpcomingHorizonDays } from './dashboardContract';

export interface DashboardSelectorInput {
  projectTasks: Task[];
  dateRange: DateRangeOption;
  now: number;
  velocityData: VelocityResponse | null;
  burndownTimeline: BurndownResponse | null;
}

export interface DashboardSelectorOutput {
  stats: ReturnType<typeof buildDashboardStats>;
  dateScopedTasks: Task[];
  scopedStats: ReturnType<typeof buildDashboardStats>;
  velocityChartData: ReturnType<typeof buildVelocityDataFromApi>;
  burndownModel: ReturnType<typeof buildBurndownData>;
  taskDistribution: ReturnType<typeof buildTaskDistribution>;
  overdueTasks: Task[];
  activeBlockers: Task[];
  staleInProgressTasks: Task[];
  velocitySeries: number[];
  velocityTrend: ReturnType<typeof buildVelocityTrend>;
  enhancedVelocityData: ReturnType<typeof buildEnhancedVelocityData>;
  targetVelocity: number | undefined;
  upcomingTasks: ReturnType<typeof buildUpcomingTasks>;
}

export const makeSelectDashboardDerivedState = () =>
  createSelector(
    [
      (input: DashboardSelectorInput) => input.projectTasks,
      (input: DashboardSelectorInput) => input.dateRange,
      (input: DashboardSelectorInput) => input.now,
      (input: DashboardSelectorInput) => input.velocityData,
      (input: DashboardSelectorInput) => input.burndownTimeline,
    ],
    (
      projectTasks,
      dateRange,
      now,
      velocityData,
      burndownTimeline
    ): DashboardSelectorOutput => {
      const stats = buildDashboardStats(projectTasks, now);
      const dateScopedTasks = filterTasksByDateRange(projectTasks, dateRange, now);
      const scopedStats = buildDashboardStats(dateScopedTasks, now);
      const velocityChartData = buildVelocityDataFromApi(velocityData);
      const burndownModel = buildBurndownData(burndownTimeline);
      const taskDistribution = buildTaskDistribution(projectTasks);
      const overdueTasks = buildOverdueTasks(dateScopedTasks, now);
      const activeBlockers = buildActiveBlockers(dateScopedTasks);
      const staleInProgressTasks = buildStaleInProgressTasks(dateScopedTasks, now);
      const velocitySeries = buildVelocitySeries(velocityChartData);
      const velocityTrend = buildVelocityTrend(velocityData, velocitySeries);
      const enhancedVelocityData = buildEnhancedVelocityData(
        velocityChartData,
        velocitySeries
      );
      const targetVelocity =
        typeof velocityData?.average_velocity === 'number'
          ? Math.round(velocityData.average_velocity)
          : buildTargetVelocity(velocitySeries);
      const upcomingTasks = buildUpcomingTasks(
        dateScopedTasks,
        now,
        getUpcomingHorizonDays(dateRange)
      );

      return {
        stats,
        dateScopedTasks,
        scopedStats,
        velocityChartData,
        burndownModel,
        taskDistribution,
        overdueTasks,
        activeBlockers,
        staleInProgressTasks,
        velocitySeries,
        velocityTrend,
        enhancedVelocityData,
        targetVelocity,
        upcomingTasks,
      };
    }
  );
