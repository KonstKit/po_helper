import React from 'react';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';

// ---------------------------------------------------------------------------
// jsdom does not implement SVG layout primitives that d3 relies on. The
// component's "zoom-to-fit" routine calls getBBox() (and the responsive
// effect reads getBoundingClientRect on the container). Stub them so real d3
// can run without throwing. We assert on semantic state only, never geometry.
// ---------------------------------------------------------------------------
beforeAll(() => {
  (window.SVGElement.prototype as unknown as { getBBox: () => DOMRect }).getBBox =
    () => ({ x: 0, y: 0, width: 20, height: 12 } as DOMRect);
  (window.SVGElement.prototype as unknown as { getBoundingClientRect: () => DOMRect }).getBoundingClientRect =
    () => ({ x: 0, y: 0, width: 900, height: 600, top: 0, left: 0, right: 900, bottom: 600, toJSON: () => ({}) } as DOMRect);
});

// Mock ONLY the data-layer function the component imports. The component also
// imports the FullChainNode / FullChainResponse *types* from this module, but
// those are type-only and erased at compile time, so no runtime stub is needed.
vi.mock('../../services/api', () => ({
  getFullTraceabilityChain: vi.fn(),
}));

import TraceabilityGraph from './TraceabilityGraph';
import { getFullTraceabilityChain } from '../../services/api';
import type { FullChainResponse } from '../../services/api';

const mockedGetChain = vi.mocked(getFullTraceabilityChain);

const ARTIFACT_ID = 101;

// Realistic payload matching FullChainResponse in services/api/types.ts:
// center_artifact_id, nodes[], edges[], levels, stats{ total_* }.
const buildChain = (
  overrides: Partial<FullChainResponse> = {}
): FullChainResponse => ({
  center_artifact_id: ARTIFACT_ID,
  nodes: [
    {
      id: ARTIFACT_ID,
      type: 'requirement',
      source: 'internal',
      external_id: 'REQ-42',
      display_key: 'REQ-42',
      title: 'Login must support SSO',
      status: 'approved',
      url: null,
      level: 0,
    },
    {
      id: 202,
      type: 'jira_issue',
      source: 'jira',
      external_id: 'PROJ-7',
      display_key: 'PROJ-7',
      title: 'Implement SSO handshake',
      status: 'in_progress',
      url: null,
      level: 1,
    },
  ],
  edges: [
    {
      from_id: ARTIFACT_ID,
      to_id: 202,
      link_type: 'implements',
      confidence: 0.9,
      confidence_factors: null,
    },
  ],
  levels: { 0: [ARTIFACT_ID], 1: [202] },
  stats: {
    total_nodes: 2,
    total_edges: 1,
    max_depth_upstream: 0,
    max_depth_downstream: 1,
  },
  ...overrides,
});

const emptyChain: FullChainResponse = {
  center_artifact_id: ARTIFACT_ID,
  nodes: [],
  edges: [],
  levels: {},
  stats: {
    total_nodes: 0,
    total_edges: 0,
    max_depth_upstream: 0,
    max_depth_downstream: 0,
  },
};

describe('TraceabilityGraph', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetChain.mockResolvedValue(buildChain());
  });

  it('shows a loading indicator before data resolves', () => {
    // Never-resolving promise keeps the component in its initial loading state.
    mockedGetChain.mockReturnValue(new Promise<FullChainResponse>(() => {}));
    render(<TraceabilityGraph artifactId={ARTIFACT_ID} />);

    expect(screen.getByRole('progressbar')).toBeInTheDocument();
    expect(mockedGetChain).toHaveBeenCalledWith(
      ARTIFACT_ID,
      expect.objectContaining({ depth: 3, direction: 'both', minConfidence: 0 })
    );
  });

  it('renders an empty-but-valid chain with zero-count stats and no node labels', async () => {
    mockedGetChain.mockResolvedValue(emptyChain);
    render(<TraceabilityGraph artifactId={ARTIFACT_ID} />);

    // The controls + stat chips render once loading completes. An empty chain
    // surfaces as "0 nodes" / "0 links" rather than a textual placeholder.
    expect(await screen.findByText('0 nodes')).toBeInTheDocument();
    expect(screen.getByText('0 links')).toBeInTheDocument();

    // No node-label <text> elements should have been drawn into the SVG.
    const svg = document.querySelector('svg') as SVGSVGElement;
    expect(svg).not.toBeNull();
    expect(within(svg as unknown as HTMLElement).queryByText('REQ-42')).not.toBeInTheDocument();
    expect(svg.querySelectorAll('g.node').length).toBe(0);
  });

  it('shows an error message when the chain fails to load', async () => {
    mockedGetChain.mockRejectedValueOnce(new Error('chain service unavailable'));
    render(<TraceabilityGraph artifactId={ARTIFACT_ID} />);

    expect(await screen.findByText('chain service unavailable')).toBeInTheDocument();
    // Loading spinner is gone and no graph stats are shown on error.
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    expect(screen.queryByText(/nodes$/)).not.toBeInTheDocument();
  });

  it('renders node labels and chain stats on success', async () => {
    render(<TraceabilityGraph artifactId={ARTIFACT_ID} />);

    // d3 draws each node label as an SVG <text> with display_key/external_id.
    expect(await screen.findByText('REQ-42')).toBeInTheDocument();
    expect(screen.getByText('PROJ-7')).toBeInTheDocument();

    // Stats chips reflect the response.stats counts.
    expect(screen.getByText('2 nodes')).toBeInTheDocument();
    expect(screen.getByText('1 links')).toBeInTheDocument();

    // One node group per node (semantic count, not geometry). Query the
    // document, not the first <svg> — MUI icons also render <svg> elements.
    expect(document.querySelectorAll('g.node').length).toBe(2);
  });

  it('refetches the chain when the Refresh control is clicked', async () => {
    render(<TraceabilityGraph artifactId={ARTIFACT_ID} />);
    await screen.findByText('REQ-42');
    expect(mockedGetChain).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: /refresh/i }));

    await waitFor(() => expect(mockedGetChain).toHaveBeenCalledTimes(2));
  });

  it('re-queries with the new direction when the Direction filter changes', async () => {
    render(<TraceabilityGraph artifactId={ARTIFACT_ID} />);
    await screen.findByText('REQ-42');

    // MUI Select renders a button-like combobox; open it then pick "Upstream".
    fireEvent.mouseDown(screen.getByRole('combobox'));
    fireEvent.click(await screen.findByRole('option', { name: 'Upstream' }));

    await waitFor(() =>
      expect(mockedGetChain).toHaveBeenLastCalledWith(
        ARTIFACT_ID,
        expect.objectContaining({ direction: 'upstream' })
      )
    );
  });

  it('invokes onNodeClick with the node datum when a node is clicked', async () => {
    const onNodeClick = vi.fn();
    render(<TraceabilityGraph artifactId={ARTIFACT_ID} onNodeClick={onNodeClick} />);
    await screen.findByText('REQ-42');

    // Click the node group that owns the REQ-42 label (d3 wires .on('click')
    // on g.node); the event bubbles from the <text> child to the group.
    const nodeG = screen.getByText('REQ-42').closest('g.node');
    expect(nodeG).not.toBeNull();
    fireEvent.click(nodeG as Element);

    await waitFor(() => expect(onNodeClick).toHaveBeenCalledTimes(1));
    expect(onNodeClick.mock.calls[0][0]).toEqual(
      expect.objectContaining({ id: ARTIFACT_ID, external_id: 'REQ-42' })
    );
  });
});
