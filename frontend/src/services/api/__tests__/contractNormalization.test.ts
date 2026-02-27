import { describe, expect, it } from 'vitest';
import {
  normalizeBurndownResponse,
  normalizeVelocityResponse,
} from '../contractNormalization';

describe('contractNormalization', () => {
  it('normalizes malformed velocity payload to stable typed contract', () => {
    const normalized = normalizeVelocityResponse({
      average_velocity: '9.5',
      sprints_analyzed: '2',
      velocity_trend: 'steady',
      sprint_velocities: [
        { sprint_id: '11', sprint_name: ' Sprint A ', velocity: '4.2' },
        { sprint_id: 'bad', sprint_name: '', velocity: 5, end_date: 'invalid' },
        { sprint_id: 99, velocity: 'oops' },
      ],
    });

    expect(normalized).toEqual({
      average_velocity: 9.5,
      sprints_analyzed: 2,
      velocity_trend: 'insufficient_data',
      sprint_velocities: [
        { sprint_id: 11, sprint_name: 'Sprint A', velocity: 4.2, end_date: undefined },
        { sprint_id: undefined, sprint_name: undefined, velocity: 5, end_date: undefined },
      ],
    });
  });

  it('normalizes malformed burndown payload and drops invalid points', () => {
    const normalized = normalizeBurndownResponse({
      sprint_id: '17',
      ideal_burndown: [
        { day: 1, ideal_remaining: 12 },
        { day: 'x', ideal_remaining: 8 },
        { day: 3, ideal_remaining: '4' },
      ],
      actual_burndown: [
        { day: 1, remaining: '10' },
        { day: 2, remaining: null },
      ],
    });

    expect(normalized).toEqual({
      sprint_id: 17,
      ideal_burndown: [
        { day: 1, ideal_remaining: 12 },
        { day: 3, ideal_remaining: 4 },
      ],
      actual_burndown: [{ day: 1, remaining: 10 }],
    });
  });

  it('returns deterministic empty defaults for non-object payloads', () => {
    expect(normalizeVelocityResponse(null)).toEqual({
      average_velocity: 0,
      sprints_analyzed: 0,
      velocity_trend: 'insufficient_data',
      sprint_velocities: [],
    });
    expect(normalizeBurndownResponse(null)).toEqual({
      ideal_burndown: [],
      actual_burndown: [],
    });
  });
});
