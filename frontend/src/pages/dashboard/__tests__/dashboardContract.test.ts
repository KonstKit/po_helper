import { beforeEach, describe, expect, it } from 'vitest';
import {
  DASHBOARD_DEFAULTS,
  DASHBOARD_STORAGE_CONTRACT,
  DASHBOARD_STORAGE_KEYS,
  detectTaskScopeAnomaly,
  migrateDashboardStorageContract,
} from '../dashboardContract';

describe('dashboardContract persistence migration', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('migrates legacy storage keys into canonical dashboard contract keys', () => {
    localStorage.setItem('date_range', '14d');
    localStorage.setItem('chart_view', 'velocity');
    localStorage.setItem('quick_filter', 'active');
    localStorage.setItem('recent_project_ids', JSON.stringify([7, 5, 3]));
    localStorage.setItem('last_project_id', '5');

    const state = migrateDashboardStorageContract();

    expect(state).toMatchObject({
      dateRange: '14d',
      chartView: 'velocity',
      quickFilter: 'active',
      recentProjectIds: [7, 5, 3],
      lastProjectId: 5,
      version: DASHBOARD_STORAGE_CONTRACT.currentVersion,
    });
    expect(localStorage.getItem(DASHBOARD_STORAGE_KEYS.dateRange)).toBe('14d');
    expect(localStorage.getItem(DASHBOARD_STORAGE_KEYS.chartView)).toBe('velocity');
    expect(localStorage.getItem(DASHBOARD_STORAGE_KEYS.quickFilter)).toBe('active');
    expect(localStorage.getItem(DASHBOARD_STORAGE_CONTRACT.versionKey)).toBe(
      String(DASHBOARD_STORAGE_CONTRACT.currentVersion)
    );
    expect(localStorage.getItem('date_range')).toBeNull();
    expect(localStorage.getItem('chart_view')).toBeNull();
    expect(localStorage.getItem('quick_filter')).toBeNull();
  });

  it('falls back to defaults when persisted values are invalid or malformed', () => {
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.dateRange, '900d');
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.chartView, 'unknown');
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.quickFilter, 'invalid');
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.recentProjectIds, '{bad json');
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.lastProjectId, 'not-a-number');

    const state = migrateDashboardStorageContract();

    expect(state.dateRange).toBe(DASHBOARD_DEFAULTS.dateRange);
    expect(state.chartView).toBe(DASHBOARD_DEFAULTS.chartView);
    expect(state.quickFilter).toBe(DASHBOARD_DEFAULTS.quickFilter);
    expect(state.recentProjectIds).toEqual([]);
    expect(state.lastProjectId).toBeNull();
    expect(localStorage.getItem(DASHBOARD_STORAGE_KEYS.dateRange)).toBe(
      DASHBOARD_DEFAULTS.dateRange
    );
    expect(localStorage.getItem(DASHBOARD_STORAGE_KEYS.chartView)).toBe(
      DASHBOARD_DEFAULTS.chartView
    );
    expect(localStorage.getItem(DASHBOARD_STORAGE_KEYS.quickFilter)).toBe(
      DASHBOARD_DEFAULTS.quickFilter
    );
  });
});

describe('dashboardContract task scope anomaly detection', () => {
  it('detects inconsistent task-scope counters', () => {
    expect(
      detectTaskScopeAnomaly({
        fetched: 120,
        total: 100,
        hasNext: false,
        isPartial: false,
      })
    ).toMatchObject({
      code: 'fetched_exceeds_total',
    });

    expect(
      detectTaskScopeAnomaly({
        fetched: 100,
        total: 100,
        hasNext: true,
        isPartial: true,
        capHit: false,
      })
    ).toMatchObject({
      code: 'has_next_conflict',
    });
  });
});
