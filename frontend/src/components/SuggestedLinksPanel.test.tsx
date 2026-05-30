import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';

vi.mock('../services/api', () => ({
  getSuggestedLinks: vi.fn(),
  getSuggestedLinksStats: vi.fn(),
  generateSuggestedLinks: vi.fn(),
  approveSuggestedLink: vi.fn(),
  rejectSuggestedLink: vi.fn(),
  bulkApproveSuggestedLinks: vi.fn(),
}));

import SuggestedLinksPanel from './SuggestedLinksPanel';
import {
  getSuggestedLinks,
  getSuggestedLinksStats,
  generateSuggestedLinks,
  approveSuggestedLink,
  rejectSuggestedLink,
  bulkApproveSuggestedLinks,
} from '../services/api';

const mockedGetLinks = vi.mocked(getSuggestedLinks);
const mockedGetStats = vi.mocked(getSuggestedLinksStats);
const mockedGenerate = vi.mocked(generateSuggestedLinks);
const mockedApprove = vi.mocked(approveSuggestedLink);
const mockedReject = vi.mocked(rejectSuggestedLink);
const mockedBulkApprove = vi.mocked(bulkApproveSuggestedLinks);

// Realistic SuggestedLink matching the backend contract in services/api/types.ts.
const pendingSuggestion = {
  id: 501,
  from_artifact_id: 10,
  to_artifact_id: 20,
  suggested_link_type: 'implements',
  similarity_score: 0.82,
  method: 'tfidf',
  reason: 'High textual overlap',
  status: 'pending' as const,
  created_at: '2026-05-01T10:00:00Z',
  from_artifact: {
    id: 10,
    type: 'requirement',
    source: 'internal',
    external_id: 'REQ-100',
    display_key: 'REQ-100',
    title: 'Login requirement',
  },
  to_artifact: {
    id: 20,
    type: 'jira_issue',
    source: 'jira',
    external_id: 'PROJ-55',
    display_key: 'PROJ-55',
    title: 'Implement login',
  },
};

// getSuggestedLinks returns a PaginatedResponse<SuggestedLink>: { data, meta }.
const buildResponse = (items: (typeof pendingSuggestion)[]) => ({
  data: items,
  meta: {
    total: items.length,
    page: 1,
    per_page: 100,
    total_pages: 1,
    has_next: false,
    has_prev: false,
  },
});

const statsPayload = {
  total_pending: 3,
  total_approved: 7,
  total_rejected: 2,
  avg_similarity_score: 0.66,
  by_link_type: { implements: 3 },
  by_method: { tfidf: 5 },
};

