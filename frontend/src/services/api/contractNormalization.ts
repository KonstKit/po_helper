import type {
  BurndownPoint,
  BurndownResponse,
  VelocityResponse,
  VelocitySprintSummary,
  VelocityTrendDirection,
} from './types';

const toFiniteNumber = (value: unknown): number | null => {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  if (typeof value === 'boolean') {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const toOptionalString = (value: unknown): string | undefined => {
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return trimmed ? trimmed : undefined;
};

const toOptionalDateString = (value: unknown): string | null | undefined => {
  if (value === null) return null;
  if (typeof value !== 'string') return undefined;
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? value : undefined;
};

const isVelocityTrendDirection = (
  value: unknown
): value is VelocityTrendDirection => {
  return (
    value === 'increasing' ||
    value === 'decreasing' ||
    value === 'stable' ||
    value === 'insufficient_data'
  );
};

const normalizeVelocitySprintSummary = (
  value: unknown
): VelocitySprintSummary | null => {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Record<string, unknown>;
  const velocity = toFiniteNumber(raw.velocity);
  if (velocity === null) return null;

  const sprintId = toFiniteNumber(raw.sprint_id);
  const sprintName = toOptionalString(raw.sprint_name);
  const endDate = toOptionalDateString(raw.end_date);

  return {
    velocity,
    sprint_id: sprintId === null ? undefined : sprintId,
    sprint_name: sprintName,
    end_date: endDate,
  };
};

export const normalizeVelocityResponse = (value: unknown): VelocityResponse => {
  if (!value || typeof value !== 'object') {
    return {
      average_velocity: 0,
      sprints_analyzed: 0,
      velocity_trend: 'insufficient_data',
      sprint_velocities: [],
    };
  }

  const raw = value as Record<string, unknown>;
  const sprintVelocities = Array.isArray(raw.sprint_velocities)
    ? raw.sprint_velocities
        .map((item) => normalizeVelocitySprintSummary(item))
        .filter((item): item is VelocitySprintSummary => item !== null)
    : [];

  const averageVelocity = toFiniteNumber(raw.average_velocity) ?? 0;
  const sprintsAnalyzed = toFiniteNumber(raw.sprints_analyzed);
  const velocityTrend = isVelocityTrendDirection(raw.velocity_trend)
    ? raw.velocity_trend
    : 'insufficient_data';

  return {
    average_velocity: averageVelocity,
    sprints_analyzed:
      sprintsAnalyzed === null ? sprintVelocities.length : sprintsAnalyzed,
    velocity_trend: velocityTrend,
    sprint_velocities: sprintVelocities,
  };
};

const normalizeBurndownPoint = (
  value: unknown,
  field: 'ideal_remaining' | 'remaining'
): BurndownPoint | null => {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Record<string, unknown>;

  const day = toFiniteNumber(raw.day);
  const remaining = toFiniteNumber(raw[field]);
  if (day === null || remaining === null) {
    return null;
  }

  return field === 'ideal_remaining'
    ? { day, ideal_remaining: remaining }
    : { day, remaining };
};

export const normalizeBurndownResponse = (value: unknown): BurndownResponse => {
  if (!value || typeof value !== 'object') {
    return {
      ideal_burndown: [],
      actual_burndown: [],
    };
  }

  const raw = value as Record<string, unknown>;
  const sprintId = toFiniteNumber(raw.sprint_id);
  const idealPoints = Array.isArray(raw.ideal_burndown)
    ? raw.ideal_burndown
        .map((item) => normalizeBurndownPoint(item, 'ideal_remaining'))
        .filter((item): item is BurndownPoint => item !== null)
    : [];
  const actualPoints = Array.isArray(raw.actual_burndown)
    ? raw.actual_burndown
        .map((item) => normalizeBurndownPoint(item, 'remaining'))
        .filter((item): item is BurndownPoint => item !== null)
    : [];

  return {
    sprint_id: sprintId === null ? undefined : sprintId,
    ideal_burndown: idealPoints,
    actual_burndown: actualPoints,
  };
};
