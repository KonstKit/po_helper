import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';

// Mock ONLY the API functions this component imports.
vi.mock('../../services/api', () => ({
  runConsistencyCheck: vi.fn(),
  fixConsistencyIssues: vi.fn(),
  getDetailedCycles: vi.fn(),
}));

import DataConsistencyPanel from './DataConsistencyPanel';
import {
  runConsistencyCheck,
  fixConsistencyIssues,
  getDetailedCycles,
} from '../../services/api';

const mockedRunCheck = vi.mocked(runConsistencyCheck);
const mockedFix = vi.mocked(fixConsistencyIssues);
const mockedDetailedCycles = vi.mocked(getDetailedCycles);

// Realistic payload matching ConsistencyCheckResponse in services/api/types.ts.
// Includes broken references + duplicates so the fix actions render.
const checkResultWithIssues = {
  health_score: 0.82,
  status: 'warning' as const,
  issues: {
    orphans: [
      { artifact_id: 101, type: 'requirement', title: 'Lonely requirement', display_key: 'REQ-101' },
    ],
    orphan_count: 1,
    cycles: [],
    cycle_count: 0,
    broken_references: [
      { link_id: 7, link_type: 'derives', from_artifact_id: 5, to_artifact_id: 9999 },
    ],
    broken_ref_count: 1,
    duplicates: [
      { from_artifact_id: 3, to_artifact_id: 4, link_type: 'verifies', count: 2 },
    ],
    duplicate_count: 1,
    stale_artifacts: [],
    stale_count: 0,
  },
  recommendations: [
    {
      priority: 'high' as const,
      category: 'Broken References',
      action: 'Remove dangling links',
      reason: 'Links point to deleted artifacts',
      fix: 'Run automatic fix',
    },
  ],
  checked_at: '2026-05-30T12:00:00Z',
  project_filtered: false,
};

// Clean result: no issues at all -> "0 issues found", healthy status.
const checkResultClean = {
  health_score: 1,
  status: 'healthy' as const,
  issues: {
    orphans: [],
    orphan_count: 0,
    cycles: [],
    cycle_count: 0,
    broken_references: [],
    broken_ref_count: 0,
    duplicates: [],
    duplicate_count: 0,
    stale_artifacts: [],
    stale_count: 0,
  },
  recommendations: [],
  checked_at: '2026-05-30T12:00:00Z',
  project_filtered: true,
};

const fixResultPreview = {
  dry_run: true,
  fixed_broken_refs: 1,
  fixed_duplicates: 1,
  details: { removed_links: [7], removed_duplicate_ids: [4] },
};

describe('DataConsistencyPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedRunCheck.mockResolvedValue(checkResultWithIssues as never);
    mockedFix.mockResolvedValue(fixResultPreview as never);
    mockedDetailedCycles.mockResolvedValue({
      total_cycles: 0,
      cycles: [],
      checked_link_types: ['derives'],
    } as never);
  });

  it('shows the initial prompt and does not fetch on mount', () => {
    render(<DataConsistencyPanel />);
    // Initial/empty state: nothing has been run yet.
    expect(screen.getByText('Run Consistency Check')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /run check/i })
    ).toBeInTheDocument();
    // Component does not auto-run on mount.
    expect(mockedRunCheck).not.toHaveBeenCalled();
  });

  it('renders an empty/healthy result with zero issues after running a check', async () => {
    mockedRunCheck.mockResolvedValueOnce(checkResultClean as never);
    render(<DataConsistencyPanel />);

    fireEvent.click(screen.getByRole('button', { name: /run check/i }));

    expect(await screen.findByText(/Data Integrity: Healthy/i)).toBeInTheDocument();
    expect(screen.getByText(/0 issues found/i)).toBeInTheDocument();
    expect(mockedRunCheck).toHaveBeenCalledTimes(1);
  });

  it('shows an error message when the consistency check fails', async () => {
    mockedRunCheck.mockRejectedValueOnce(new Error('check exploded'));
    render(<DataConsistencyPanel />);

    fireEvent.click(screen.getByRole('button', { name: /run check/i }));

    expect(await screen.findByText('check exploded')).toBeInTheDocument();
  });

  it('renders the health score, issue counts and section labels on success', async () => {
    render(<DataConsistencyPanel />);

    fireEvent.click(screen.getByRole('button', { name: /run check/i }));

    // Health score rendered as a rounded percentage (0.82 -> 82%).
    expect(await screen.findByText('82%')).toBeInTheDocument();
    expect(screen.getByText(/Data Integrity: Warning/i)).toBeInTheDocument();
    // 1 orphan + 1 broken ref + 1 duplicate = 3 issues.
    expect(screen.getByText(/3 issues found/i)).toBeInTheDocument();
    // Issue section headers with non-zero counts are rendered. These labels
    // also appear as check-option toggles, so multiple matches are expected.
    expect(screen.getAllByText('Orphaned Artifacts').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Broken References').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Duplicate Links').length).toBeGreaterThan(0);
    // A recommendation row is shown.
    expect(
      screen.getByText(/Broken References: Remove dangling links/i)
    ).toBeInTheDocument();
  });

  it('passes the current check options to runConsistencyCheck', async () => {
    render(<DataConsistencyPanel projectId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /run check/i }));

    await waitFor(() =>
      expect(mockedRunCheck).toHaveBeenCalledWith(
        expect.objectContaining({
          projectId: 42,
          checkOrphans: true,
          checkCycles: true,
          checkDuplicates: true,
          checkBrokenRefs: true,
          checkStale: true,
          staleDays: 90,
        })
      )
    );
  });

  it('invokes fixConsistencyIssues as a dry run when previewing fixes', async () => {
    render(<DataConsistencyPanel projectId={7} />);

    fireEvent.click(screen.getByRole('button', { name: /run check/i }));
    // Fix actions only appear once results with broken refs/duplicates exist.
    const previewButton = await screen.findByRole('button', { name: /preview fixes/i });

    fireEvent.click(previewButton);

    await waitFor(() =>
      expect(mockedFix).toHaveBeenCalledWith(
        expect.objectContaining({
          projectId: 7,
          fixBrokenRefs: true,
          fixDuplicates: true,
          dryRun: true,
        })
      )
    );
    // The dry-run preview alert surfaces the counts.
    expect(
      await screen.findByText(/1 broken references/i)
    ).toBeInTheDocument();
  });
});
