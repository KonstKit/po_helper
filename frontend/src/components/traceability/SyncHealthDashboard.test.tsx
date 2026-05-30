import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';

vi.mock('../../services/api', () => ({
  getSyncHealth: vi.fn(),
  getDetailedSyncHealth: vi.fn(),
  listProjects: vi.fn(),
}));

import SyncHealthDashboard from './SyncHealthDashboard';
import { getSyncHealth, getDetailedSyncHealth, listProjects } from '../../services/api';

const mockedGetHealth = vi.mocked(getSyncHealth);
const mockedGetDetailed = vi.mocked(getDetailedSyncHealth);
const mockedListProjects = vi.mocked(listProjects);

const projectList = {
  data: [
    { id: 1, jira_key: 'PROJ', name: 'Apollo Platform', status: 'active' },
    { id: 2, jira_key: 'BETA', name: 'Beta Service', status: 'active' },
  ],
};

const healthResponse = {
  health: {
    status: 'healthy' as const,
    score: 92,
  },
  summary: {
    total_sources: 3,
    reachable_sources: 2,
    total_artifacts: 1234,
    last_sync: '2026-05-30T10:00:00Z',
    checked_at: '2026-05-30T12:00:00Z',
  },
  sources: [
    {
      source: 'jira',
      label: 'Jira Cloud',
      status: 'reachable' as const,
      effective_connector_source: 'jira',
      last_sync: '2026-05-30T10:00:00Z',
      artifact_count: 800,
      checked_at: '2026-05-30T12:00:00Z',
      error: null,
    },
    {
      source: 'github',
      label: 'GitHub Repos',
      status: 'degraded' as const,
      effective_connector_source: 'github',
      last_sync: null,
      artifact_count: 434,
      checked_at: '2026-05-30T12:00:00Z',
      error: 'Rate limited',
    },
  ],
  projects: [
    {
      project_id: 1,
      project_name: 'Apollo Platform',
      jira_key: 'PROJ',
      last_sync: '2026-05-30T10:00:00Z',
      artifact_count: 800,
      health_status: 'healthy' as const,
    },
  ],
};

const detailedResponse = {
  project_id: 1,
  project_name: 'Apollo Platform',
  jira_key: 'PROJ',
  last_sync: '2026-05-30T10:00:00Z',
  health_status: 'healthy' as const,
  by_type: { requirement: 120, task: 300 },
  by_source: { jira: 800 },
  link_coverage: {
    total_artifacts: 800,
    linked_artifacts: 720,
    orphaned_artifacts: 80,
    coverage_pct: 90.0,
  },
  sources: [],
  checked_at: '2026-05-30T12:00:00Z',
  repositories: [],
};

describe('SyncHealthDashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedListProjects.mockResolvedValue(projectList as never);
    mockedGetHealth.mockResolvedValue(healthResponse as never);
    mockedGetDetailed.mockResolvedValue(detailedResponse as never);
  });

  it('shows the loading indicator before data resolves', () => {
    // Keep the promise pending so the loading branch stays mounted.
    mockedGetHealth.mockReturnValue(new Promise(() => {}) as never);
    render(<SyncHealthDashboard />);
    expect(screen.getByText(/Loading sync health data/i)).toBeInTheDocument();
  });

  it('renders an empty projects message when no project health rows exist', async () => {
    mockedGetHealth.mockResolvedValueOnce({
      ...healthResponse,
      projects: [],
    } as never);
    render(<SyncHealthDashboard />);
    expect(await screen.findByText(/No projects found/i)).toBeInTheDocument();
    // Heading reflects the zero count.
    expect(screen.getByText(/Project Health \(0\)/i)).toBeInTheDocument();
  });

  it('shows an error alert with a retry button when loading fails', async () => {
    mockedGetHealth.mockRejectedValueOnce(new Error('boom while loading health'));
    render(<SyncHealthDashboard />);
    expect(await screen.findByText('boom while loading health')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('renders the health metrics and project rows on success', async () => {
    render(<SyncHealthDashboard />);

    // Health score (Math.round(92)) and overall status label.
    expect(await screen.findByText('92%')).toBeInTheDocument();
    expect(screen.getByText('System Healthy')).toBeInTheDocument();

    // The summary is one joined string; assert robust substrings (the
    // thousands separator is locale-dependent, so don't hardcode "1,234").
    expect(screen.getByText(/2 of 3 sources reachable/i)).toBeInTheDocument();
    expect(screen.getByText(/total artifacts/i)).toBeInTheDocument();

    // Source cards render their labels.
    expect(screen.getByText('Jira Cloud')).toBeInTheDocument();
    expect(screen.getByText('GitHub Repos')).toBeInTheDocument();

    // Project health table: heading count + the project row.
    expect(screen.getByText(/Project Health \(1\)/i)).toBeInTheDocument();
    expect(screen.getByText('Apollo Platform')).toBeInTheDocument();

    expect(mockedGetHealth).toHaveBeenCalledWith({ projectId: undefined });
    expect(mockedListProjects).toHaveBeenCalled();
  });

  it('loads detailed health when a project row is clicked', async () => {
    render(<SyncHealthDashboard />);

    const projectCell = await screen.findByText('Apollo Platform');
    const row = projectCell.closest('tr');
    expect(row).not.toBeNull();
    fireEvent.click(row as HTMLElement);

    await waitFor(() => expect(mockedGetDetailed).toHaveBeenCalledWith(1));

    // Expanded detail panel renders its section headings + coverage metric.
    expect(await screen.findByText('Artifacts by Type')).toBeInTheDocument();
    expect(screen.getByText('Link Coverage')).toBeInTheDocument();
    expect(screen.getByText('90.0%')).toBeInTheDocument();
  });
});
