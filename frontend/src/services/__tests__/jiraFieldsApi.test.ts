import { beforeEach, describe, expect, it, vi } from 'vitest';

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock('../api', () => ({
  default: apiMock,
}));

import {
  discoverJiraFields,
  saveFieldMapping,
} from '../jiraFieldsApi';

describe('jiraFieldsApi', () => {
  beforeEach(() => {
    apiMock.get.mockReset();
    apiMock.post.mockReset();
    apiMock.delete.mockReset();
    globalThis.fetch = vi.fn();
  });

  it('discovers Jira fields through the shared axios client', async () => {
    apiMock.get.mockResolvedValue({
      data: { total_fields: 1, custom_fields: 0, standard_fields: 1, mappings: {}, all_fields: {} },
    });

    await discoverJiraFields(true);

    expect(apiMock.get).toHaveBeenCalledWith('/v1/jira-fields/fields', {
      params: { force_refresh: true },
    });
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it('saves field mappings through the shared axios client', async () => {
    apiMock.post.mockResolvedValue({
      data: { field_type: 'story_points', field_id: 'customfield_10016', status: 'saved' },
    });

    await saveFieldMapping('story_points', 'customfield_10016', 'WAB');

    expect(apiMock.post).toHaveBeenCalledWith('/v1/jira-fields/mappings', undefined, {
      params: {
        field_type: 'story_points',
        field_id: 'customfield_10016',
        project_key: 'WAB',
      },
    });
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });
});
