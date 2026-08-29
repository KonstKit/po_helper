import { describe, beforeEach, afterEach, expect, it, vi } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import '@testing-library/jest-dom';

vi.mock('../../services/api', () => ({
  listProjects: vi.fn(),
  getTraceabilityMatrix: vi.fn(),
  runTraceabilityBackfill: vi.fn(),
  getTraceabilityRequirementFlow: vi.fn(),
  getTraceabilityTaskArtifacts: vi.fn(),
  listGitlabProjects: vi.fn(),
}));

import Traceability from '../Traceability';
import {
  listProjects,
  getTraceabilityMatrix,
  runTraceabilityBackfill,
  getTraceabilityRequirementFlow,
  getTraceabilityTaskArtifacts,
  listGitlabProjects,
} from '../../services/api';

const mockedListProjects = vi.mocked(listProjects);
const mockedGetTraceabilityMatrix = vi.mocked(getTraceabilityMatrix);
const mockedRunTraceabilityBackfill = vi.mocked(runTraceabilityBackfill);
const mockedGetTraceabilityRequirementFlow = vi.mocked(getTraceabilityRequirementFlow);
const mockedGetTraceabilityTaskArtifacts = vi.mocked(getTraceabilityTaskArtifacts);
const mockedListGitlabProjects = vi.mocked(listGitlabProjects);

describe('Traceability page', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    mockedListProjects.mockResolvedValue({
      data: [
        {
          id: 1,
          jira_key: 'TRACE',
          name: 'Trace Project',
          status: 'active',
        },
      ],
      meta: {
        total: 1,
        page: 1,
        per_page: 50,
        total_pages: 1,
        has_next: false,
        has_prev: false,
      },
    });

    mockedGetTraceabilityMatrix.mockResolvedValue({
      total: 2,
      by_type: {
        jira_issue: 1,
        commit: 1,
      },
      per_type: {
        jira_issue: {
          total: 1,
          linked: 1,
          unlinked: 0,
          link_count: 2,
          coverage_pct: 100,
          avg_links_per_artifact: 2,
          link_type_counts: {
            implements: 2,
            tests: 1,
          },
          link_type_artifact_counts: {
            implements: 1,
            tests: 1,
          },
        },
        commit: {
          total: 1,
          linked: 1,
          unlinked: 0,
          link_count: 1,
          coverage_pct: 100,
          avg_links_per_artifact: 1,
          link_type_counts: {
            derives_from: 1,
          },
          link_type_artifact_counts: {
            derives_from: 1,
          },
        },
      },
      coverage: {
        linked_artifacts: 1,
        coverage_pct: 50,
      },
    });

    mockedRunTraceabilityBackfill.mockResolvedValue({
      status: 'ok',
      created: 0,
      updated: 0,
      warnings: [],
      sources: {
        git: { project_id: 1, repositories: [] },
      },
      git: { project_id: 1, repositories: [] },
    });

    mockedListGitlabProjects.mockResolvedValue({ count: 0, projects: [], pagination: {}, source: '' });

    mockedGetTraceabilityRequirementFlow.mockResolvedValue({
      nodes: [
        { id: 101, type: 'requirement', title: 'Feature ABC', status: 'Open' },
        { id: 201, type: 'commit', title: 'Initial commit', status: null },
      ],
      edges: [
        { from: 101, to: 201, type: 'implements', confidence: 0.9 },
      ],
    });

    mockedGetTraceabilityTaskArtifacts.mockResolvedValue({
      task_artifact: { id: 101, key: 'ABC-1' },
      outgoing: [],
      incoming: [],
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders matrix snapshot and loads flow by artifact id', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        
      <MemoryRouter
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Traceability />
      </MemoryRouter>
      </QueryClientProvider>
    );

    await waitFor(() => expect(listProjects).toHaveBeenCalled());
    await waitFor(() => expect(getTraceabilityMatrix).toHaveBeenCalled());

    expect(await screen.findByText(/Coverage snapshot/i)).toBeInTheDocument();
    expect(await screen.findByText(/implements: 2/i)).toBeInTheDocument();
    expect(screen.getByText(/Commit/i)).toBeInTheDocument();

    const artifactInput = screen.getByLabelText(/Artifact ID/i);
    fireEvent.change(artifactInput, { target: { value: '101' } });
    fireEvent.click(screen.getByRole('button', { name: /load by id/i }));

    await waitFor(() => expect(getTraceabilityRequirementFlow).toHaveBeenCalledWith(101, { depth: 3 }));
    await waitFor(() => expect(screen.getByText(/Drilldown/i)).toBeInTheDocument());
  });
});
