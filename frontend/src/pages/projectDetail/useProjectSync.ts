import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MutableRefObject,
} from 'react';

import {
  api,
  syncJiraProject,
  purgeProject,
  getIntegrationsStatus,
  listTasksByProjectPaginated,
  clearIntegrationStatusCache,
  openWebSocket,
  type TaskItem,
} from '../../services/api';
import { getErrorMessage, getErrorCode } from '../../utils/errorUtils';
import {
  getNextSyncProgress,
  getSyncProgressFromTask,
  selectRelevantJiraSyncTask,
  type JiraSyncTaskStatus,
} from './syncProgress';

export interface SyncProgressState {
  active: boolean;
  percent: number;
  step: string;
}

export interface ProjectSyncOptions {
  projectId: string | undefined;
  jiraKey: string | undefined;
  taskPaginationRef: MutableRefObject<{ page: number; pageSize: number }>;
  showToast: (toast: {
    open: boolean;
    type: "success" | "error" | "info" | "warning";
    msg: string;
  }) => void;
  logNonFatal: (label: string, err: unknown) => void;
  onTasksLoaded: (rows: TaskItem[], total: number) => void;
  onProjectReload: () => Promise<unknown>;
}

/**
 * Jira-sync domain of the project page (E6 decomposition).
 *
 * Owns manual sync, the stale-data auto-sync, the progress ticker, the
 * sync-status poll fallback, the WebSocket completion listener and the
 * purge-and-resync flow, together with their timers. All timers are
 * cleared on unmount; the page calls stopSyncActivity() when the project
 * id changes so nothing leaks across projects.
 */
