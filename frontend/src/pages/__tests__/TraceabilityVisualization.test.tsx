import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom/vitest';
import { MemoryRouter } from 'react-router-dom';

// Stable global project so the picker loads without Redux/list resolution.
vi.mock('../../hooks/useSelectedProject', () => ({
  useSelectedProject: () => ({
    projectId: 1,
    projects: [{ id: 1, name: 'Apollo', jira_key: 'APOLLO', status: 'active' }],
    selectProject: vi.fn(),
  }),
}));

vi.mock('../../services/api', () => ({
  getRTMMatrix: vi.fn(),
  getConfidenceDistribution: vi.fn(),
}));

// Stub heavy child panels/charts so the test focuses on the picker wiring.
vi.mock('../../components/traceability/TraceabilityGraph', () => ({ default: () => <div data-testid="graph" /> }));
vi.mock('../../components/traceability/ImpactAnalysisPanel', () => ({ default: () => <div /> }));
vi.mock('../../components/traceability/OrphanedArtifactsPanel', () => ({ default: () => <div /> }));
vi.mock('../../components/SuggestedLinksPanel', () => ({ default: () => <div /> }));
vi.mock('../../components/traceability/SyncHealthDashboard', () => ({ default: () => <div /> }));
vi.mock('../../components/traceability/DataConsistencyPanel', () => ({ default: () => <div /> }));

import TraceabilityVisualization from '../TraceabilityVisualization';
import { getRTMMatrix, getConfidenceDistribution } from '../../services/api';

const mockedMatrix = vi.mocked(getRTMMatrix);
const mockedConfidence = vi.mocked(getConfidenceDistribution);

// Empty initial page: isolates the search behavior — no default artifact is
// auto-selected, so the picker input starts empty and the typed query is clean.
const seedRows: { id: number }[] = [];
// An artifact NOT in the initial (seed) page — only reachable via server search.
const searchRows = [
  { id: 999, type: 'requirement', source: 'jira', external_id: 'REQ-999', display_key: 'REQ-999', title: 'Deep artifact' },
];

describe('TraceabilityVisualization artifact picker (M10 server-side search)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedConfidence.mockResolvedValue({ histogram: [], stats: {} } as never);
    // Seed load has no searchQuery; a typed search passes searchQuery.
    mockedMatrix.mockImplementation((opts?: { searchQuery?: string }) =>
      Promise.resolve((opts?.searchQuery ? { rows: searchRows } : { rows: seedRows }) as never),
    );
  });

  it('server-searches with typed text so artifacts beyond the first page are selectable', async () => {
    const user = userEvent.setup({ delay: null });
    render(
      <MemoryRouter>
        <TraceabilityVisualization />
      </MemoryRouter>,
    );

    // Initial seed load: paged, no search term.
    await waitFor(() =>
      expect(mockedMatrix).toHaveBeenCalledWith(expect.objectContaining({ projectId: 1, rowLimit: 200 })),
    );

    // Type a key that is NOT in the seed page. The input is pre-seeded with the
    // default artifact's label, so clear it first.
    const input = screen.getByLabelText('Artifact');
    await user.click(input);
    await user.type(input, 'REQ-999');

    // Debounced server search fires with the typed query (matches title/key/external_id).
    await waitFor(() =>
      expect(mockedMatrix).toHaveBeenCalledWith(
        expect.objectContaining({ projectId: 1, searchQuery: 'REQ-999' }),
      ),
    );

    // The deep artifact (beyond the seed page) becomes a selectable option.
    expect(await screen.findByText(/Deep artifact/)).toBeInTheDocument();
  }, 20000);
});
