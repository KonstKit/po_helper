import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getMock, postMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  postMock: vi.fn(),
}));

vi.mock('../client', () => ({
  default: { get: getMock, post: postMock },
  withRetry: (fn: unknown) => fn,
}));

import {
  claimReviewItem,
  listReviewItems,
  rejectReviewItem,
  reopenReviewItem,
  resolveReviewItem,
} from '../traceability';

describe('review queue API client', () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
    getMock.mockResolvedValue({ data: { total: 0, items: [] } });
    postMock.mockResolvedValue({ data: { id: 1, status: 'claimed' } });
  });

  it('maps list filters to backend query params', async () => {
    await listReviewItems({ projectId: 3, status: 'pending', ruleId: 9, limit: 25 });
    expect(getMock).toHaveBeenCalledWith('/v1/traceability/review-items', {
      params: { skip: 0, limit: 25, project_id: 3, status: 'pending', rule_id: 9 },
    });
  });

  it('omits undefined filters', async () => {
    await listReviewItems();
    expect(getMock).toHaveBeenCalledWith('/v1/traceability/review-items', {
      params: { skip: 0, limit: 50 },
    });
  });

  it('claim posts to the claim endpoint with no body', async () => {
    await claimReviewItem(11);
    expect(postMock).toHaveBeenCalledWith(
      '/v1/traceability/review-items/11/claim',
      undefined
    );
  });

  it('resolve/reject/reopen post a note body when provided', async () => {
    await resolveReviewItem(11, 'done');
    expect(postMock).toHaveBeenCalledWith('/v1/traceability/review-items/11/resolve', {
      note: 'done',
    });

    await rejectReviewItem(12, 'nope');
    expect(postMock).toHaveBeenCalledWith('/v1/traceability/review-items/12/reject', {
      note: 'nope',
    });

    await reopenReviewItem(13);
    expect(postMock).toHaveBeenCalledWith(
      '/v1/traceability/review-items/13/reopen',
      undefined
    );
  });
});