export function useProjectSync({
  projectId,
  jiraKey,
  taskPaginationRef,
  showToast,
  logNonFatal,
  onTasksLoaded,
  onProjectReload,
}: ProjectSyncOptions) {
  const [syncing, setSyncing] = useState(false);
  const [syncProgress, setSyncProgress] = useState<SyncProgressState>({
    active: false,
    percent: 0,
    step: "",
  });
  const [confirmOpen, setConfirmOpen] = useState(false);

  const syncTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const syncStatusPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const syncStatusPollStateRef = useRef({
    startedAt: 0,
    seenRunning: false,
    relevantTaskNotBeforeMs: 0,
  });
  const wsRef = useRef<WebSocket | null>(null);
  const autoSyncTriedRef = useRef<boolean>(false);
  const autoSyncDisabledRef = useRef<boolean>(false);
  const autoSyncTimeoutRef = useRef<number | null>(null);
  const purgePollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const purgeReqCtrlRef = useRef<AbortController | null>(null);
  const autoSyncPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const autoSyncReqCtrlRef = useRef<AbortController | null>(null);
  // Bumped whenever sync activity is stopped (project switch / unmount) so
  // an in-flight auto-sync run can detect that it became stale.
  const autoSyncRunTokenRef = useRef(0);

  const timedOut = useCallback((e: unknown) => {
    const msg = getErrorMessage(e, "").toLowerCase();
    return getErrorCode(e) === "ECONNABORTED" || msg.includes("timeout");
  }, []);

  const stopSyncProgressTicker = useCallback(() => {
    if (syncTimerRef.current) {
      clearInterval(syncTimerRef.current);
      syncTimerRef.current = null;
    }
  }, []);

  const startSyncProgressTicker = useCallback(
    (initialPercent = 15, initialStep = "Background sync in progress...") => {
      stopSyncProgressTicker();
      setSyncProgress((current) => ({
        active: true,
        percent: Math.max(current.percent, initialPercent),
        step: initialStep,
      }));
      syncTimerRef.current = setInterval(() => {
        setSyncProgress((current) => ({
          active: true,
          percent: getNextSyncProgress(current.percent),
          step: current.step || initialStep,
        }));
      }, 4000);
    },
    [stopSyncProgressTicker],
  );

  // Load the current tasks page via the paginated API. Mirrors the page
  // loadTasksPage callback so sync completion can refresh the grid.
  const fetchTasksPage = useCallback(async () => {
    if (!projectId || Number.isNaN(Number(projectId))) {
      return;
    }
    try {
      const { page, pageSize } = taskPaginationRef.current;
      const response = await listTasksByProjectPaginated(Number(projectId), {
        skip: page * pageSize,
        limit: pageSize,
      });
      onTasksLoaded(response.data, response.meta.total);
    } catch (err) {
      console.error("Failed to load tasks page", err);
    }
  }, [projectId, taskPaginationRef, onTasksLoaded]);

const clearSyncStatusPoll = useCallback(() => {
  if (syncStatusPollRef.current) {
    clearInterval(syncStatusPollRef.current);
    syncStatusPollRef.current = null;
  }
  syncStatusPollStateRef.current = {
    startedAt: 0,
    seenRunning: false,
    relevantTaskNotBeforeMs: 0,
  };
}, []);

// Clears every timer this hook owns (progress ticker, status poll,
// pending auto-sync timeout, purge poll). The page calls this when the
// project id changes; unmount additionally closes the WebSocket.
const stopSyncActivity = useCallback(() => {
  stopSyncProgressTicker();
  clearSyncStatusPoll();
  if (autoSyncTimeoutRef.current !== null) {
    clearTimeout(autoSyncTimeoutRef.current);
    autoSyncTimeoutRef.current = null;
  }
  if (purgePollRef.current) {
    clearInterval(purgePollRef.current);
    purgePollRef.current = null;
  }
  if (purgeReqCtrlRef.current) {
    purgeReqCtrlRef.current.abort();
    purgeReqCtrlRef.current = null;
  }
if (autoSyncPollRef.current) {
  clearInterval(autoSyncPollRef.current);
  autoSyncPollRef.current = null;
}
if (autoSyncReqCtrlRef.current) {
  autoSyncReqCtrlRef.current.abort();
  autoSyncReqCtrlRef.current = null;
}
// Invalidate any in-flight auto-sync run.
autoSyncRunTokenRef.current += 1;
}, [stopSyncProgressTicker, clearSyncStatusPoll]);

const startSyncStatusPoll = useCallback(
  (pid: number, relevantTaskNotBeforeMs?: number) => {
    clearSyncStatusPoll();
    const pollStartedAt = Date.now();
    syncStatusPollStateRef.current = {
      startedAt: pollStartedAt,
      seenRunning: false,
      relevantTaskNotBeforeMs: relevantTaskNotBeforeMs ?? pollStartedAt,
    };

    let pollInFlight = false;
    syncStatusPollRef.current = setInterval(async () => {
      if (pollInFlight) {
        return;
      }
      pollInFlight = true;
      try {
        const response = await api.get<JiraSyncTaskStatus[]>(
          "/v1/traceability/sync-tasks",
          { params: { project_id: pid }, timeout: 8000 },
        );

        const tasks = Array.isArray(response.data) ? response.data : [];
        const latestJiraSyncTask = selectRelevantJiraSyncTask(
          tasks,
          syncStatusPollStateRef.current.relevantTaskNotBeforeMs,
        );
        const derivedProgress = getSyncProgressFromTask(latestJiraSyncTask);
        if (derivedProgress) {
          setSyncProgress((current) => ({
            active: true,
            percent: Math.max(current.percent, derivedProgress.percent),
            step: derivedProgress.step,
          }));
        }

        const hasRunningJiraSync = latestJiraSyncTask?.status === "running";
        if (hasRunningJiraSync) {
          syncStatusPollStateRef.current.seenRunning = true;
          return;
        }

        const elapsedMs = Date.now() - syncStatusPollStateRef.current.startedAt;
        const canFinalize =
          syncStatusPollStateRef.current.seenRunning || 30000 <= elapsedMs;

        if (canFinalize) {
          clearSyncStatusPoll();
          stopSyncProgressTicker();
          setSyncProgress({
            active: false,
            percent: 100,
            step: "Sync complete",
          });
          setSyncing(false);
          await fetchTasksPage();
          await onProjectReload();
          if (latestJiraSyncTask?.status === "failed") {
            showToast({
              open: true,
              type: "error",
              msg: "Sync failed (status poll fallback)",
            });
          } else {
            showToast({
              open: true,
              type: "success",
              msg: "Sync completed (status poll fallback)",
            });
          }
        }
      } catch (err) {
        logNonFatal("background load", err);
      } finally {
        pollInFlight = false;
      }
    }, 5000);
  },
  [
    clearSyncStatusPoll,
    fetchTasksPage,
    onProjectReload,
    showToast,
    stopSyncProgressTicker,
    logNonFatal,
  ],
);

const handleManualSync = useCallback(async () => {
  if (!jiraKey) {
    showToast({
      open: true,
      type: "warning",
      msg: "Project has no Jira key configured.",
    });
    return;
  }
  try {
    try {
      const integ = await getIntegrationsStatus();
      if (!(integ?.jira?.configured && integ?.jira?.has_token)) {
        showToast({
          open: true,
          type: "warning",
          msg: "Jira not configured or token missing",
        });
        return;
      }
    } catch (err) {
      logNonFatal("background load", err);
    }
    setSyncing(true);
    setSyncProgress({
      active: true,
      percent: 5,
      step: "Syncing with Jira...",
    });
    const syncResponse = await syncJiraProject(jiraKey, { timeout: 15000 });
    const existingRunning = syncResponse.method === "existing_running";
    setSyncProgress((p) => ({
      ...p,
      percent: Math.max(p.percent, 15),
      step: existingRunning
        ? "Sync already running, waiting for completion..."
        : "Background sync in progress...",
    }));
    startSyncProgressTicker(
      15,
      existingRunning
        ? "Sync already running, waiting for completion..."
        : "Background sync in progress...",
    );
    showToast({
      open: true,
      type: "info",
      msg: existingRunning
        ? "Jira sync is already running. Data will refresh automatically when complete."
        : "Sync started in background. Data will refresh automatically when complete.",
    });
    if (projectId && !Number.isNaN(Number(projectId))) {
      const relevantTaskNotBeforeMs = syncResponse.sync_task_started_at
        ? Date.parse(syncResponse.sync_task_started_at)
        : Date.now();
      startSyncStatusPoll(Number(projectId), relevantTaskNotBeforeMs);
    }
  } catch (e) {
    clearSyncStatusPoll();
    stopSyncProgressTicker();
    setSyncing(false);
    setSyncProgress({ active: false, percent: 0, step: "" });
    showToast({ open: true, type: "error", msg: getErrorMessage(e, "Sync failed") });
  }
}, [
  jiraKey,
  projectId,
  showToast,
  logNonFatal,
  startSyncProgressTicker,
  startSyncStatusPoll,
  clearSyncStatusPoll,
  stopSyncProgressTicker,
]);

/**
 * Kicks off a background Jira sync when the last successful sync is
 * older than 12h. Runs the actual work via setTimeout(0) so section
 * rendering is never blocked, and retries the task-page fetch when the
 * paginated request times out (backend still applying sync results).
 */
const runAutoSyncIfStale = useCallback(
  (lastSyncAtMs: number, key: string, pid: number) => {
    const twelveHrs = 12 * 3600 * 1000;
    const stale = !lastSyncAtMs || twelveHrs < Date.now() - lastSyncAtMs;
    if (!stale || autoSyncTriedRef.current || autoSyncDisabledRef.current) {
      return;
    }
    autoSyncTriedRef.current = true;
    const runToken = ++autoSyncRunTokenRef.current;
    const isStaleRun = () => runToken !== autoSyncRunTokenRef.current;

    const runAutoSync = async () => {
      try {
        const integ = await getIntegrationsStatus();
        const ok = integ?.jira?.configured && integ?.jira?.has_token;
        if (!ok) {
          showToast({
            open: true,
            type: "warning",
            msg: "Auto-sync skipped: Jira not configured or token missing",
          });
          return;
        }

        showToast({
          open: true,
          type: "info",
          msg: "Auto-sync started (last sync stale)",
        });
        setSyncing(true);
        setSyncProgress({
          active: true,
          percent: 5,
          step: "Syncing with Jira...",
        });
        if (syncTimerRef.current) clearInterval(syncTimerRef.current);
        syncTimerRef.current = setInterval(() => {
          setSyncProgress((p) => ({
            ...p,
            percent: p.percent < 90 ? p.percent + 2 : 90,
          }));
        }, 300);

        try {
          await syncJiraProject(key, { timeout: 10000 });
        } catch (e) {
          if (!timedOut(e)) throw e;
        }

        if (isStaleRun()) {
          return;
        }
        setSyncProgress((p) => ({
          ...p,
          step: "Applying updates...",
        }));
        // Use paginated API for polling after auto-sync
        let taskTotal = 0;
        try {
          const { page, pageSize } = taskPaginationRef.current;
          const response = await listTasksByProjectPaginated(pid, {
            skip: page * pageSize,
            limit: pageSize,
          });
          taskTotal = response.meta.total;
          if (0 < taskTotal) {
            onTasksLoaded(response.data, taskTotal);
          }
        } catch (e) {
          if (timedOut(e)) {
            let attempts = 0;
            const maxAttempts = 30;
            await new Promise<void>((resolve) => {
              let pollInFlight = false;
              autoSyncPollRef.current = setInterval(async () => {
                  if (isStaleRun()) {
                    // project switched or unmounted while polling
                    if (autoSyncPollRef.current) {
                      clearInterval(autoSyncPollRef.current);
                      autoSyncPollRef.current = null;
                    }
                    resolve();
                    return;
                  }
                if (pollInFlight) {
                  return;
                }
                pollInFlight = true;
                attempts++;
                if (autoSyncReqCtrlRef.current) {
                  autoSyncReqCtrlRef.current.abort();
                }
                autoSyncReqCtrlRef.current = new AbortController();
                try {
                  const { page, pageSize } = taskPaginationRef.current;
                  const response = await listTasksByProjectPaginated(
                    pid,
                    {
                      skip: page * pageSize,
                      limit: pageSize,
                    },
                    {
                      signal: autoSyncReqCtrlRef.current.signal,
                      timeout: 8000,
                    },
                  );
                  taskTotal = response.meta.total;
                  if (0 < taskTotal && !isStaleRun()) {
                    onTasksLoaded(response.data, taskTotal);
                  }
                } catch (err) {
                  logNonFatal("background load", err);
                } finally {
                  pollInFlight = false;
                }
                if (0 < taskTotal || maxAttempts <= attempts) {
                  if (autoSyncPollRef.current) {
                    clearInterval(autoSyncPollRef.current);
                    autoSyncPollRef.current = null;
                  }
                  if (autoSyncReqCtrlRef.current) {
                    autoSyncReqCtrlRef.current.abort();
                    autoSyncReqCtrlRef.current = null;
                  }
                  resolve();
                }
              }, 2000);
            });
          } else {
            throw e;
          }
        }

        if (isStaleRun()) {
          return;
        }
        if (0 < taskTotal) {
          await onProjectReload();
          showToast({
            open: true,
            type: "success",
            msg: "Auto-sync completed",
          });
        } else {
          showToast({
            open: true,
            type: "warning",
            msg: "Auto-sync returned no tasks; previous data kept.",
          });
          autoSyncDisabledRef.current = true;
        }
        // Terminal cleanup for both outcomes (pre-refactor behavior):
        // without the WebSocket completion event the ticker would run
        // forever and keep the sync controls disabled.
        if (syncTimerRef.current) clearInterval(syncTimerRef.current);
        syncTimerRef.current = null;
        setSyncProgress({
          active: false,
          percent: 100,
          step: "Sync complete",
        });
        setSyncing(false);
      } catch (e) {
        if (syncTimerRef.current) clearInterval(syncTimerRef.current);
        syncTimerRef.current = null;
        setSyncing(false);
        setSyncProgress({ active: false, percent: 0, step: "" });
        showToast({
          open: true,
          type: "error",
          msg: "Auto-sync failed: " + getErrorMessage(e, "Unknown error"),
        });
        try {
          wsRef.current?.close();
        } catch (err) {
          logNonFatal("background load", err);
        }
        clearIntegrationStatusCache();
        autoSyncDisabledRef.current = true;
      } finally {
        if (autoSyncTimeoutRef.current !== null) {
          autoSyncTimeoutRef.current = null;
        }
      }
    };

    if (autoSyncTimeoutRef.current !== null) {
      clearTimeout(autoSyncTimeoutRef.current);
    }
    autoSyncTimeoutRef.current = window.setTimeout(() => {
      runAutoSync().catch((err) => {
        console.error("Auto-sync background error", err);
      });
    }, 0);
  },
  [showToast, logNonFatal, onTasksLoaded, onProjectReload, taskPaginationRef, timedOut],
);

  /** Purge local project data and resync it from Jira (confirm dialog). */
  const handlePurgeAndResync = useCallback(
    async (project: { id: number; jira_key: string }) => {
      setConfirmOpen(false);
      try {
        showToast({
          open: true,
          type: "info",
          msg: "Purging project data...",
        });
        await purgeProject(project.id);
        showToast({
          open: true,
          type: "success",
          msg: "Purged. Resyncing...",
        });
        // Check Jira integration/token before resync
        try {
          const integ = await getIntegrationsStatus();
          if (!(integ?.jira?.configured && integ?.jira?.has_token)) {
            showToast({
              open: true,
              type: "warning",
              msg: "Resync skipped: Jira not configured or token missing",
            });
            return;
          }
        } catch (err) {
          logNonFatal("background load", err);
        }
        setSyncing(true);
        await syncJiraProject(project.jira_key);
        // Poll tasks until available or timeout - use paginated API
        let attempts = 0;
        let taskTotal = 0;
        const maxAttempts = 30; // ~60s if interval 2s
        let purgePollInFlight = false;
        if (purgePollRef.current) clearInterval(purgePollRef.current);
        purgePollRef.current = setInterval(async () => {
          if (purgePollInFlight) {
            return;
          }
          purgePollInFlight = true;
          attempts++;
          // abort previous in-flight request before issuing a new poll
          if (purgeReqCtrlRef.current) purgeReqCtrlRef.current.abort();
          purgeReqCtrlRef.current = new AbortController();
          try {
            const { page, pageSize } = taskPaginationRef.current;
            const response = await listTasksByProjectPaginated(
              project.id,
              {
                skip: page * pageSize,
                limit: pageSize,
              },
              {
                signal: purgeReqCtrlRef.current.signal,
                timeout: 8000,
              },
            );
            taskTotal = response.meta.total;
            if (0 < taskTotal) {
              onTasksLoaded(response.data, taskTotal);
            }
          } catch (err) {
            logNonFatal("background load", err);
          } finally {
            purgePollInFlight = false;
          }
          if (0 < taskTotal || maxAttempts <= attempts) {
            if (purgePollRef.current) {
              clearInterval(purgePollRef.current);
              purgePollRef.current = null;
            }
            if (purgeReqCtrlRef.current) {
              purgeReqCtrlRef.current.abort();
              purgeReqCtrlRef.current = null;
            }
            setSyncing(false);
            showToast({
              open: true,
              type: 0 < taskTotal ? "success" : "error",
              msg:
                0 < taskTotal
                  ? "Resync completed"
                  : "Timeout while waiting for data",
            });
          }
        }, 2000);
      } catch (e) {
        setSyncing(false);
        showToast({
          open: true,
          type: "error",
          msg: "Purge/Resync failed: " + getErrorMessage(e, "Unknown error"),
        });
      }
    },
    [showToast, logNonFatal, onTasksLoaded, taskPaginationRef],
  );

  // WebSocket: listen for backend sync completion and refresh tasks (only
  // if Jira is configured and auto-sync is not disabled).
  useEffect(() => {
    let closed = false;
    (async () => {
      try {
        if (autoSyncDisabledRef.current) return; // no WS when auto-sync disabled
        const integ = await getIntegrationsStatus();
        const ok = integ?.jira?.configured && integ?.jira?.has_token;
        if (!ok) return; // no WS when Jira is not configured
        const ws = await openWebSocket();
        if (!ws) return; // no session or ticket issue - do not open a socket
        if (closed) {
          // effect cleanup ran while the ticket was being fetched - do not
          // leak the socket
          try {
            ws.close();
          } catch {
            /* already closed */
          }
          return;
        }
        wsRef.current = ws;
        ws.onmessage = async (ev) => {
          try {
            const msg = JSON.parse(ev.data || "{}");
            const isForThisProject =
              typeof projectId === "string" &&
              Number(projectId) === Number(msg?.project_id);
            if (msg?.type === "jira_sync_complete" && isForThisProject) {
              clearSyncStatusPoll();
              stopSyncProgressTicker();
              setSyncProgress({ active: false, percent: 100, step: "Sync complete" });
              setSyncing(false);
              // Reload current page with paginated API after sync
              await fetchTasksPage();
              await onProjectReload();
              showToast({
                open: true,
                type: "success",
                msg: "Background sync completed",
              });
            } else if (msg?.type === "jira_sync_failed" && isForThisProject) {
              clearSyncStatusPoll();
              stopSyncProgressTicker();
              setSyncing(false);
              setSyncProgress({ active: false, percent: 0, step: "" });
              autoSyncDisabledRef.current = true;
              const detail = typeof msg?.detail === "string" ? msg.detail : "";
              let message = "Jira sync failed";
              if (msg?.reason === "auth") {
                message = "Jira sync failed: access denied";
              } else if (msg?.reason === "unexpected") {
                message = "Jira sync failed: unexpected Jira response";
              } else if (msg?.reason === "empty") {
                message = "Jira sync failed: no issues returned";
              }
              showToast({
                open: true,
                type: "error",
                msg: detail ? message + ": " + detail : message,
              });
            }
          } catch (err) {
            logNonFatal("background load", err);
          }
        };
        ws.onclose = () => {
          if (!closed) wsRef.current = null;
        };
      } catch (err) {
        logNonFatal("background load", err);
      }
    })();
    return () => {
      closed = true;
      clearSyncStatusPoll();
      try {
        wsRef.current?.close();
      } catch (err) {
        logNonFatal("background load", err);
      }
      wsRef.current = null;
    };
  }, [clearSyncStatusPoll, projectId, fetchTasksPage, onProjectReload, logNonFatal]);

  // Safety net for unmount: the page stops sync activity on project
  // switch, but the hook also cleans up after itself so nothing leaks when
  // it is used outside the page (tests, future call sites).
  useEffect(
    () => () => {
      stopSyncActivity();
      try {
        wsRef.current?.close();
      } catch {
        /* already closed */
      }
      wsRef.current = null;
    },
    [stopSyncActivity],
  );

  return {
    syncing,
    setSyncing,
    syncProgress,
    setSyncProgress,
    confirmOpen,
    setConfirmOpen,
    handleManualSync,
    handlePurgeAndResync,
    runAutoSyncIfStale,
    fetchTasksPage,
    stopSyncActivity,
    autoSyncDisabledRef,
  };
}
