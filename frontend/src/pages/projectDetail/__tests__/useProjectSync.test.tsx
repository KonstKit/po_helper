
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  syncJiraProject: vi.fn(),
  purgeProject: vi.fn(),
  getIntegrationsStatus: vi.fn(),
  listTasksByProjectPaginated: vi.fn(),
  clearIntegrationStatusCache: vi.fn(),
  openWebSocket: vi.fn(),
}));

vi.mock("../../../services/api", () => ({
  api: { get: mocks.apiGet },
  syncJiraProject: mocks.syncJiraProject,
  purgeProject: mocks.purgeProject,
  getIntegrationsStatus: mocks.getIntegrationsStatus,
  listTasksByProjectPaginated: mocks.listTasksByProjectPaginated,
  clearIntegrationStatusCache: mocks.clearIntegrationStatusCache,
  openWebSocket: mocks.openWebSocket,
}));

import { useProjectSync } from "../useProjectSync";

const jiraConfigured = {
  jira: { configured: true, has_token: true },
};

const page = { current: { page: 0, pageSize: 25 } };

type FakeWs = {
  close: () => void;
  onmessage: ((ev: { data: string }) => void) | null;
  onclose: (() => void) | null;
};

describe("useProjectSync", () => {
  const showToast = vi.fn();
  const logNonFatal = vi.fn();
  const onTasksLoaded = vi.fn();
  const onProjectReload = vi.fn().mockResolvedValue(undefined);

  const render = (projectId: string | undefined = "1", jiraKey = "KEY") =>
    renderHook(
      (props: { projectId: string | undefined; jiraKey: string }) =>
        useProjectSync({
          projectId: props.projectId,
          jiraKey: props.jiraKey,
          taskPaginationRef: page,
          showToast,
          logNonFatal,
          onTasksLoaded,
          onProjectReload,
        }),
      { initialProps: { projectId, jiraKey } },
    );

  beforeEach(() => {
    vi.resetAllMocks();
    vi.useRealTimers();
    mocks.getIntegrationsStatus.mockResolvedValue(jiraConfigured);
    mocks.openWebSocket.mockResolvedValue(null);
    mocks.syncJiraProject.mockResolvedValue({});
    onProjectReload.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("manual sync warns when the project has no jira key", async () => {
    const hook = render("1", "");
    await act(async () => {
      await hook.result.current.handleManualSync();
    });
    expect(mocks.syncJiraProject).not.toHaveBeenCalled();
    expect(showToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: "warning" }),
    );
  });

  it("manual sync warns when jira is not configured", async () => {
    mocks.getIntegrationsStatus.mockResolvedValue({
      jira: { configured: true, has_token: false },
    });
    const hook = render();
    await act(async () => {
      await hook.result.current.handleManualSync();
    });
    expect(mocks.syncJiraProject).not.toHaveBeenCalled();
    expect(showToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: "warning", msg: "Jira not configured or token missing" }),
    );
  });

  it("manual sync starts the background sync and reports it", async () => {
    const hook = render();
    await act(async () => {
      await hook.result.current.handleManualSync();
    });
    expect(mocks.syncJiraProject).toHaveBeenCalledWith("KEY", { timeout: 15000 });
    expect(showToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: "info" }),
    );
    expect(hook.result.current.syncing).toBe(true);
  });

  it("manual sync surfaces a failure toast and resets state", async () => {
    mocks.syncJiraProject.mockRejectedValue(new Error("boom"));
    const hook = render();
    await act(async () => {
      await hook.result.current.handleManualSync();
    });
    expect(showToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: "error" }),
    );
    expect(hook.result.current.syncing).toBe(false);
    expect(hook.result.current.syncProgress.active).toBe(false);
  });

  it("does not auto-sync when the last sync is fresh", async () => {
    vi.useFakeTimers();
    const hook = render();
    await act(async () => {
      hook.result.current.runAutoSyncIfStale(Date.now(), "KEY", 1);
      await vi.advanceTimersByTimeAsync(50);
    });
    expect(mocks.syncJiraProject).not.toHaveBeenCalled();
  });

  it("auto-syncs when the last sync is stale and reloads tasks", async () => {
    vi.useFakeTimers();
    mocks.listTasksByProjectPaginated.mockResolvedValue({
      data: [{ id: 1 }],
      meta: { total: 1 },
    });
    const hook = render();
    await act(async () => {
      hook.result.current.runAutoSyncIfStale(0, "KEY", 1);
      await vi.advanceTimersByTimeAsync(50);
    });
    expect(mocks.syncJiraProject).toHaveBeenCalledWith("KEY", { timeout: 10000 });
    expect(onTasksLoaded).toHaveBeenCalledWith([{ id: 1 }], 1);
    expect(onProjectReload).toHaveBeenCalled();
    expect(showToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: "success", msg: "Auto-sync completed" }),
    );
  });

  it("purge-and-resync polls tasks until data arrives, then reports success", async () => {
    vi.useFakeTimers();
    mocks.listTasksByProjectPaginated.mockResolvedValue({
      data: [{ id: 7 }],
      meta: { total: 7 },
    });
    const hook = render();
    await act(async () => {
      void hook.result.current.handlePurgeAndResync({ id: 1, jira_key: "KEY" });
      await vi.advanceTimersByTimeAsync(2500);
    });
    expect(mocks.purgeProject).toHaveBeenCalledWith(1);
    expect(mocks.syncJiraProject).toHaveBeenCalledWith("KEY");
    expect(onTasksLoaded).toHaveBeenCalledWith([{ id: 7 }], 7);
    expect(showToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: "success", msg: "Resync completed" }),
    );
    expect(hook.result.current.syncing).toBe(false);
  });

  it("purge-and-resync reports an error when the purge fails", async () => {
    vi.useFakeTimers();
    mocks.purgeProject.mockRejectedValue(new Error("nope"));
    const hook = render();
    await act(async () => {
      void hook.result.current.handlePurgeAndResync({ id: 1, jira_key: "KEY" });
      await vi.advanceTimersByTimeAsync(50);
    });
    expect(showToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: "error", msg: expect.stringContaining("Purge/Resync failed") }),
    );
    expect(hook.result.current.syncing).toBe(false);
  });

});

