import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import projectReducer from '../../store/projectSlice';

vi.mock('../../services/api', () => ({
  listReviewItems: vi.fn(),
  claimReviewItem: vi.fn(),
  resolveReviewItem: vi.fn(),
  rejectReviewItem: vi.fn(),
}));

import ReviewQueue from '../ReviewQueue';
import {
  claimReviewItem,
  listReviewItems,
  rejectReviewItem,
  resolveReviewItem,
} from '../../services/api';

const mockedList = vi.mocked(listReviewItems);
const mockedClaim = vi.mocked(claimReviewItem);
const mockedResolve = vi.mocked(resolveReviewItem);
const mockedReject = vi.mocked(rejectReviewItem);

const pendingItem = {
  id: 11,
  project_id: 1,
  artifact_id: 101,
  rule_id: 5,
  node_id: 'review-1',
  status: 'pending' as const,
  priority: 'high',
  reason: 'low confidence',
  meta: { external_id: 'REQ-42' },
};

// ReviewQueue now sources its project from the single global selector
// (UX review C5) via `useSelectedProject`, which reads Redux. Render it under a
// store preloaded with a project so the hook neither calls the project API nor
// renders the "no projects" path.
const sampleProject = {
  id: 1,
  jira_key: 'APOLLO',
  name: 'Apollo',
  status: 'active',
  total_tasks: 3,
};

const renderRQ = () => {
  const store = configureStore({
    reducer: { project: projectReducer },
    preloadedState: {
      project: {
        projects: [sampleProject],
        currentProject: sampleProject,
        loading: false,
        error: null,
        lastLoadedAt: null,
      },
    },
  });
  return render(
    <Provider store={store}>
      <ReviewQueue />
    </Provider>
  );
};

describe('ReviewQueue', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedList.mockResolvedValue({ total: 1, items: [pendingItem] } as never);
    mockedClaim.mockResolvedValue({ ...pendingItem, status: 'claimed' } as never);
    mockedResolve.mockResolvedValue({ ...pendingItem, status: 'resolved' } as never);
    mockedReject.mockResolvedValue({ ...pendingItem, status: 'rejected' } as never);
  });

  it('lists pending review items with artifact identity', async () => {
    renderRQ();
    expect(await screen.findByText('REQ-42')).toBeInTheDocument();
    expect(mockedList).toHaveBeenCalled();
  });

  it('shows empty state when there are no items', async () => {
    mockedList.mockResolvedValueOnce({ total: 0, items: [] } as never);
    renderRQ();
    expect(await screen.findByText('No review items')).toBeInTheDocument();
  });

  it('shows an error with retry when loading fails', async () => {
    mockedList.mockRejectedValueOnce(new Error('load failed'));
    renderRQ();
    expect(await screen.findByText('load failed')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('claims a pending item', async () => {
    renderRQ();
    await screen.findByText('REQ-42');
    fireEvent.click(screen.getByRole('button', { name: 'Claim' }));
    await waitFor(() => expect(mockedClaim).toHaveBeenCalledWith(11));
  });

  it('resolves an item and refetches', async () => {
    renderRQ();
    await screen.findByText('REQ-42');
    fireEvent.click(screen.getByRole('button', { name: 'Resolve' }));
    await waitFor(() => expect(mockedResolve).toHaveBeenCalledWith(11));
    // initial load + refetch after action
    await waitFor(() => expect(mockedList).toHaveBeenCalledTimes(2));
  });

  it('rejects an item', async () => {
    renderRQ();
    await screen.findByText('REQ-42');
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }));
    await waitFor(() => expect(mockedReject).toHaveBeenCalledWith(11));
  });
});
