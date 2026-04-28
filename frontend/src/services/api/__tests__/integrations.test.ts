import { beforeEach, describe, expect, it, vi } from 'vitest';

const { postMock } = vi.hoisted(() => ({
  postMock: vi.fn(),
}));

vi.mock('../client', () => ({
  default: {
    post: postMock,
  },
}));

import { connectJira } from '../integrations';

describe('connectJira', () => {
  beforeEach(() => {
    postMock.mockReset();
    postMock.mockResolvedValue({ data: { status: 'connected' } });
  });

  it('sends Jira credentials in the JSON body instead of query params', async () => {
    await connectJira({
      baseUrl: 'https://example.atlassian.net',
      email: 'user@example.com',
      apiToken: 'token',
      save: false,
      usePat: false,
    });

    expect(postMock).toHaveBeenCalledTimes(1);
    expect(postMock).toHaveBeenCalledWith('/v1/jira/connect', {
      base_url: 'https://example.atlassian.net',
      email: 'user@example.com',
      api_token: 'token',
      save: false,
      use_pat: false,
    });
  });
});
