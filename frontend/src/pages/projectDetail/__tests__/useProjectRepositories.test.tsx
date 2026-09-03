import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';

const mocks = vi.hoisted(() => ({
  getProjectRepositories: vi.fn(),
  getIntegrationsStatus: vi.fn(),
  clearIntegrationStatusCache: vi.fn(),
  listGitlabProjects: vi.fn(),
  bindRepositoryToProject: vi.fn(),
  unbindRepositoryFromProject: vi.fn(),
  setPrimaryRepository: vi.fn(),
}));

vi.mock('../../../services/api', () => ({
  getProjectRepositories: mocks.getProjectRepositories,
  getIntegrationsStatus: mocks.getIntegrationsStatus,
  clearIntegrationStatusCache: mocks.clearIntegrationStatusCache,
  bindRepositoryToProject: vi.fn(),
  unbindRepositoryFromProject: vi.fn(),
  setPrimaryRepository: vi.fn(),
  listGitlabProjects: mocks.listGitlabProjects,
}));

import { useProjectRepositories } from '../useProjectRepositories';
import * as apiModule from '../../../services/api';


const flush = () => new Promise((r) => setTimeout(r, 0));

describe('useProjectRepositories', () => {
  it('mock module is wired', () => {
    expect(apiModule.getProjectRepositories).toBe(mocks.getProjectRepositories);
  });

  const showToast = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getIntegrationsStatus.mockResolvedValue({
      github: { configured: true, has_token: true },
      gitlab: { configured: true, has_token: true },
    });
  });

  const render = (projectId: string = '1') =>
    renderHook((props: { projectId: string }) => useProjectRepositories({ projectId: props.projectId, showToast }), {
      initialProps: { projectId },
      wrapper: ({ children }: { children: ReactNode }) => <>{children}</>,
    });

  it('loads bindings once per project and ignores stale responses on A->B switch (MF-02)', async () => {
    let resolveA: (v: never[]) => void = () => {};
    mocks.getProjectRepositories.mockImplementation((pid: number) =>
      pid === 1
        ? new Promise<never>(() => { resolveA = () => {}; })
        : Promise.resolve([{ repository_id: 2 }]),
    );

    const hook = render('1');
    await waitFor(() => expect(mocks.getProjectRepositories).toHaveBeenCalled());
    // switch to project 2 before A resolves
    await act(async () => { hook.rerender({ projectId: '2' }); });
    await flush();
    expect(mocks.getProjectRepositories).toHaveBeenCalledWith(2);

    // while A hangs, project-2 bindings (B) must land
    await waitFor(() =>
      expect(
        (hook.result.current.repoBindings ?? []).map((b) => b.repository_id),
      ).toEqual([2]),
    );
    // and the abandoned A response stays abandoned
    await act(async () => { resolveA([]); });
    await waitFor(() =>
      expect(
        (hook.result.current.repoBindings ?? []).map((b) => b.repository_id),
      ).toEqual([2]),
    );
  });

  it('marks the first binding as primary on dialog reopen (MF-01)', async () => {
    mocks.getProjectRepositories.mockResolvedValue([]);
    const hook = render('1');
    await flush();
    // open dialog -> close -> open; form reset must keep isPrimary=true
    await act(async () => { hook.result.current.setRepoDialogOpen(true); });
    await flush();
    await act(async () => { hook.result.current.setRepoDialogOpen(false); });
    await act(async () => { hook.result.current.setRepoDialogOpen(true); });
    await flush();
    expect(hook.result.current.repoForm.isPrimary).toBe(true);
  });

  it('resetGitlabResults clears results and pagination cursor', async () => {
    mocks.getProjectRepositories.mockResolvedValue([]);
    const hook = render('1');
    await act(async () => {
      hook.result.current.setGitlabSearch('term');
      hook.result.current.resetGitlabResults();
    });
    expect(hook.result.current.gitlabProjects).toEqual([]);
    expect(hook.result.current.gitlabHasNextPageRef.current).toBe(false);
  });

  it('gitlab search replaces on page 1 and appends page 2 (SF-2)', async () => {
    mocks.listGitlabProjects
      .mockResolvedValueOnce({ projects: [{ id: 10, name: 'p1' }], pagination: { next_page: 2 } })
      .mockResolvedValueOnce({ projects: [{ id: 11, name: 'p2' }], pagination: { next_page: null } });

    const hook = render('1');
    await act(async () => { hook.rerender({ projectId: '2' }); });
    await act(async () => {
      await hook.result.current.performGitlabSearch(1);
    });
    await act(async () => {
      await hook.result.current.performGitlabSearch(2, { append: true });
    });
    expect(hook.result.current.gitlabProjects.map((p) => p.id)).toEqual([10, 11]);
  });

  it('gitlab search treats zero next_page as the last page (SF-2)', async () => {
    mocks.listGitlabProjects
      .mockResolvedValueOnce({ projects: [{ id: 1 }], pagination: {} });

    const hook = render('1');
    await act(async () => { hook.rerender({ projectId: '2' }); });
    await act(async () => {
      await hook.result.current.performGitlabSearch(1);
    });
    await act(async () => {
      await hook.result.current.performGitlabSearch(2, { append: true });
    });
    // no next page -> append is skipped, results stay as after page 1
    expect(hook.result.current.gitlabProjects).toEqual([{ id: 1 }]);
  });
});
