import { describe, expect, it } from 'vitest';
import {
  getCanonicalSprintId,
  normalizeSprint,
  selectActiveSprint,
  selectActiveSprintId,
} from '../sprintNormalization';

const NOW = new Date('2026-02-19T12:00:00.000Z').getTime();

describe('sprintNormalization', () => {
  it('resolves canonical identifier using sprint_id first and then id', () => {
    expect(getCanonicalSprintId({ sprint_id: 42, id: 7 })).toBe(42);
    expect(getCanonicalSprintId({ id: 7 })).toBe(7);
    expect(getCanonicalSprintId({ id: '11' })).toBe(11);
  });

  it('selects active sprint with precedence: state -> status -> date-window -> fallback', () => {
    const sprints = [
      {
        id: 1,
        name: 'State active',
        state: 'active',
        start_date: '2026-02-01T00:00:00.000Z',
        end_date: '2026-02-28T00:00:00.000Z',
      },
      {
        id: 2,
        name: 'Status active',
        status: 'active',
        start_date: '2026-02-05T00:00:00.000Z',
        end_date: '2026-02-27T00:00:00.000Z',
      },
      {
        id: 3,
        name: 'Date active',
        start_date: '2026-02-10T00:00:00.000Z',
        end_date: '2026-02-21T00:00:00.000Z',
      },
    ];

    const active = selectActiveSprint(sprints, NOW);
    expect(active?.id).toBe(1);
  });

  it('falls back to date-window match when explicit active markers are missing', () => {
    const sprints = [
      {
        id: 10,
        name: 'Past',
        start_date: '2026-01-01T00:00:00.000Z',
        end_date: '2026-01-15T00:00:00.000Z',
      },
      {
        id: 11,
        name: 'Current',
        start_date: '2026-02-01T00:00:00.000Z',
        end_date: '2026-02-28T00:00:00.000Z',
      },
    ];

    expect(selectActiveSprintId(sprints, NOW)).toBe(11);
  });

  it('falls back to latest sprint by date when no active marker exists', () => {
    const sprints = [
      {
        id: 100,
        name: 'Older',
        start_date: '2025-11-01T00:00:00.000Z',
        end_date: '2025-11-14T00:00:00.000Z',
      },
      {
        id: 101,
        name: 'Latest closed',
        start_date: '2025-12-01T00:00:00.000Z',
        end_date: '2025-12-20T00:00:00.000Z',
      },
    ];

    expect(selectActiveSprintId(sprints, NOW)).toBe(101);
  });

  it('returns structured guard diagnostics for malformed payloads', () => {
    const normalized = normalizeSprint(
      {
        id: null,
        sprint_id: null,
        name: 'Malformed',
        start_date: null,
        end_date: null,
      },
      NOW
    );

    expect(normalized.isValid).toBe(false);
    expect(normalized.missingFields).toEqual(
      expect.arrayContaining(['id', 'state_or_status', 'start_date', 'end_date'])
    );
  });

  it('keeps payload valid when identifier exists but dates are missing', () => {
    const normalized = normalizeSprint(
      {
        id: 300,
        name: 'No dates',
        status: 'active',
      },
      NOW
    );

    expect(normalized.isValid).toBe(true);
    expect(normalized.missingFields).toEqual(expect.arrayContaining(['start_date', 'end_date']));
  });
});
