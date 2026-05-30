import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';

vi.mock('../../services/api', () => ({
  getOrphanedArtifacts: vi.fn(),
}));

import OrphanedArtifactsPanel from './OrphanedArtifactsPanel';
import { getOrphanedArtifacts } from '../../services/api';

const mockedGet = vi.mocked(getOrphanedArtifacts);

const buildMeta = (total: number) => ({
  total,
  page: 1,
  per_page: 10,
  total_pages: 1,
  has_next: false,
  has_prev: false,
});

const orphanRequirement = {
  id: 101,
  type: 'requirement',
  source: 'manual',
  external_id: 'REQ-42',
  display_key: 'REQ-42',
  title: 'Login must support SSO',
  status: 'open',
  created_at: '2026-01-01T00:00:00Z',
  suggestion: 'Link to JIRA-9',
};

const orphanJira = {
  id: 202,
  type: 'jira_issue',
  source: 'jira',
  external_id: 'JIRA-9',
  display_key: 'JIRA-9',
  title: 'Implement SSO',
  status: 'In Progress',
  created_at: '2026-01-02T00:00:00Z',
  suggestion: null,
};

const populatedResponse = {
  data: [orphanRequirement, orphanJira],
  meta: buildMeta(2),
  by_type: { requirement: 1, jira_issue: 1 },
  by_source: { manual: 1, jira: 1 },
};

const emptyResponse = {
  data: [],
  meta: buildMeta(0),
  by_type: {},
  by_source: {},
};

describe('OrphanedArtifactsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGet.mockResolvedValue(populatedResponse as never);
  });

  it('shows the loading progress bar on initial render', () => {
    // Keep the promise unresolved so the loading state stays visible.
    mockedGet.mockReturnValue(new Promise(() => {}) as never);
    const { container } = render(<OrphanedArtifactsPanel projectId={1} />);
    expect(container.querySelector('.MuiLinearProgress-root')).toBeInTheDocument();
    expect(mockedGet).toHaveBeenCalledTimes(1);
  });

  it('shows an empty message when there are no orphaned artifacts', async () => {
    mockedGet.mockResolvedValueOnce(emptyResponse as never);
    render(<OrphanedArtifactsPanel projectId={1} />);
    expect(await screen.findByText(/No orphaned artifacts found/i)).toBeInTheDocument();
  });

  it('shows an error message when loading fails', async () => {
    mockedGet.mockRejectedValueOnce(new Error('boom while loading orphans'));
    render(<OrphanedArtifactsPanel projectId={1} />);
    expect(await screen.findByText('boom while loading orphans')).toBeInTheDocument();
  });

  it('renders the orphaned artifact rows, counts, and type breakdown on success', async () => {
    render(<OrphanedArtifactsPanel projectId={1} />);

    // Row identity / titles
    expect(await screen.findByText('REQ-42')).toBeInTheDocument();
    expect(screen.getByText('JIRA-9')).toBeInTheDocument();
    expect(screen.getByText('Login must support SSO')).toBeInTheDocument();
    expect(screen.getByText('Implement SSO')).toBeInTheDocument();

    // Total count chip from meta.total
    expect(screen.getByText('2 orphaned')).toBeInTheDocument();

    // Breakdown chips from by_type / by_source
    expect(screen.getByText('requirement: 1')).toBeInTheDocument();
    expect(screen.getByText('jira_issue: 1')).toBeInTheDocument();
    expect(screen.getByText('manual: 1')).toBeInTheDocument();
    expect(screen.getByText('jira: 1')).toBeInTheDocument();

    // Suggestion text for the first artifact
    expect(screen.getByText('Link to JIRA-9')).toBeInTheDocument();
  });

  it('refetches when the Refresh button is clicked', async () => {
    render(<OrphanedArtifactsPanel projectId={1} />);
    await screen.findByText('REQ-42');
    expect(mockedGet).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: /refresh/i }));
    await waitFor(() => expect(mockedGet).toHaveBeenCalledTimes(2));
  });

  it('invokes onCreateLink with the artifact id when the link action is clicked', async () => {
    const onCreateLink = vi.fn();
    render(<OrphanedArtifactsPanel projectId={1} onCreateLink={onCreateLink} />);
    await screen.findByText('REQ-42');

    const linkButtons = screen.getAllByRole('button', { name: /create link/i });
    fireEvent.click(linkButtons[0]);
    expect(onCreateLink).toHaveBeenCalledWith(101);
  });

  it('filters by artifact type via the type breakdown chip', async () => {
    render(<OrphanedArtifactsPanel projectId={1} />);
    await screen.findByText('REQ-42');
    expect(mockedGet).toHaveBeenCalledTimes(1);

    // Clicking the "requirement: 1" breakdown chip sets the type filter,
    // which re-runs the query with artifactType: 'requirement'.
    fireEvent.click(screen.getByText('requirement: 1'));
    await waitFor(() =>
      expect(mockedGet).toHaveBeenLastCalledWith(
        expect.objectContaining({ artifactType: 'requirement' }),
      ),
    );
  });
});
