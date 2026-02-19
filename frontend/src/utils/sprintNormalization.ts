export type SprintLifecycleState = 'active' | 'closed' | 'future' | 'unknown';
export type SprintStateSource = 'state' | 'status' | 'date' | 'fallback' | 'none';

export interface SprintLike {
  id?: number | string | null;
  sprint_id?: number | string | null;
  project_id?: number | string | null;
  state?: string | null;
  status?: string | null;
  start_date?: string | null;
  end_date?: string | null;
}

export interface NormalizedSprint<T extends SprintLike = SprintLike> {
  sprint: T;
  canonicalId: number | null;
  projectId: number | null;
  state: SprintLifecycleState;
  stateSource: SprintStateSource;
  startTime: number | null;
  endTime: number | null;
  missingFields: string[];
  isValid: boolean;
  hasContractDrift: boolean;
}

const ACTIVE_STATES = new Set(['active', 'in_progress', 'inprogress', 'started', 'open', 'current']);
const CLOSED_STATES = new Set(['closed', 'complete', 'completed', 'done', 'finished', 'resolved']);
const FUTURE_STATES = new Set(['future', 'upcoming', 'planned', 'not_started']);

const toPositiveInteger = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isInteger(value) && value > 0) {
    return value;
  }
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    if (Number.isInteger(parsed) && parsed > 0) {
      return parsed;
    }
  }
  return null;
};

const toDateMs = (value: unknown): number | null => {
  if (typeof value !== 'string' || value.trim() === '') return null;
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : null;
};

const normalizeLifecycleToken = (value: unknown): SprintLifecycleState | null => {
  if (typeof value !== 'string') return null;
  const token = value.trim().toLowerCase();
  if (!token) return null;
  if (ACTIVE_STATES.has(token)) return 'active';
  if (CLOSED_STATES.has(token)) return 'closed';
  if (FUTURE_STATES.has(token)) return 'future';
  return null;
};

const resolveDateState = (
  startTime: number | null,
  endTime: number | null,
  now: number
): SprintLifecycleState | null => {
  if (startTime !== null && endTime !== null) {
    if (now >= startTime && now <= endTime) return 'active';
    if (now < startTime) return 'future';
    if (now > endTime) return 'closed';
  }
  if (startTime !== null && now < startTime) return 'future';
  if (endTime !== null && now > endTime) return 'closed';
  return null;
};

export const getCanonicalSprintId = (sprint: SprintLike | null | undefined): number | null => {
  if (!sprint) return null;
  const sprintId = toPositiveInteger(sprint.sprint_id);
  if (sprintId !== null) return sprintId;
  return toPositiveInteger(sprint.id);
};

export const normalizeSprint = <T extends SprintLike>(
  sprint: T,
  now = Date.now()
): NormalizedSprint<T> => {
  const canonicalId = getCanonicalSprintId(sprint);
  const projectId = toPositiveInteger(sprint.project_id);
  const startTime = toDateMs(sprint.start_date);
  const endTime = toDateMs(sprint.end_date);
  const stateFromState = normalizeLifecycleToken(sprint.state);
  const stateFromStatus = normalizeLifecycleToken(sprint.status);
  const stateFromDates = resolveDateState(startTime, endTime, now);

  let state: SprintLifecycleState = 'unknown';
  let stateSource: SprintStateSource = 'none';

  if (stateFromState) {
    state = stateFromState;
    stateSource = 'state';
  } else if (stateFromStatus) {
    state = stateFromStatus;
    stateSource = 'status';
  } else if (stateFromDates) {
    state = stateFromDates;
    stateSource = 'date';
  }

  const missingFields: string[] = [];
  if (canonicalId === null) missingFields.push('id');
  if (!stateFromState && !stateFromStatus) missingFields.push('state_or_status');
  if (startTime === null) missingFields.push('start_date');
  if (endTime === null) missingFields.push('end_date');

  return {
    sprint,
    canonicalId,
    projectId,
    state,
    stateSource,
    startTime,
    endTime,
    missingFields,
    isValid: canonicalId !== null,
    hasContractDrift: missingFields.length > 0,
  };
};

export const normalizeSprints = <T extends SprintLike>(
  sprints: T[],
  now = Date.now()
): Array<NormalizedSprint<T>> => sprints.map((sprint) => normalizeSprint(sprint, now));

const compareNormalizedSprints = <T extends SprintLike>(
  left: NormalizedSprint<T>,
  right: NormalizedSprint<T>
): number => {
  const leftEnd = left.endTime ?? Number.NEGATIVE_INFINITY;
  const rightEnd = right.endTime ?? Number.NEGATIVE_INFINITY;
  if (leftEnd !== rightEnd) return rightEnd - leftEnd;

  const leftStart = left.startTime ?? Number.NEGATIVE_INFINITY;
  const rightStart = right.startTime ?? Number.NEGATIVE_INFINITY;
  if (leftStart !== rightStart) return rightStart - leftStart;

  const leftId = left.canonicalId ?? Number.NEGATIVE_INFINITY;
  const rightId = right.canonicalId ?? Number.NEGATIVE_INFINITY;
  return rightId - leftId;
};

const pickBest = <T extends SprintLike>(
  candidates: Array<NormalizedSprint<T>>
): NormalizedSprint<T> | null => {
  if (candidates.length === 0) return null;
  return [...candidates].sort(compareNormalizedSprints)[0] ?? null;
};

export const selectActiveNormalizedSprint = <T extends SprintLike>(
  normalized: Array<NormalizedSprint<T>>
): NormalizedSprint<T> | null => {
  const explicitStateActive = normalized.filter(
    (entry) => entry.state === 'active' && entry.stateSource === 'state'
  );
  const byState = pickBest(explicitStateActive);
  if (byState) return byState;

  const statusActive = normalized.filter(
    (entry) => entry.state === 'active' && entry.stateSource === 'status'
  );
  const byStatus = pickBest(statusActive);
  if (byStatus) return byStatus;

  const byDateWindow = normalized.filter(
    (entry) => entry.state === 'active' && entry.stateSource === 'date'
  );
  const byDate = pickBest(byDateWindow);
  if (byDate) return byDate;

  const byTimeline = pickBest(
    normalized.filter((entry) => entry.startTime !== null || entry.endTime !== null)
  );
  if (byTimeline) {
    return { ...byTimeline, stateSource: 'fallback' };
  }

  const byId = pickBest(normalized.filter((entry) => entry.canonicalId !== null));
  if (byId) {
    return { ...byId, stateSource: 'fallback' };
  }

  return null;
};

export const selectActiveSprint = <T extends SprintLike>(sprints: T[], now = Date.now()): T | null => {
  const selected = selectActiveNormalizedSprint(normalizeSprints(sprints, now));
  return selected?.sprint ?? null;
};

export const selectActiveSprintId = <T extends SprintLike>(sprints: T[], now = Date.now()): number | null =>
  getCanonicalSprintId(selectActiveSprint(sprints, now));

export const isSprintActive = (sprint: SprintLike, now = Date.now()): boolean =>
  normalizeSprint(sprint, now).state === 'active';

export const getSprintStateLabel = (sprint: SprintLike, now = Date.now()): string => {
  const state = normalizeSprint(sprint, now).state;
  if (state === 'active') return 'Active';
  if (state === 'closed') return 'Closed';
  if (state === 'future') return 'Future';
  return 'Unknown';
};
