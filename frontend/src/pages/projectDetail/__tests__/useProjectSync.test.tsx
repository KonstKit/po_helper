
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
    vi.clearAllMocks();
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
