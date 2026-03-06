import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Box,
  Typography,
  Grid,
  Card,
  CardContent,
  Chip,
  LinearProgress,
  Button,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Divider,
  Checkbox,
  FormControlLabel,
  Stack,
} from "@mui/material";
import type { SelectChangeEvent } from "@mui/material/Select";
import { GridColDef, GridPaginationModel } from "@mui/x-data-grid";
import {
  api,
  getProjectById,
  listTasksByProjectPaginated,
  syncJiraProject,
  getBurndown,
  getRisks,
  getProjectSprints,
  getSprintBurndown,
  getSprintQuality,
  getBoardsForProject,
  updateProject,
  listPullRequests,
  evaluateQualityGateAndCheck,
  getQualityHistory,
  getIntegrationsStatus,
  clearIntegrationStatusCache,
  getProjectBudgetHours,
  getProjectValueMetrics,
  getSprintCapacity,
  getProjectRepositories,
  bindRepositoryToProject,
  unbindRepositoryFromProject,
  setPrimaryRepository,
  listGitlabProjects,
  purgeProject,
  getTeamMembersActivity,
} from "../services/api";
import type {
  ProjectRepositoryLink,
  RepositoryProvider,
  GitlabProjectSummary,
  Project,
  Sprint,
  TaskItem,
  BurndownResponse,
  RisksResponse,
  SprintQuality,
  SprintCapacity,
  TeamMemberActivity,
  QualityHistoryItem,
  BudgetHoursResponse,
  ValueMetricsResponse,
  Board,
} from "../services/api";
import { Snackbar, Alert, Tooltip } from "@mui/material";
import CircularProgressWithLabel from "../components/CircularProgressWithLabel";
import { isDevelopment } from "../utils/env";
import { getErrorMessage, getErrorCode } from "../utils/errorUtils";
import { normalizeQualityGateProvider } from "../utils/qualityGate";
import { getCanonicalSprintId, selectActiveSprint } from "../utils/sprintNormalization";
import ProjectDetailTabs from "./projectDetail/ProjectDetailTabs";
import {
  getNextSyncProgress,
  getSyncProgressFromTask,
  selectRelevantJiraSyncTask,
  type JiraSyncTaskStatus,
} from "./projectDetail/syncProgress";

const cacheKeyForTasks = (projectId: number) =>
  `project_tasks_cache_${projectId}`;

const formatHours = (value: unknown): string => {
  const num = Number(value);
  if (!Number.isFinite(num)) return "0";
  const rounded = Math.round(num * 10) / 10;
  return Number(rounded.toFixed(1)).toString();
};

