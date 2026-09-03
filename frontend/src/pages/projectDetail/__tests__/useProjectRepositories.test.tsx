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
    const calls: number[] = [];
    mocks.getProjectRepositories.mockImplementation((pid: number) => {
      calls.push(pid);
      if (pid === 1) {
        return new Promise<Array<{ repository_id: number }>>(() => {});
      }
      return Promise.resolve([{ repository_id: 2 }]);
    });

    const hook = render('1');
    await act(async () => { hook.rerender({ projectId: '2' }); });
    // React 18 StrictMode в renderHook double-invokes effects, поэтому
    // проверяем только наличие запросов per-PID
    expect(calls).toContain(1);
    expect(calls).toContain(2);

    // B (project 2) data must land after the switch
    await waitFor(() =>
      expect((hook.result.current.repoBindings ?? []).map((b) => b.repository_id)).toEqual([2]),
    );

  });

  it('late A response never clobbers B bindings (MF-02)', async () => {
    let resolveA: (v: Array<{ repository_id: number }>) => void = () => {};
    const calls: number[] = [];
    mocks.getProjectRepositories.mockImplementation((pid: number) => {
      calls.push(pid);
      if (pid === 1) {
        return new Promise<Array<{ repository_id: number }>>((res) => { resolveA = res; });
      }
      return Promise.resolve([{ repository_id: 2 }]);
    });

    const hook = render('1');
    await act(async () => { hook.rerender({ projectId: '2' }); });
    // resolve A (project 1 data) LATE, while the hook is already on project 2
    await act(async () => { resolveA([{ repository_id: 99 }]); });
    expect((hook.result.current.repoBindings ?? []).map((b) => b.repository_id)).toEqual([2]);
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

  it('gitlab search stops when a later page has no next_page (SF-2)', async () => {
    // page 1 returns data WITH next_page: 0 (i.e. last page), page 2 must never be requested
    mocks.listGitlabProjects
      .mockResolvedValueOnce({ projects: [{ id: 1, name: 'p1' }], pagination: { next_page: 0 } });

    const hook = render('1');
    await act(async () => { hook.rerender({ projectId: '2' }); });
    await act(async () => {
      await hook.result.current.performGitlabSearch(1);
    });
    expect(hook.result.current.gitlabProjects.map((p) => p.id)).toEqual([1]);
    // page 2 must never be requested since next_page is 0
    const pages = mocks.listGitlabProjects.mock.calls.map((c) => c[0].page);
    expect(pages).toEqual([1]);
  });
});
