import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';

vi.mock('../../services/api', () => ({
  getImpactAnalysis: vi.fn(),
}));

import ImpactAnalysisPanel from './ImpactAnalysisPanel';
import { getImpactAnalysis } from '../../services/api';
import type { ImpactAnalysisResponse } from '../../services/api';

const mockedGetImpactAnalysis = vi.mocked(getImpactAnalysis);

const ARTIFACT_ID = 101;

const successResponse: ImpactAnalysisResponse = {
  source_artifact_id: ARTIFACT_ID,
  change_type: 'modify',
  directly_affected: [
    {
      id: 201,
      type: 'jira_issue',
      title: 'Direct ticket PROJ-201',
      status: 'open',
      distance: 1,
      path: [ARTIFACT_ID, 201],
      impact_type: 'direct',
    },
  ],
  indirectly_affected: [
    {
      id: 301,
      type: 'commit',
      title: 'Indirect commit abc123',
      status: null,
      distance: 2,
      path: [ARTIFACT_ID, 201, 301],
      impact_type: 'indirect',
    },
  ],
  risk_score: 0.75,
  risk_level: 'high',
  recommendations: ['Re-run regression tests', 'Notify the QA team'],
  stats: {
    total_affected: 2,
    direct_count: 1,
    indirect_count: 1,
    affected_types: { jira_issue: 1, commit: 1 },
  },
};

const emptyResponse: ImpactAnalysisResponse = {
  source_artifact_id: ARTIFACT_ID,
  change_type: 'modify',
  directly_affected: [],
  indirectly_affected: [],
  risk_score: 0,
  risk_level: 'low',
  recommendations: [],
  stats: {
    total_affected: 0,
    direct_count: 0,
    indirect_count: 0,
    affected_types: {},
  },
};

describe('ImpactAnalysisPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetImpactAnalysis.mockResolvedValue(successResponse);
  });

  it('renders the initial prompt before any analysis is run', () => {
    render(<ImpactAnalysisPanel artifactId={ARTIFACT_ID} artifactTitle="Login requirement" />);

    // Initial state: no fetch yet, instructional prompt is shown.
    expect(
      screen.getByText(/Click .*Run Analysis.* to see the impact/i)
    ).toBeInTheDocument();
    expect(screen.getByText('Login requirement')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Run Analysis/i })).toBeInTheDocument();
    expect(mockedGetImpactAnalysis).not.toHaveBeenCalled();
  });

  it('shows empty messages when no artifacts are affected', async () => {
    mockedGetImpactAnalysis.mockResolvedValueOnce(emptyResponse);
    render(<ImpactAnalysisPanel artifactId={ARTIFACT_ID} />);

    fireEvent.click(screen.getByRole('button', { name: /Run Analysis/i }));

    expect(await screen.findByText('No directly affected artifacts')).toBeInTheDocument();
    expect(screen.getByText('No indirectly affected artifacts')).toBeInTheDocument();
    // Both section headers report a zero count.
    expect(screen.getByText('Directly Affected (0)')).toBeInTheDocument();
    expect(screen.getByText('Indirectly Affected (0)')).toBeInTheDocument();
  });

  it('shows an error message when the analysis request fails', async () => {
    mockedGetImpactAnalysis.mockRejectedValueOnce(new Error('analysis blew up'));
    render(<ImpactAnalysisPanel artifactId={ARTIFACT_ID} />);

    fireEvent.click(screen.getByRole('button', { name: /Run Analysis/i }));

    expect(await screen.findByText('analysis blew up')).toBeInTheDocument();
  });

  it('renders affected artifacts, risk level and counts on success', async () => {
    render(<ImpactAnalysisPanel artifactId={ARTIFACT_ID} />);

    fireEvent.click(screen.getByRole('button', { name: /Run Analysis/i }));

    // Affected artifact titles render in their respective sections.
    expect(await screen.findByText('Direct ticket PROJ-201')).toBeInTheDocument();
    expect(screen.getByText('Indirect commit abc123')).toBeInTheDocument();

    // Risk summary derived from the payload.
    expect(screen.getByText(/Risk Level: HIGH/)).toBeInTheDocument();
    expect(screen.getByText(/Score: 75%/)).toBeInTheDocument();

    // Stat chips reflect the counts from the response.
    expect(screen.getByText('2 affected')).toBeInTheDocument();
    expect(screen.getByText('1 direct')).toBeInTheDocument();
    expect(screen.getByText('1 indirect')).toBeInTheDocument();

    // Section headers include the affected counts.
    expect(screen.getByText('Directly Affected (1)')).toBeInTheDocument();
    expect(screen.getByText('Indirectly Affected (1)')).toBeInTheDocument();

    // Recommendations surface to the user.
    expect(screen.getByText('Re-run regression tests')).toBeInTheDocument();
  });

  it('calls getImpactAnalysis with the artifact id and current change type on click', async () => {
    render(<ImpactAnalysisPanel artifactId={ARTIFACT_ID} />);

    fireEvent.click(screen.getByRole('button', { name: /Run Analysis/i }));

    await waitFor(() =>
      expect(mockedGetImpactAnalysis).toHaveBeenCalledWith(ARTIFACT_ID, { changeType: 'modify' })
    );
    expect(mockedGetImpactAnalysis).toHaveBeenCalledTimes(1);
  });

  it('invokes onArtifactClick when an affected artifact is clicked', async () => {
    const onArtifactClick = vi.fn();
    render(<ImpactAnalysisPanel artifactId={ARTIFACT_ID} onArtifactClick={onArtifactClick} />);

    fireEvent.click(screen.getByRole('button', { name: /Run Analysis/i }));

    const directItem = await screen.findByText('Direct ticket PROJ-201');
    fireEvent.click(directItem);

    expect(onArtifactClick).toHaveBeenCalledWith(201);
  });
});