describe("useProjectSync lifecycle", () => {
  const showToast = vi.fn();
  const logNonFatal = vi.fn();
  const onTasksLoaded = vi.fn();
  const onProjectReload = vi.fn().mockResolvedValue(undefined);

  const render = (projectId: string | undefined = "1") =>
    renderHook(
      (props: { projectId: string | undefined }) =>
        useProjectSync({
          projectId: props.projectId,
          jiraKey: "KEY",
          taskPaginationRef: page,
          showToast,
          logNonFatal,
          onTasksLoaded,
          onProjectReload,
        }),
      { initialProps: { projectId } },
    );

  beforeEach(() => {
    vi.resetAllMocks();
    vi.useFakeTimers();
    mocks.getIntegrationsStatus.mockResolvedValue(jiraConfigured);
    mocks.openWebSocket.mockResolvedValue(null);
    mocks.syncJiraProject.mockResolvedValue({});
    onProjectReload.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("auto-sync reaches terminal state and stops the progress ticker", async () => {
    mocks.listTasksByProjectPaginated.mockResolvedValue({
      data: [{ id: 1 }],
      meta: { total: 1 },
    });
    const hook = render();
    await act(async () => {
      hook.result.current.runAutoSyncIfStale(0, "KEY", 1);
      await vi.advanceTimersByTimeAsync(50);
    });
    expect(hook.result.current.syncing).toBe(false);
    expect(hook.result.current.syncProgress).toEqual({
      active: false,
      percent: 100,
      step: "Sync complete",
    });
    // Ticker must be stopped: long after completion the progress stays put.
    const after = hook.result.current.syncProgress;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000);
    });
    expect(hook.result.current.syncProgress).toEqual(after);
    expect(hook.result.current.syncing).toBe(false);
  });

  it("stops timers and sockets on unmount", async () => {
    const close = vi.fn();
    mocks.openWebSocket.mockResolvedValue({ close, onmessage: null, onclose: null });
    const hook = render();
    // let the WS effect connect
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(close).not.toHaveBeenCalled();
    await act(async () => {
      void hook.result.current.handleManualSync();
      await vi.advanceTimersByTimeAsync(0);
    });
    hook.unmount();
    expect(close).toHaveBeenCalledTimes(1);
    const loadedCalls = onTasksLoaded.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000);
    });
    expect(onTasksLoaded.mock.calls.length).toBe(loadedCalls);
  });

  it("reloads data when the WebSocket reports sync completion for this project", async () => {
    let ws: { close: () => void; onmessage: ((ev: { data: string }) => void) | null; onclose: (() => void) | null } | null = null;
    mocks.openWebSocket.mockImplementation(async () => {
      ws = { close: vi.fn(), onmessage: null, onclose: null };
      return ws;
    });
    mocks.listTasksByProjectPaginated.mockResolvedValue({
      data: [{ id: 3 }],
      meta: { total: 3 },
    });
    const hook = render();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const socket = ws as unknown as FakeWs;
    await act(async () => {
      socket.onmessage?.({
        data: JSON.stringify({ type: "jira_sync_complete", project_id: 1 }),
      });
    });
    expect(onTasksLoaded).toHaveBeenCalledWith([{ id: 3 }], 3);
    expect(onProjectReload).toHaveBeenCalled();
    expect(showToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: "success", msg: "Background sync completed" }),
    );
    expect(hook.result.current.syncing).toBe(false);
    // switching projects closes the old socket
    await act(async () => {
      hook.rerender({ projectId: "2" });
      await vi.advanceTimersByTimeAsync(0);
    });
  });

  it("ignores WebSocket events for other projects", async () => {
    let ws: { close: () => void; onmessage: ((ev: { data: string }) => void) | null; onclose: (() => void) | null } | null = null;
    mocks.openWebSocket.mockImplementation(async () => {
      ws = { close: vi.fn(), onmessage: null, onclose: null };
      return ws;
    });
    render();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const socket = ws as unknown as FakeWs;
    await act(async () => {
      socket.onmessage?.({
        data: JSON.stringify({ type: "jira_sync_complete", project_id: 999 }),
      });
    });
    expect(onTasksLoaded).not.toHaveBeenCalled();
    expect(onProjectReload).not.toHaveBeenCalled();
  });

  it("finalizes via the status-poll fallback when the task finishes", async () => {
    const startedAt = new Date().toISOString();
    mocks.syncJiraProject.mockResolvedValue({
      method: "manual",
      sync_task_started_at: startedAt,
    });
    mocks.apiGet
      .mockResolvedValueOnce({
        data: [{ task_type: "jira_sync", status: "running", started_at: startedAt }],
      })
      .mockResolvedValueOnce({
        data: [{ task_type: "jira_sync", status: "succeeded", started_at: startedAt }],
      });
    mocks.listTasksByProjectPaginated.mockResolvedValue({
      data: [{ id: 5 }],
      meta: { total: 5 },
    });
    const hook = render();
    await act(async () => {
      await hook.result.current.handleManualSync();
    });
    // first poll sees running, second sees succeeded and finalizes
    await act(async () => {
      await vi.advanceTimersByTimeAsync(11000);
    });
    expect(mocks.apiGet).toHaveBeenCalledWith(
      "/v1/traceability/sync-tasks",
      expect.objectContaining({ params: { project_id: 1 } }),
    );
    expect(onTasksLoaded).toHaveBeenCalledWith([{ id: 5 }], 5);
    expect(showToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: "success", msg: "Sync completed (status poll fallback)" }),
    );
    expect(hook.result.current.syncing).toBe(false);
  });

  it("purge poll aborts the previous in-flight request before issuing the next", async () => {
    const signals: AbortSignal[] = [];
    let call = 0;
    mocks.listTasksByProjectPaginated.mockImplementation(
      (_pid: number, _q: unknown, opts?: { signal?: AbortSignal }) => {
        if (opts?.signal) signals.push(opts.signal);
        call++;
        return Promise.resolve(
          call === 1
            ? { data: [], meta: { total: 0 } }
            : { data: [{ id: 9 }], meta: { total: 9 } },
        );
      },
    );
    const hook = render();
    await act(async () => {
      void hook.result.current.handlePurgeAndResync({ id: 1, jira_key: "KEY" });
      await vi.advanceTimersByTimeAsync(2100);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(signals.length).toBe(2);
    expect(signals[0].aborted).toBe(true);
    expect(onTasksLoaded).toHaveBeenCalledWith([{ id: 9 }], 9);
  });
});