describe('SuggestedLinksPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetLinks.mockResolvedValue(buildResponse([pendingSuggestion]) as never);
    mockedGetStats.mockResolvedValue(statsPayload as never);
    mockedGenerate.mockResolvedValue({ generated: 1, stored: 1, indexed_artifacts: 5 } as never);
    mockedApprove.mockResolvedValue(undefined as never);
    mockedReject.mockResolvedValue(undefined as never);
    mockedBulkApprove.mockResolvedValue({ approved: 1, created_links: 1 } as never);
  });

  it('shows a loading progress indicator on initial render', () => {
    // Keep the request pending so the loading state is observable.
    mockedGetLinks.mockReturnValue(new Promise(() => {}) as never);
    mockedGetStats.mockReturnValue(new Promise(() => {}) as never);
    render(<SuggestedLinksPanel projectId={1} />);
    // LinearProgress renders a progressbar while loading.
    expect(screen.getAllByRole('progressbar').length).toBeGreaterThan(0);
  });

  it('renders an empty message when there are no suggestions', async () => {
    mockedGetLinks.mockResolvedValueOnce(buildResponse([]) as never);
    render(<SuggestedLinksPanel projectId={1} />);
    expect(await screen.findByText(/No suggestions found/i)).toBeInTheDocument();
  });

  it('shows an error message when loading fails', async () => {
    mockedGetLinks.mockRejectedValueOnce(new Error('boom while loading'));
    render(<SuggestedLinksPanel projectId={1} />);
    expect(await screen.findByText('boom while loading')).toBeInTheDocument();
  });

  it('renders the suggestion rows and stats on success', async () => {
    render(<SuggestedLinksPanel projectId={1} />);

    // Artifact identities from the row.
    expect(await screen.findByText('REQ-100')).toBeInTheDocument();
    expect(screen.getByText('PROJ-55')).toBeInTheDocument();

    // Link type, method and similarity percentage are rendered.
    expect(screen.getByText('implements')).toBeInTheDocument();
    expect(screen.getByText('TFIDF')).toBeInTheDocument();
    expect(screen.getByText('82%')).toBeInTheDocument();

    // Stats cards reflect the stats payload.
    expect(screen.getByText('7')).toBeInTheDocument(); // total_approved
    expect(screen.getByText('66%')).toBeInTheDocument(); // avg_similarity_score

    expect(mockedGetLinks).toHaveBeenCalled();
    expect(mockedGetStats).toHaveBeenCalled();
  });

  it('approves a suggestion via the confirmation dialog', async () => {
    render(<SuggestedLinksPanel projectId={1} />);
    await screen.findByText('REQ-100');

    // Row action button (icon-only, accessible name comes from its tooltip).
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));

    // Confirm inside the opened dialog.
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Approve' }));

    await waitFor(() => expect(mockedApprove).toHaveBeenCalledWith(501, undefined));
    // Initial load + reload after approval.
    await waitFor(() => expect(mockedGetLinks).toHaveBeenCalledTimes(2));
  });

  it('rejects a suggestion via the confirmation dialog', async () => {
    render(<SuggestedLinksPanel projectId={1} />);
    await screen.findByText('REQ-100');

    fireEvent.click(screen.getByRole('button', { name: 'Reject' }));

    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Reject' }));

    await waitFor(() => expect(mockedReject).toHaveBeenCalledWith(501, undefined));
  });

  it('triggers generation when the Generate Suggestions button is clicked', async () => {
    render(<SuggestedLinksPanel projectId={1} />);
    await screen.findByText('REQ-100');

    fireEvent.click(screen.getByRole('button', { name: /Generate Suggestions/i }));

    await waitFor(() => expect(mockedGenerate).toHaveBeenCalled());
  });

  it('changing the status filter re-queries with the new status', async () => {
    render(<SuggestedLinksPanel projectId={1} />);
    await screen.findByText('REQ-100');
    mockedGetLinks.mockClear();

    // Open the MUI Select and choose "Approved".
    fireEvent.mouseDown(screen.getByRole('combobox', { name: /Status/i }));
    const listbox = await screen.findByRole('listbox');
    fireEvent.click(within(listbox).getByRole('option', { name: 'Approved' }));

    await waitFor(() =>
      expect(mockedGetLinks).toHaveBeenCalledWith(
        expect.objectContaining({ status: 'approved', projectId: 1 })
      )
    );
  });

  // --- Additional interaction cases (appended) ---

  // A second high-confidence (>= 0.7) pending suggestion so bulk/high-confidence
  // selection has more than one selectable row to work with.
  const secondSuggestion = {
    ...pendingSuggestion,
    id: 502,
    from_artifact_id: 11,
    to_artifact_id: 21,
    similarity_score: 0.91,
    from_artifact: {
      ...pendingSuggestion.from_artifact,
      id: 11,
      external_id: 'REQ-101',
      display_key: 'REQ-101',
      title: 'Logout requirement',
    },
    to_artifact: {
      ...pendingSuggestion.to_artifact,
      id: 21,
      external_id: 'PROJ-56',
      display_key: 'PROJ-56',
      title: 'Implement logout',
    },
  };

  it('minScore filter: changing the similarity slider re-queries with the new minScore', async () => {
    const { container } = render(<SuggestedLinksPanel projectId={1} />);
    await screen.findByText('REQ-100');
    mockedGetLinks.mockClear();

    // MUI <Slider> renders a hidden <input type="range">. Changing it fires
    // onChange (handleMinScoreChange -> setMinScoreFilter), and the component's
    // useEffect([loadData]) re-queries getSuggestedLinks with the new minScore
    // (independently of onChangeCommitted).
    const input = container.querySelector('input[type="range"]') as HTMLInputElement;
    expect(input).not.toBeNull();
    fireEvent.change(input, { target: { value: '0.6' } });

    await waitFor(() =>
      expect(mockedGetLinks).toHaveBeenCalledWith(
        expect.objectContaining({
          minScore: expect.closeTo(0.6, 5),
          projectId: 1,
        })
      )
    );
  });

  it('bulk selection + bulk approve: selecting rows and approving calls bulkApproveSuggestedLinks with the selected ids', async () => {
    mockedGetLinks.mockResolvedValue(
      buildResponse([pendingSuggestion, secondSuggestion]) as never
    );
    render(<SuggestedLinksPanel projectId={1} />);
    await screen.findByText('REQ-100');
    await screen.findByText('REQ-101');

    // Row checkboxes: index 0 is the header "select all" checkbox, then one per row.
    const checkboxes = screen.getAllByRole('checkbox');
    fireEvent.click(checkboxes[1]); // first suggestion (id 501)
    fireEvent.click(checkboxes[2]); // second suggestion (id 502)

    // The bulk approve button only appears once something is selected.
    fireEvent.click(
      await screen.findByRole('button', { name: /Approve Selected \(2\)/i })
    );

    await waitFor(() => expect(mockedBulkApprove).toHaveBeenCalledTimes(1));
    const idsArg = mockedBulkApprove.mock.calls[0][0];
    expect(Array.isArray(idsArg)).toBe(true);
    expect(idsArg).toEqual(expect.arrayContaining([501, 502]));
    expect(idsArg).toHaveLength(2);
  });

  it('bulk selection: "Select High Confidence" selects the >=70% rows then bulk approves them', async () => {
    mockedGetLinks.mockResolvedValue(
      buildResponse([pendingSuggestion, secondSuggestion]) as never
    );
    render(<SuggestedLinksPanel projectId={1} />);
    // Wait for BOTH pending rows (0.82 and 0.91, each >= 0.7) so the
    // "Select High Confidence (2)" control is present.
    await screen.findByText('REQ-100');
    await screen.findByText('REQ-101');

    // The button is wrapped in a MUI <Tooltip>, which overrides the button's
    // accessible NAME with the tooltip title ("Auto-approve … 70%+ similarity").
    // So match the VISIBLE label text instead of role+name; the click bubbles
    // from the text node to the button.
    fireEvent.click(screen.getByText(/Select High Confidence \(2\)/i));

    fireEvent.click(
      await screen.findByRole('button', { name: /Approve Selected \(2\)/i })
    );

    await waitFor(() => expect(mockedBulkApprove).toHaveBeenCalledTimes(1));
    expect(mockedBulkApprove.mock.calls[0][0]).toEqual(
      expect.arrayContaining([501, 502])
    );
  });

  it('note passthrough (approve): a typed note is forwarded to approveSuggestedLink', async () => {
    render(<SuggestedLinksPanel projectId={1} />);
    await screen.findByText('REQ-100');

    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));

    const dialog = await screen.findByRole('dialog');
    const noteField = within(dialog).getByRole('textbox');
    fireEvent.change(noteField, { target: { value: 'Looks correct, approving' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Approve' }));

    await waitFor(() =>
      expect(mockedApprove).toHaveBeenCalledWith(501, 'Looks correct, approving')
    );
  });

  it('note passthrough (reject): a typed note is forwarded to rejectSuggestedLink', async () => {
    render(<SuggestedLinksPanel projectId={1} />);
    await screen.findByText('REQ-100');

    fireEvent.click(screen.getByRole('button', { name: 'Reject' }));

    const dialog = await screen.findByRole('dialog');
    const noteField = within(dialog).getByRole('textbox');
    fireEvent.change(noteField, { target: { value: 'Not a real relationship' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Reject' }));

    await waitFor(() =>
      expect(mockedReject).toHaveBeenCalledWith(501, 'Not a real relationship')
    );
  });
});