const ProjectDetail = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const logDebug = (...args: unknown[]) => {
    if (isDevelopment) {
      console.log(...args);
    }
  };

  const [value, setValue] = React.useState(0);
  const [loading, setLoading] = useState(true);
  const [progress, setProgress] = useState<{
    loading: boolean;
    percent: number;
    step: string;
  }>({ loading: true, percent: 0, step: "Loading project..." });
  const [project, setProject] = useState<Project | null>(null);
  const [rows, setRows] = useState<TaskItem[]>([]);
  const lastRowsRef = useRef<TaskItem[]>([]);
  // Server-side pagination state for tasks
  const [taskPaginationModel, setTaskPaginationModel] = useState<GridPaginationModel>({ page: 0, pageSize: 25 });
  const [taskRowCount, setTaskRowCount] = useState(0);
  const [risks, setRisks] = useState<RisksResponse | null>(null);
  const [burndown, setBurndown] = useState<BurndownResponse | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [sprints, setSprints] = useState<Sprint[]>([]);
  const [selectedSprint, setSelectedSprint] = useState<number | "">("");
  const [sprintBurndown, setSprintBurndown] = useState<BurndownResponse | null>(null);
  const [sprintQuality, setSprintQuality] = useState<SprintQuality | null>(null);
  const [sprintCapacity, setSprintCapacity] = useState<SprintCapacity | null>(null);
  const [budgetHours, setBudgetHours] = useState<BudgetHoursResponse | null>(null);
  const [valueMetrics, setValueMetrics] = useState<ValueMetricsResponse | null>(null);
  const [teamMembers, setTeamMembers] = useState<TeamMemberActivity[]>([]);
  const [toast, setToast] = useState<{
    open: boolean;
    type: "success" | "error" | "info" | "warning";
    msg: string;
  }>({ open: false, type: "info", msg: "" });
  const [error, setError] = useState<string | null>(null);
  const [boards, setBoards] = useState<Board[]>([]);
  const [boardId, setBoardId] = useState<number | "">("");
  const taskPaginationRef = useRef(taskPaginationModel);
  const boardIdRef = useRef(boardId);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [syncProgress, setSyncProgress] = useState<{
    active: boolean;
    percent: number;
    step: string;
  }>({ active: false, percent: 0, step: "" });
  const syncTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const syncStatusPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const syncStatusPollStateRef = useRef<{
    startedAt: number;
    seenRunning: boolean;
    relevantTaskNotBeforeMs: number;
  }>({
    startedAt: 0,
    seenRunning: false,
    relevantTaskNotBeforeMs: 0,
  });
  const purgePollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const purgeReqCtrlRef = useRef<AbortController | null>(null);
  useEffect(() => {
    taskPaginationRef.current = taskPaginationModel;
  }, [taskPaginationModel]);

  useEffect(() => {
    boardIdRef.current = boardId;
  }, [boardId]);
  const [thresholds, setThresholds] = useState<{
    min_line?: number | "";

    min_branch?: number | "";
  }>({});
  const applyProjectData = useCallback((data: Project | null) => {
    if (!data) {
      return;
    }
    setProject({
      ...data,
      completion_percentage: data.completion_percentage ?? 0,
      total_estimate_hours: data.total_estimate_hours ?? 0,
      total_spent_hours: data.total_spent_hours ?? 0,
      completed_tasks: data.completed_tasks ?? 0,
      in_progress_tasks: data.in_progress_tasks ?? 0,
      spent_budget: data.spent_budget ?? 0,
    });
    const qt = data?.quality_thresholds || {};
    setThresholds({
      min_line: typeof qt.min_line === "number" ? qt.min_line : "",
      min_branch: typeof qt.min_branch === "number" ? qt.min_branch : "",
    });
  }, []);

  const loadProjectDetails = useCallback(async (forceRefresh = false) => {
    if (!id || Number.isNaN(Number(id))) {
      return null;
    }
    const data = await getProjectById(Number(id), undefined, { skipCache: forceRefresh });
    applyProjectData(data);
    return data;
  }, [id, applyProjectData]);

  // Load tasks with server-side pagination
  const loadTasksPage = useCallback(async () => {
    if (!id || Number.isNaN(Number(id))) {
      return;
    }
    try {
      const { page, pageSize } = taskPaginationRef.current;
      const response = await listTasksByProjectPaginated(Number(id), {
        skip: page * pageSize,
        limit: pageSize,
      });
      setRows(response.data);
      setTaskRowCount(response.meta.total);
      lastRowsRef.current = response.data;
    } catch (err) {
      console.error('Failed to load tasks page', err);
    }
  }, [id]);

  const [hist, setHist] = useState<QualityHistoryItem[]>([]);
  const [qualityLoading, setQualityLoading] = useState(false);
  const [bulkProgress, setBulkProgress] = useState<{
    active: boolean;
    percent: number;
    step: string;
  }>({ active: false, percent: 0, step: "" });

  const [repoBindings, setRepoBindings] = useState<ProjectRepositoryLink[]>([]);
  const [repoLoading, setRepoLoading] = useState(false);
  const [repoDialogOpen, setRepoDialogOpen] = useState(false);
  const [repoForm, setRepoForm] = useState<{
    repositoryUrl: string;
    provider: RepositoryProvider;
    repoSlug: string;
    isPrimary: boolean;
  }>({
    repositoryUrl: "",
    provider: 'github',
    repoSlug: "",
    isPrimary: true,
  });
  const [gitlabProjects, setGitlabProjects] = useState<GitlabProjectSummary[]>([]);
  const [gitlabLoading, setGitlabLoading] = useState(false);
  const [gitlabError, setGitlabError] = useState<string | null>(null);
  const [gitlabSearch, setGitlabSearch] = useState('');
  const [gitlabGroupPath, setGitlabGroupPath] = useState('');
  const [gitlabPage, setGitlabPage] = useState(1);
  const gitlabHasNextPageRef = useRef(false);
  const [repoProviders, setRepoProviders] = useState<{ github: boolean; gitlab: boolean }>({ github: false, gitlab: false });
  const [repoError, setRepoError] = useState<string | null>(null);
  const [repoSaving, setRepoSaving] = useState(false);
  const [repoAction, setRepoAction] = useState<{ type: "primary" | "remove"; id: number } | null>(null);

  const reloadRepositories = useCallback(
    async (showError = true) => {
      if (!id) return;
      setRepoLoading(true);
      try {
        const updated = await getProjectRepositories(Number(id));
        setRepoBindings(updated);
      } catch (error) {
        if (showError) {
          const message = getErrorMessage(error, "Failed to refresh repositories");
          setToast({ open: true, type: "error", msg: message });
        }
      } finally {
        setRepoLoading(false);
      }
    },
    [id],
  );

  const performGitlabSearch = useCallback(
    async (page: number, options: { append?: boolean } = {}) => {
      if (!repoProviders.gitlab) {
        return;
      }

      const append = options.append ?? false;
      if (!append) {
        setGitlabProjects([]);
      }
      setGitlabLoading(true);
      setGitlabError(null);

      try {
        const response = await listGitlabProjects({
          groupPath: gitlabGroupPath || undefined,
          search: gitlabSearch || undefined,
          page,
          includeSubgroups: true,
        });

        const projects = response.projects ?? [];
        setGitlabProjects(prev => (append ? [...prev, ...projects] : projects));

        const nextRaw = response.pagination?.next_page ?? null;
        const hasNext = Boolean(nextRaw && String(nextRaw).trim() && String(nextRaw) !== '0');
        gitlabHasNextPageRef.current = hasNext;
        setGitlabPage(page);
      } catch (error) {
        setGitlabError(getErrorMessage(error, 'Failed to fetch GitLab projects'));
      } finally {
        setGitlabLoading(false);
      }
    },
    [gitlabGroupPath, gitlabSearch, repoProviders.gitlab],
  );

  useEffect(() => {
    if (!repoDialogOpen) {
      setGitlabProjects([]);
      setGitlabError(null);
      setGitlabLoading(false);
      gitlabHasNextPageRef.current = false;
      return;
    }
    setGitlabPage(1);
    void performGitlabSearch(1);
  }, [performGitlabSearch, repoDialogOpen]);

  useEffect(() => {
    if (!repoDialogOpen || repoForm.provider !== 'gitlab' || !repoProviders.gitlab) {
      return;
    }
    setGitlabPage(1);
    void performGitlabSearch(1);
  }, [performGitlabSearch, repoDialogOpen, repoForm.provider, repoProviders.gitlab]);

  const wsRef = useRef<WebSocket | null>(null);
  const autoSyncTriedRef = useRef<boolean>(false);
  const autoSyncDisabledRef = useRef<boolean>(false);
  const autoSyncTimeoutRef = useRef<number | null>(null);
  const timedOut = (e: unknown) => {
    const msg = getErrorMessage(e, "").toLowerCase();
    return getErrorCode(e) === "ECONNABORTED" || msg.includes("timeout");
  };
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

  const clearSyncStatusPoll = useCallback(() => {
    if (syncStatusPollRef.current) {
      clearInterval(syncStatusPollRef.current);
      syncStatusPollRef.current = null;
    }
    syncStatusPollStateRef.current = { startedAt: 0, seenRunning: false, relevantTaskNotBeforeMs: 0 };
  }, []);

  const startSyncStatusPoll = useCallback(
    (projectId: number, relevantTaskNotBeforeMs?: number) => {
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
          const response = await api.get<JiraSyncTaskStatus[]>("/v1/traceability/sync-tasks", {
            params: { project_id: projectId },
            timeout: 8000,
          });

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
            syncStatusPollStateRef.current.seenRunning || elapsedMs >= 30000;

          if (canFinalize) {
            clearSyncStatusPoll();
            stopSyncProgressTicker();
            setSyncProgress({
              active: false,
              percent: 100,
              step: "Sync complete",
            });
            setSyncing(false);
            await loadTasksPage();
            await loadProjectDetails(true);
            if (latestJiraSyncTask?.status === "failed") {
              setToast({
                open: true,
                type: "error",
                msg: "Sync failed (status poll fallback)",
              });
            } else {
              setToast({
                open: true,
                type: "success",
                msg: "Sync completed (status poll fallback)",
              });
            }
          }
        } catch (err) {
          void err;
        } finally {
          pollInFlight = false;
        }
      }, 5000);
    },
    [clearSyncStatusPoll, loadProjectDetails, loadTasksPage, stopSyncProgressTicker],
  );

  const handleManualSync = async () => {
    if (!project?.jira_key) {
      setToast({
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
          setToast({
            open: true,
            type: "warning",
            msg: "Jira not configured or token missing",
          });
          return;
        }
      } catch (err) { void err; }
      setSyncing(true);
      setSyncProgress({
        active: true,
        percent: 5,
        step: "Syncing with Jira...",
      });
      const syncResponse = await syncJiraProject(project.jira_key, { timeout: 15000 });
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
      setToast({
        open: true,
        type: "info",
        msg: existingRunning
          ? "Jira sync is already running. Data will refresh automatically when complete."
          : "Sync started in background. Data will refresh automatically when complete.",
      });
      if (id && !Number.isNaN(Number(id))) {
        const relevantTaskNotBeforeMs = syncResponse.sync_task_started_at
          ? Date.parse(syncResponse.sync_task_started_at)
          : Date.now();
        startSyncStatusPoll(Number(id), relevantTaskNotBeforeMs);
      }
    } catch (e) {
      clearSyncStatusPoll();
      stopSyncProgressTicker();
      setSyncing(false);
      setSyncProgress({ active: false, percent: 0, step: "" });
      setToast({ open: true, type: "error", msg: getErrorMessage(e, "Sync failed") });
    }
  };

  const handleOpenRepoDialog = () => {
    setRepoDialogOpen(true);
  };

  const handleRepoDialogClose = () => {
    if (repoSaving) return;
    setRepoDialogOpen(false);
    setRepoError(null);
  };

  const handleRetry = async () => {
    setError(null);
    setLoading(true);
    try {
      await loadProjectDetails(true);
      await loadTasksPage();
    } catch (err) {
      setError(getErrorMessage(err, 'Failed to reload project data'));
    } finally {
      setLoading(false);
    }
  };

  const handleRepoSubmit = async () => {
    if (!id) return;
    const url = repoForm.repositoryUrl.trim();
    const slug = repoForm.repoSlug.trim();

    setRepoError(null);

    if (!url && !slug) {
      setRepoError('Provide a repository URL or slug.');
      return;
    }

    const providerConfigured =
      repoForm.provider === 'github' ? repoProviders.github : repoProviders.gitlab;

    if (!url && !providerConfigured) {
      setRepoError(
        `${repoForm.provider === 'gitlab' ? 'GitLab' : 'GitHub'} integration is not configured.`,
      );
      return;
    }

    setRepoSaving(true);
    try {
      await bindRepositoryToProject(Number(id), {
        repositoryUrl: url || undefined,
        repoSlug: url ? undefined : slug || undefined,
        provider: url ? undefined : repoForm.provider,
        isPrimary: repoForm.isPrimary,
      });
      setRepoDialogOpen(false);
      setToast({
        open: true,
        type: 'success',
        msg: 'Repository linked to project.',
      });
      await reloadRepositories();
    } catch (error) {
      setRepoError(getErrorMessage(error, 'Failed to link repository'));
    } finally {
      setRepoSaving(false);
    }
  };

  const handleSetPrimaryRepository = async (binding: ProjectRepositoryLink) => {
    if (!id) return;
    setRepoAction({ type: 'primary', id: binding.repository_id });
    try {
      await setPrimaryRepository(Number(id), binding.repository_id);
      setToast({
        open: true,
        type: 'success',
        msg: 'Primary repository updated.',
      });
      await reloadRepositories();
    } catch (error) {
      setToast({
        open: true,
        type: 'error',
        msg: getErrorMessage(error, 'Failed to update primary repository'),
      });
    } finally {
      setRepoAction(null);
    }
  };

  const handleRemoveRepository = async (binding: ProjectRepositoryLink) => {
    if (!id) return;
    setRepoAction({ type: 'remove', id: binding.repository_id });
    try {
      await unbindRepositoryFromProject(Number(id), binding.repository_id);
      setToast({
        open: true,
        type: 'success',
        msg: 'Repository unlinked from project.',
      });
      await reloadRepositories();
    } catch (error) {
      setToast({
        open: true,
        type: 'error',
        msg: getErrorMessage(error, 'Failed to remove repository'),
      });
    } finally {
      setRepoAction(null);
    }
  };

  const updateTaskRows = useCallback(
    (list: TaskItem[]) => {
      setRows(list);
      lastRowsRef.current = list;
      if (id && !Number.isNaN(Number(id))) {
        try {
          localStorage.setItem(
            cacheKeyForTasks(Number(id)),
            JSON.stringify(list),
          );
        } catch (err) {
          console.warn("Failed to cache project tasks", err);
        }
      }
    },
    [id],
  );

  const handleChange = (event: React.SyntheticEvent, newValue: number) => {
    setValue(newValue);
  };

  const loadSprintInsights = useCallback(async (sprintId: number) => {
    try {
      setSprintBurndown(await getSprintBurndown(sprintId));
    } catch (err) {
      void err;
    }
    try {
      setSprintQuality(await getSprintQuality(sprintId));
    } catch (err) {
      void err;
    }
    try {
      setSprintCapacity(await getSprintCapacity(sprintId));
    } catch (err) {
      void err;
    }
  }, []);

  const handleBoardChange = useCallback(
    async (nextBoardId: number) => {
      if (!id) return;
      setBoardId(nextBoardId);
      try {
        const sp = await getProjectSprints(Number(id), 10, nextBoardId);
        const sprintList = sp.sprints || [];
        setSprints(sprintList);
        const currentSprintStillExists =
          typeof selectedSprint === "number" &&
          sprintList.some((sprint) => getCanonicalSprintId(sprint) === selectedSprint);
        const preferredSprint = currentSprintStillExists
          ? selectedSprint
          : getCanonicalSprintId(selectActiveSprint(sprintList)) ??
            getCanonicalSprintId(sprintList[0]) ??
            "";
        setSelectedSprint(preferredSprint);
        if (typeof preferredSprint === "number") {
          await loadSprintInsights(preferredSprint);
        } else {
          setSprintBurndown(null);
          setSprintQuality(null);
          setSprintCapacity(null);
        }
      } catch (err) {
        void err;
      }
    },
    [id, loadSprintInsights, selectedSprint],
  );

  const handleSprintChange = useCallback(
    async (nextSprintId: number) => {
      setSelectedSprint(nextSprintId);
      await loadSprintInsights(nextSprintId);
    },
    [loadSprintInsights],
  );

  const handleSaveThresholds = useCallback(async () => {
    if (!id) return;
    try {
      setQualityLoading(true);
      await updateProject(Number(id), {
        quality_thresholds: {
          min_line:
            thresholds.min_line === "" ? undefined : thresholds.min_line,
          min_branch:
            thresholds.min_branch === "" ? undefined : thresholds.min_branch,
        },
      });
      setToast({
        open: true,
        type: "success",
        msg: "Thresholds saved",
      });
    } catch (e) {
      setToast({
        open: true,
        type: "error",
        msg: getErrorMessage(e, "Save failed"),
      });
    } finally {
      setQualityLoading(false);
    }
  }, [id, thresholds.min_branch, thresholds.min_line]);

  const handleBulkQualityCheck = useCallback(async () => {
    if (!id) return;
    try {
      setBulkProgress({
        active: true,
        percent: 0,
        step: "Fetching PRs...",
      });
      const prs = await listPullRequests({
        projectId: Number(id),
        limit: 500,
      });
      const list = prs.pull_requests || [];
      for (let i = 0; i < list.length; i++) {
        setBulkProgress({
          active: true,
          percent: Math.round((i / list.length) * 100),
          step: `Checking ${i + 1}/${list.length}`,
        });
        try {
          await evaluateQualityGateAndCheck({
            prNumber: list[i].number,
            projectId: Number(id),
            provider: normalizeQualityGateProvider(list[i].provider),
          });
        } catch (err) {
          void err;
        }
      }
      setBulkProgress({
        active: false,
        percent: 100,
        step: "Done",
      });
      const h = await getQualityHistory({
        projectId: Number(id),
        limit: 20,
      });
      setHist(h.history || []);
    } catch (e) {
      setBulkProgress({ active: false, percent: 0, step: "" });
      setToast({
        open: true,
        type: "error",
        msg: getErrorMessage(e, "Bulk check failed"),
      });
    }
  }, [id]);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const integ = await getIntegrationsStatus();
        if (cancelled) return;
        setRepoProviders({
          github: Boolean(integ?.github?.configured && integ?.github?.has_token),
          gitlab: Boolean(integ?.gitlab?.configured && integ?.gitlab?.has_token),
        });
      } catch (error) {
        if (!cancelled) {
          console.error('[ProjectDetail] Failed to load integration status', error);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;

    const loadRepositories = async () => {
      setRepoLoading(true);
      try {
        const data = await getProjectRepositories(Number(id));
        if (!cancelled) {
          setRepoBindings(data);
        }
      } catch (error) {
        if (!cancelled) {
          setToast({
            open: true,
            type: 'error',
            msg: getErrorMessage(error, 'Failed to load repositories'),
          });
        }
      } finally {
        if (!cancelled) {
          setRepoLoading(false);
        }
      }
    };

    loadRepositories();

    return () => {
      cancelled = true;
    };
  }, [id, updateTaskRows]);

  useEffect(() => {
    if (!repoDialogOpen) return;
    let cancelled = false;

    const refresh = async () => {
      try {
        clearIntegrationStatusCache();
        const integ = await getIntegrationsStatus();
        if (cancelled) return;
        const nextProviders = {
          github: Boolean(integ?.github?.configured && integ?.github?.has_token),
          gitlab: Boolean(integ?.gitlab?.configured && integ?.gitlab?.has_token),
        };
        setRepoProviders(nextProviders);
        const defaultProvider: RepositoryProvider =
          nextProviders.github ? 'github' : nextProviders.gitlab ? 'gitlab' : 'github';
        setRepoForm({
          repositoryUrl: '',
          provider: defaultProvider,
          repoSlug: '',
          isPrimary: repoBindings.length === 0,
        });
        setRepoError(null);
      } catch (error) {
        if (!cancelled) {
          console.error('[ProjectDetail] Failed to refresh integration status', error);
        }
      }
    };

    refresh();

    return () => {
      cancelled = true;
    };
  }, [repoDialogOpen, repoBindings.length]);

  useEffect(() => {
    logDebug("ProjectDetail: Checking cache for id:", id);
    if (id && !Number.isNaN(Number(id))) {
      try {
        const cached = localStorage.getItem(cacheKeyForTasks(Number(id)));
        if (cached) {
          const parsed = JSON.parse(cached);
          logDebug("ProjectDetail: Restored cached tasks:", parsed?.length);
          updateTaskRows(parsed);
          lastRowsRef.current = parsed;
        } else {
          logDebug("ProjectDetail: No cached tasks found");
        }
      } catch (err) {
        console.warn("Failed to restore cached tasks", err);
      }
    }
  }, [id, updateTaskRows]);

  // Reload tasks when pagination changes (not on initial mount, handled by main effect)
  const paginationMountedRef = useRef(false);
  useEffect(() => {
    if (!paginationMountedRef.current) {
      paginationMountedRef.current = true;
      return; // Skip initial load - handled by main effect
    }
    loadTasksPage();
  }, [loadTasksPage]);

  useEffect(() => {
    logDebug(
      "ProjectDetail: Loading data for project id:",
      id,
      "type:",
      typeof id,
    );
    (async () => {
      setError(null);
      setLoading(true);
      try {
        if (id) {
          logDebug("ProjectDetail: Starting to load project details");
          setProgress({
            loading: true,
            percent: 5,
            step: "Loading project...",
          });
          const data = await loadProjectDetails();
          logDebug("ProjectDetail: Project data loaded:", data);
          if (!data) {
            throw new Error('Project not found');
          }
          // Load thresholds and initial history
          try {
            const h = await getQualityHistory({
              projectId: Number(id),
              limit: 20,
            });
            setHist(h.history || []);
          } catch (err) { void err; }
          try {
            logDebug("ProjectDetail: Loading tasks for project:", id);
            setProgress({
              loading: true,
              percent: 20,
              step: "Loading tasks...",
            });
            // Use paginated API for server-side pagination
            const response = await listTasksByProjectPaginated(Number(id), {
              skip: 0,
              limit: 25, // Initial page size
            });
            logDebug("ProjectDetail: Tasks loaded:", response.data?.length, "of", response.meta.total);
            if (response.data.length === 0 && lastRowsRef.current.length > 0) {
              setToast({
                open: true,
                type: "warning",
                msg: "No tasks returned from Jira; keeping cached data.",
              });
            } else {
              setRows(response.data);
              setTaskRowCount(response.meta.total);
              lastRowsRef.current = response.data;
            }
          } catch (e) {
            console.error("ProjectDetail: Failed to load tasks:", e);
          }
          try {
            setProgress({
              loading: true,
              percent: 35,
              step: "Analyzing risks...",
            });
            setRisks(await getRisks(Number(id)));
          } catch (err) { void err; }
          try {
            setProgress({
              loading: true,
              percent: 50,
              step: "Loading burndown...",
            });
            setBurndown(await getBurndown(Number(id)));
          } catch (err) { void err; }
          try {
            setProgress({
              loading: true,
              percent: 70,
              step: "Loading budget hours...",
            });
            const b = await getProjectBudgetHours(Number(id));
            setBudgetHours(b);
          } catch (err) { void err; }
          try {
            setProgress({
              loading: true,
              percent: 72,
              step: "Loading value metrics...",
            });
            const vm = await getProjectValueMetrics(Number(id));
            setValueMetrics(vm);
          } catch (err) { void err; }
          try {
            setProgress({
              loading: true,
              percent: 73,
              step: "Loading team members...",
            });
            const tm = await getTeamMembersActivity(Number(id));
            setTeamMembers(tm || []);
          } catch (err) { void err; }
          try {
            if (data?.jira_key) {
              setProgress({
                loading: true,
                percent: 75,
                step: "Loading boards...",
              });
              const b = await getBoardsForProject(data.jira_key);
              setBoards(b.boards || []);
              if ((b.boards || []).length) {
                const primaryBoard =
                  (b.boards || []).find((board) => board.type === "scrum") || b.boards[0];
                const primaryBoardId = primaryBoard.id;
                setBoardId(primaryBoardId);
                boardIdRef.current = primaryBoardId;
              }
            }
          } catch (err) { void err; }
          try {
            setProgress({
              loading: true,
              percent: 85,
              step: "Loading sprints...",
            });
            const sp = await getProjectSprints(
              Number(id),
              10,
              typeof boardIdRef.current === "number" ? boardIdRef.current : undefined,
            );
            const sprintList = sp.sprints || [];
            setSprints(sprintList);
            const activeSprintId =
              getCanonicalSprintId(selectActiveSprint(sprintList)) ??
              getCanonicalSprintId(sprintList[0]);
            if (typeof activeSprintId === "number") {
              setSelectedSprint(activeSprintId);
              setProgress({
                loading: true,
                percent: 94,
                step: "Loading sprint analytics...",
              });
              await loadSprintInsights(activeSprintId);
            } else {
              setSelectedSprint("");
              setSprintBurndown(null);
              setSprintQuality(null);
              setSprintCapacity(null);
            }
          } catch (e) {
            console.error(e);
          }
          // Auto-sync if last sync older than 12h
          try {
            const lastSync = data?.meta?.last_sync_at
              ? new Date(data.meta.last_sync_at).getTime()
              : 0;
            const twelveHrs = 12 * 3600 * 1000;
            if (
              (!lastSync || Date.now() - lastSync > twelveHrs) &&
              !autoSyncTriedRef.current &&
              !autoSyncDisabledRef.current
            ) {
              autoSyncTriedRef.current = true;

              const runAutoSync = async () => {
                try {
                  const integ = await getIntegrationsStatus();
                  const ok = integ?.jira?.configured && integ?.jira?.has_token;
                  if (!ok) {
                    setToast({
                      open: true,
                      type: "warning",
                      msg: "Auto-sync skipped: Jira not configured or token missing",
                    });
                    return;
                  }

                  setToast({
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
                    await syncJiraProject(data.jira_key, { timeout: 10000 });
                  } catch (e) {
                    if (!timedOut(e)) throw e;
                  }

                  setSyncProgress((p) => ({
                    ...p,
                    step: "Applying updates...",
                  }));
                  // Use paginated API for polling after auto-sync
                  let taskTotal = 0;
                  try {
                    const { page, pageSize } = taskPaginationRef.current;
                    const response = await listTasksByProjectPaginated(Number(id), {
                      skip: page * pageSize,
                      limit: pageSize,
                    });
                    taskTotal = response.meta.total;
                    if (taskTotal > 0) {
                      setRows(response.data);
                      setTaskRowCount(taskTotal);
                      lastRowsRef.current = response.data;
                    }
                  } catch (e) {
                    if (timedOut(e)) {
                      let attempts = 0;
                      const maxAttempts = 30;
                      await new Promise<void>((resolve) => {
                        let pollInFlight = false;
                        let pollReqCtrl: AbortController | null = null;
                        const iv = setInterval(async () => {
                          if (pollInFlight) {
                            return;
                          }
                          pollInFlight = true;
                          attempts++;
                          if (pollReqCtrl) {
                            pollReqCtrl.abort();
                          }
                          pollReqCtrl = new AbortController();
                          try {
                            const { page, pageSize } = taskPaginationRef.current;
                            const response = await listTasksByProjectPaginated(Number(id), {
                              skip: page * pageSize,
                              limit: pageSize,
                            }, {
                              signal: pollReqCtrl.signal,
                              timeout: 8000,
                            });
                            taskTotal = response.meta.total;
                            if (taskTotal > 0) {
                              setRows(response.data);
                              setTaskRowCount(taskTotal);
                              lastRowsRef.current = response.data;
                            }
                          } catch (err) { void err; }
                          finally {
                            pollInFlight = false;
                          }
                          if (taskTotal > 0 || attempts >= maxAttempts) {
                            clearInterval(iv);
                            if (pollReqCtrl) {
                              pollReqCtrl.abort();
                            }
                            resolve();
                          }
                        }, 2000);
                      });
                    } else {
                      throw e;
                    }
                  }

                  if (taskTotal > 0) {
                    await loadProjectDetails(true);
                    setToast({
                      open: true,
                      type: "success",
                      msg: "Auto-sync completed",
                    });
                  } else {
                    setToast({
                      open: true,
                      type: "warning",
                      msg: "Auto-sync returned no tasks; previous data kept.",
                    });
                    autoSyncDisabledRef.current = true;
                  }
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
                  setToast({
                    open: true,
                    type: "error",
                    msg: `Auto-sync failed: ${getErrorMessage(e, "Unknown error")}`,
                  });
                  try {
                    wsRef.current?.close();
                  } catch (err) { void err; }
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
                runAutoSync().catch((err) =>
                  console.error("Auto-sync background error", err),
                );
              }, 0);
            }
          } catch {
            if (syncTimerRef.current) clearInterval(syncTimerRef.current);
            syncTimerRef.current = null;
            setSyncing(false);
            setSyncProgress({ active: false, percent: 0, step: "" });
            try {
              wsRef.current?.close();
            } catch (err) { void err; }
            clearIntegrationStatusCache();
            autoSyncDisabledRef.current = true;
          }
        }
      } catch (e) {
        if (isDevelopment) {
          console.error('[ProjectDetail] Failed to load project', e);
        }
        setError(getErrorMessage(e, 'Failed to load project details'));
        setProject(null);
      } finally {
        setLoading(false);
        setProgress({ loading: false, percent: 100, step: "Ready" });
        setSyncing(false);
        setSyncProgress({ active: false, percent: 0, step: "" });
      }
    })();
    return () => {
      // ensure intervals are cleaned up on unmount/navigation
      if (syncTimerRef.current) clearInterval(syncTimerRef.current);
      syncTimerRef.current = null;
      clearSyncStatusPoll();
      if (autoSyncTimeoutRef.current !== null) {
        clearTimeout(autoSyncTimeoutRef.current);
        autoSyncTimeoutRef.current = null;
      }
      if (purgePollRef.current) clearInterval(purgePollRef.current);
      purgePollRef.current = null;
      if (purgeReqCtrlRef.current) purgeReqCtrlRef.current.abort();
      purgeReqCtrlRef.current = null;
    };
  }, [clearSyncStatusPoll, id, loadProjectDetails, loadSprintInsights, loadTasksPage]);

  // WebSocket: listen for backend sync completion and refresh tasks (only if Jira configured and auto-sync not disabled)
  useEffect(() => {
    let closed = false;
    (async () => {
      try {
        if (autoSyncDisabledRef.current) return; // don't open WS if auto-sync disabled
        const integ = await getIntegrationsStatus();
        const ok = integ?.jira?.configured && integ?.jira?.has_token;
        if (!ok) return; // don't open WS if Jira not configured
        const proto = window.location.protocol === "https:" ? "wss" : "ws";
        const base = window.location.host;
        const ws = new WebSocket(`${proto}://${base}/api/v1/ws`);
        wsRef.current = ws;
        ws.onmessage = async (ev) => {
          try {
            const msg = JSON.parse(ev.data || "{}");
            if (
              msg?.type === "jira_sync_complete" &&
              typeof id === "string" &&
              Number(id) === Number(msg?.project_id)
            ) {
              clearSyncStatusPoll();
              if (syncTimerRef.current) {
                clearInterval(syncTimerRef.current);
                syncTimerRef.current = null;
              }
              setSyncProgress({ active: false, percent: 100, step: "Sync complete" });
              setSyncing(false);
              // Reload current page with paginated API after sync
              await loadTasksPage();
              await loadProjectDetails(true);
              setToast({
                open: true,
                type: "success",
                msg: "Background sync completed",
              });
            } else if (
              msg?.type === "jira_sync_failed" &&
              typeof id === "string" &&
              Number(id) === Number(msg?.project_id)
            ) {
              clearSyncStatusPoll();
              if (syncTimerRef.current) {
                clearInterval(syncTimerRef.current);
                syncTimerRef.current = null;
              }
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
              setToast({
                open: true,
                type: "error",
                msg: detail ? `${message}: ${detail}` : message,
              });
            }
          } catch (err) { void err; }
        };
        ws.onclose = () => {
          if (!closed) wsRef.current = null;
        };
      } catch (err) { void err; }
    })();
    return () => {
      closed = true;
      clearSyncStatusPoll();
      try {
        wsRef.current?.close();
      } catch (err) { void err; }
      wsRef.current = null;
    };
  }, [clearSyncStatusPoll, id, loadProjectDetails, loadTasksPage]);

  const taskColumns: GridColDef<TaskItem>[] = [
    { field: "key", headerName: "Key", width: 120 },
    { field: "summary", headerName: "Summary", width: 300, flex: 1 },
    {
      field: "status",
      headerName: "Status",
      width: 120,
      renderCell: (params) => <Chip label={params.value} size="small" />,
    },
    { field: "assignee_name", headerName: "Assignee", width: 150 },
    { field: "estimate_hours", headerName: "Estimate", width: 100 },
    { field: "spent_hours", headerName: "Spent", width: 100 },
  ];

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" height={360}>
        <CircularProgressWithLabel value={progress.percent} label={progress.step} />
      </Box>
    );
  }

  if (error) {
    return (
      <Box display="flex" flexDirection="column" alignItems="center" justifyContent="center" height={360} gap={2}>
        <Alert severity="error" sx={{ maxWidth: 420, textAlign: 'center' }}>
          {error}
        </Alert>
        <Box display="flex" gap={2}>
          <Button variant="contained" onClick={handleRetry}>
            Retry
          </Button>
          <Button variant="outlined" onClick={() => navigate('/projects')}>
            Back to Projects
          </Button>
        </Box>
      </Box>
    );
  }

  if (!project) {
    return (
      <Box display="flex" flexDirection="column" alignItems="center" justifyContent="center" height={360} gap={2}>
        <Alert severity="warning" sx={{ maxWidth: 420, textAlign: 'center' }}>
          Project data is not available.
        </Alert>
        <Button variant="outlined" onClick={() => navigate('/projects')}>
          Back to Projects
        </Button>
      </Box>
    );
  }

  return (
    <Box>
      {/* Project Header */}
      <Box mb={3}>
        <Typography variant="h4" gutterBottom>
          {project.name}
        </Typography>
        <Typography variant="body1" color="text.secondary" paragraph>
          {project.description}
        </Typography>
        <Box display="flex" gap={2} alignItems="center">
          <Chip label={project.status} color="success" />
          <Typography variant="body2">Key: {project.jira_key}</Typography>
          <Button
            variant="outlined"
            size="small"
            disabled={syncing}
            onClick={() => void handleManualSync()}
          >
            Sync with Jira
          </Button>
          {syncProgress.active && (
            <Box sx={{ ml: 2 }}>
              <CircularProgressWithLabel
                value={syncProgress.percent}
                size={36}
              />
            </Box>
          )}
          {project?.meta?.last_sync_at && (
            <Chip
              label={`Last sync: ${new Date(project.meta.last_sync_at).toLocaleString()}`}
              size="small"
              sx={{ ml: 2 }}
            />
          )}
          <Button
            variant="text"
            color="error"
            size="small"
            sx={{ ml: 2 }}
            disabled={syncing}
            onClick={() => setConfirmOpen(true)}
          >
            Purge + Resync
          </Button>
        </Box>
      </Box>

      {/* Project Stats */}
      <Grid container spacing={3} mb={3}>
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom>
                Completion
              </Typography>
              <Typography variant="h5">
                {Number(project.completion_percentage ?? 0).toFixed(1)}%
              </Typography>
              <LinearProgress
                variant="determinate"
                value={
                  Math.round(Number(project.completion_percentage ?? 0) * 10) /
                  10
                }
                sx={{ mt: 1 }}
              />
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom>
                Tasks
              </Typography>
              <Typography variant="h5">
                {project.completed_tasks ?? 0}/{project.total_tasks ?? 0}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {(project.total_tasks ?? 0) - (project.completed_tasks ?? 0)} remaining
              </Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom>
                Time Spent
              </Typography>
              <Typography variant="h5">{formatHours(project.total_spent_hours)}h</Typography>
              <Typography variant="body2" color="text.secondary">
                of {formatHours(project.total_estimate_hours)}h estimated
              </Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom>
                Budget Hours
              </Typography>
              <Typography variant="h5">
                {budgetHours ? `${formatHours(budgetHours.total_spent_hours)}h` : "—"}
              </Typography>
              <Typography
                variant="body2"
                color={budgetHours?.overrun ? "error" : "text.secondary"}
              >
                {budgetHours
                  ? `of ${formatHours(budgetHours.total_estimate_hours)}h ${budgetHours.overrun ? `(over by ${formatHours(budgetHours.overrun_hours)}h)` : ""}`
                  : "—"}
              </Typography>
              {budgetHours && (
                <Box mt={1}>
                  <LinearProgress
                    variant="determinate"
                    value={Math.min(
                      100,
                      Math.round(
                        (budgetHours.total_spent_hours /
                          Math.max(1, budgetHours.total_estimate_hours)) *
                          100,
                      ),
                    )}
                    color={budgetHours.overrun ? "error" : "primary"}
                  />
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom>
                ROI
              </Typography>
              {valueMetrics ? (
                <Tooltip
                  title={`${valueMetrics.value_delivered} value / ${formatHours(valueMetrics.total_spent_hours)} hours`}
                >
                  <Chip
                    label={`ROI: ${Math.round((valueMetrics.roi || 0) * 1000) / 1000}`}
                    color={valueMetrics.roi > 0 ? "success" : "default"}
                  />
                </Tooltip>
              ) : (
                <Chip label="ROI: 0" />
              )}
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom>
                Budget Used
              </Typography>
              <Typography variant="h5">
                ${(project.spent_budget ?? 0).toLocaleString()}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                of ${(project.budget ?? 0).toLocaleString()} budget
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Tabs */}
      <ProjectDetailTabs
        value={value}
        onChange={handleChange}
        rows={rows}
        taskColumns={taskColumns}
        taskPaginationModel={taskPaginationModel}
        onTaskPaginationModelChange={setTaskPaginationModel}
        taskRowCount={taskRowCount}
        burndown={burndown}
        teamMembers={teamMembers}
        risks={risks}
        boards={boards}
        boardId={boardId}
        sprints={sprints}
        selectedSprint={selectedSprint}
        sprintBurndown={sprintBurndown}
        sprintQuality={sprintQuality}
        sprintCapacity={sprintCapacity}
        onBoardChange={handleBoardChange}
        onSprintChange={handleSprintChange}
        thresholds={thresholds}
        setThresholds={setThresholds}
        qualityLoading={qualityLoading}
        hist={hist}
        bulkProgress={bulkProgress}
        onSaveThresholds={handleSaveThresholds}
        onBulkCheck={handleBulkQualityCheck}
        repoProviders={repoProviders}
        repoLoading={repoLoading}
        repoBindings={repoBindings}
        repoAction={repoAction}
        onOpenRepoDialog={handleOpenRepoDialog}
        onSetPrimaryRepository={handleSetPrimaryRepository}
        onRemoveRepository={handleRemoveRepository}
      />

        {/* Toasts */}
        <Snackbar
          open={toast.open}
          autoHideDuration={3000}
          onClose={() => setToast({ ...toast, open: false })}
          anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
        >
          <Alert severity={toast.type} sx={{ width: "100%" }}>
            {toast.msg}
          </Alert>
        </Snackbar>

        {/* Link Repository Dialog */}
        <Dialog open={repoDialogOpen} onClose={handleRepoDialogClose}>
          <DialogTitle>Link Repository</DialogTitle>
          <DialogContent sx={{ width: 420, maxWidth: '100%' }}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Add a GitHub or GitLab repository to associate pull requests and commits with this project.
            </Typography>
            {!repoProviders.github && !repoProviders.gitlab && (
              <Alert severity="warning" sx={{ mb: 2 }}>
                Configure a GitHub or GitLab integration first to enable API lookups for repositories.
              </Alert>
            )}
            <TextField
              fullWidth
              label="Repository URL"
              placeholder="https://github.com/org/repo"
              value={repoForm.repositoryUrl}
              onChange={(e) =>
                setRepoForm((form) => ({
                  ...form,
                  repositoryUrl: e.target.value,
                }))
              }
              margin="dense"
              disabled={repoSaving}
            />
            <Divider sx={{ my: 2 }}>or</Divider>
            <FormControl fullWidth margin="dense" disabled={repoSaving}>
              <InputLabel id="repo-provider-label">Provider</InputLabel>
              <Select
                labelId="repo-provider-label"
                label="Provider"
                value={repoForm.provider}
                onChange={(e: SelectChangeEvent<RepositoryProvider>) => {
                  const nextProvider = e.target.value;
                  if (nextProvider !== 'github' && nextProvider !== 'gitlab') {
                    return;
                  }
                  setRepoForm((form) => ({
                    ...form,
                    provider: nextProvider,
                  }));
                }}
              >
                <MenuItem value="github" disabled={!repoProviders.github}>GitHub</MenuItem>
                <MenuItem value="gitlab" disabled={!repoProviders.gitlab}>GitLab</MenuItem>
              </Select>
            </FormControl>
            <TextField
              fullWidth
              label="Repository Slug"
              placeholder="org/repo"
              value={repoForm.repoSlug}
              onChange={(e) =>
                setRepoForm((form) => ({
                  ...form,
                  repoSlug: e.target.value,
                }))
              }
              helperText="Used when repository URL is not provided."
              margin="dense"
              disabled={repoSaving}
            />




{repoForm.provider === 'gitlab' && repoProviders.gitlab && (

  <Box sx={{ mt: 2 }}>

    <Divider sx={{ mb: 2 }}>GitLab project browser</Divider>

    <Stack spacing={1}>

      <TextField

        label="Group path"

        placeholder="company/platform"

        value={gitlabGroupPath}

        onChange={(event) => {

          setGitlabGroupPath(event.target.value);

        }}

        size="small"

        disabled={gitlabLoading}

      />

      <TextField

        label="Search"

        placeholder="project name"

        value={gitlabSearch}

        onChange={(event) => {

          setGitlabSearch(event.target.value);

        }}

        size="small"

        disabled={gitlabLoading}

      />

      <Stack direction="row" spacing={1}>

        <Button

          size="small"

          variant="contained"

          onClick={() => void performGitlabSearch(1)}

          disabled={gitlabLoading}

        >

          Search

        </Button>

        <Button

          size="small"

          onClick={() => {

            setGitlabGroupPath('');

            setGitlabSearch('');

            setGitlabProjects([]);

            gitlabHasNextPageRef.current = false;

          }}

          disabled={gitlabLoading}

        >

          Clear

        </Button>

      </Stack>

    </Stack>



    {gitlabError && (

      <Alert severity="error" sx={{ mt: 1 }}>

        {gitlabError}

      </Alert>

    )}



    <Box sx={{ mt: 2, maxHeight: 220, overflowY: 'auto', position: 'relative' }}>

      {gitlabLoading && <LinearProgress sx={{ position: 'sticky', top: 0 }} />}

      <Table size="small">

        <TableHead>

          <TableRow>

            <TableCell>Name</TableCell>

            <TableCell>Slug</TableCell>

            <TableCell align="right">Select</TableCell>

          </TableRow>

        </TableHead>

        <TableBody>

          {gitlabProjects.map((project) => (

            <TableRow key={project.id} hover>

              <TableCell>

                <Typography variant="body2" fontWeight={600}>

                  {project.name}

                </Typography>

                <Typography variant="caption" color="text.secondary">

                  {project.path_with_namespace}

                </Typography>

              </TableCell>

              <TableCell>{project.path_with_namespace}</TableCell>

              <TableCell align="right">

                <Button

                  size="small"

                  onClick={() => {

                    setRepoForm((form) => ({

                      ...form,

                      provider: 'gitlab',

                      repoSlug: project.path_with_namespace || form.repoSlug,

                      repositoryUrl: project.http_url_to_repo || form.repositoryUrl,

                    }));

                  }}

                >

                  Use

                </Button>

              </TableCell>

            </TableRow>

          ))}

          {!gitlabLoading && gitlabProjects.length === 0 && (

            <TableRow>

              <TableCell colSpan={3}>

                <Typography variant="body2" color="text.secondary">

                  No projects found. Adjust filters to try again.

                </Typography>

              </TableCell>

            </TableRow>

          )}

        </TableBody>

      </Table>

      {gitlabHasNextPageRef.current && (

        <Box sx={{ display: 'flex', justifyContent: 'center', py: 1 }}>

          <Button

            size="small"

            onClick={() => performGitlabSearch(gitlabPage + 1, { append: true })}

            disabled={gitlabLoading}

          >

            Load more

          </Button>

        </Box>

      )}

    </Box>

  </Box>

)}

            <FormControlLabel
              control={
                <Checkbox
                  checked={repoForm.isPrimary}
                  onChange={(e) =>
                    setRepoForm((form) => ({
                      ...form,
                      isPrimary: e.target.checked,
                    }))
                  }
                  disabled={repoSaving}
                />
              }
              label="Set as primary repository"
              sx={{ mt: 1 }}
            />
            {repoError && (
              <Alert severity="error" sx={{ mt: 2 }}>
                {repoError}
              </Alert>
            )}
          </DialogContent>
          <DialogActions>
            <Button onClick={handleRepoDialogClose} disabled={repoSaving}>
              Cancel
            </Button>
            <Button
              onClick={handleRepoSubmit}
              variant="contained"
              disabled={
                repoSaving ||
                (!repoForm.repositoryUrl.trim() && !repoForm.repoSlug.trim())
              }
            >
              {repoSaving ? "Linking..." : "Link Repository"}
            </Button>
          </DialogActions>
        </Dialog>

        {/* Confirm Purge Dialog */}
        <Dialog open={confirmOpen} onClose={() => setConfirmOpen(false)}>
          <DialogTitle>Delete local project data?</DialogTitle>
          <DialogContent>
            This will remove all tasks and sprints for this project from local
            DB and reload from Jira.
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setConfirmOpen(false)}>Cancel</Button>
            <Button
              color="error"
              onClick={async () => {
                setConfirmOpen(false);
                try {
                  if (!project?.id) return;
                  setToast({
                    open: true,
                    type: "info",
                    msg: "Purging project data...",
                  });
                  await purgeProject(project.id);
                  setToast({
                    open: true,
                    type: "success",
                    msg: "Purged. Resyncing...",
                  });
                  // Check Jira integration/token before resync
                  try {
                    const integ = await getIntegrationsStatus();
                    if (!(integ?.jira?.configured && integ?.jira?.has_token)) {
                      setToast({
                        open: true,
                        type: "warning",
                        msg: "Resync skipped: Jira not configured or token missing",
                      });
                      return;
                    }
                  } catch (err) { void err; }
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
                    if (purgeReqCtrlRef.current)
                      purgeReqCtrlRef.current.abort();
                    purgeReqCtrlRef.current = new AbortController();
                    try {
                      const response = await listTasksByProjectPaginated(Number(id), {
                        skip: taskPaginationModel.page * taskPaginationModel.pageSize,
                        limit: taskPaginationModel.pageSize,
                      }, {
                        signal: purgeReqCtrlRef.current.signal,
                        timeout: 8000,
                      });
                      taskTotal = response.meta.total;
                      if (taskTotal > 0) {
                        setRows(response.data);
                        setTaskRowCount(taskTotal);
                        lastRowsRef.current = response.data;
                      }
                    } catch (err) { void err; }
                    finally {
                      purgePollInFlight = false;
                    }
                    if (taskTotal > 0 || attempts >= maxAttempts) {
                      if (purgePollRef.current) {
                        clearInterval(purgePollRef.current);
                        purgePollRef.current = null;
                      }
                      if (purgeReqCtrlRef.current) {
                        purgeReqCtrlRef.current.abort();
                        purgeReqCtrlRef.current = null;
                      }
                      setSyncing(false);
                      setToast({
                        open: true,
                        type: taskTotal > 0 ? "success" : "error",
                        msg:
                          taskTotal > 0
                            ? "Resync completed"
                            : "Timeout while waiting for data",
                      });
                    }
                  }, 2000);
                } catch (e) {
                  setSyncing(false);
                  setToast({
                    open: true,
                    type: "error",
                    msg: `Purge/Resync failed: ${getErrorMessage(e, "Unknown error")}`,
                  });
                }
              }}
            >
              Delete and Resync
            </Button>
          </DialogActions>
        </Dialog>
    </Box>
  );
};

export default ProjectDetail;
