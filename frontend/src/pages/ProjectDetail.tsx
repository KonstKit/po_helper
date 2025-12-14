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
  Tab,
  Tabs,
  Paper,
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
import { DataGrid, GridColDef } from "@mui/x-data-grid";
import { Line } from "react-chartjs-2";
import {
  getProjectById,
  listTasksByProject,
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
  getVelocity,
} from "../services/api";
import type {
  ProjectRepositoryLink,
  RepositoryProvider,
  GitlabProjectSummary,
} from "../services/api";
import { CircularProgress, Snackbar, Alert, Tooltip } from "@mui/material";
import CircularProgressWithLabel from "../components/CircularProgressWithLabel";
import { isDevelopment } from "../utils/env";
import GitHubIcon from '@mui/icons-material/GitHub';
import GitlabIcon from '@mui/icons-material/GitHub';

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props;

  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={`project-tabpanel-${index}`}
      aria-labelledby={`project-tab-${index}`}
      {...other}
    >
      {value === index && <Box sx={{ p: 3 }}>{children}</Box>}
    </div>
  );
}

const cacheKeyForTasks = (projectId: number) =>
  `project_tasks_cache_${projectId}`;

const ProjectDetail = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const logDebug = (...args: unknown[]) => {
    if (isDevelopment) {
      // eslint-disable-next-line no-console
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
  const [reloadToken, setReloadToken] = useState(0);
  const [project, setProject] = useState<any | null>(null);
  const [rows, setRows] = useState<any[]>([]);
  const lastRowsRef = useRef<any[]>([]);
  const [risks, setRisks] = useState<any>(null);
  const [burndown, setBurndown] = useState<any>(null);
  const [syncing, setSyncing] = useState(false);
  const [sprints, setSprints] = useState<any[]>([]);
  const [selectedSprint, setSelectedSprint] = useState<number | "">("");
  const [sprintBurndown, setSprintBurndown] = useState<any>(null);
  const [sprintQuality, setSprintQuality] = useState<any>(null);
  const [sprintCapacity, setSprintCapacity] = useState<any>(null);
  const [velocityAvg, setVelocityAvg] = useState<number>(0);
  const [budgetHours, setBudgetHours] = useState<{
    total_estimate_hours: number;
    total_spent_hours: number;
    remaining_hours: number;
    overrun: boolean;
    overrun_hours: number;
    top_overruns: any[];
  } | null>(null);
  const [valueMetrics, setValueMetrics] = useState<{
    value_delivered: number;
    total_spent_hours: number;
    roi: number;
  } | null>(null);
  const [teamMembers, setTeamMembers] = useState<any[]>([]);
  const [toast, setToast] = useState<{
    open: boolean;
    type: "success" | "error" | "info" | "warning";
    msg: string;
  }>({ open: false, type: "info", msg: "" });
  const [error, setError] = useState<string | null>(null);
  const [boards, setBoards] = useState<any[]>([]);
  const [boardId, setBoardId] = useState<number | "">("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [syncProgress, setSyncProgress] = useState<{
    active: boolean;
    percent: number;
    step: string;
  }>({ active: false, percent: 0, step: "" });
  const syncTimerRef = useRef<any>(null);
  const purgePollRef = useRef<any>(null);
  const purgeReqCtrlRef = useRef<AbortController | null>(null);
  const [thresholds, setThresholds] = useState<{
    min_line?: number | "";

    min_branch?: number | "";
  }>({});
  const applyProjectData = useCallback((data: any) => {
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
    const qt = (data as any)?.quality_thresholds || {};
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

  const [hist, setHist] = useState<any[]>([]);
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
    provider: 'github' as RepositoryProvider,
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
      } catch (error: any) {
        if (showError) {
          const message =
            error?.response?.data?.detail ||
            error?.message ||
            "Failed to refresh repositories";
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
      } catch (error: any) {
        const message =
          error?.response?.data?.detail ||
          error?.message ||
          'Failed to fetch GitLab projects';
        setGitlabError(message);
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
  const timedOut = (e: any) => {
    const msg = (e?.message || "").toLowerCase();
    return e?.code === "ECONNABORTED" || msg.includes("timeout");
  };
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
      } catch {}
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
      await syncJiraProject(project.jira_key, { timeout: 15000 });
      const list = await listTasksByProject(Number(id));
      updateTaskRows(list);
      await loadProjectDetails(true);
      setReloadToken((token) => token + 1);
      setSyncProgress({ active: false, percent: 100, step: "Sync complete" });
      setSyncing(false);
      setToast({ open: true, type: "success", msg: "Sync completed" });
    } catch (e: any) {
      setSyncing(false);
      setSyncProgress({ active: false, percent: 0, step: "" });
      const message = e?.response?.data?.detail || e?.message || "Sync failed";
      setToast({ open: true, type: "error", msg: message });
    } finally {
      if (syncTimerRef.current) {
        clearInterval(syncTimerRef.current);
        syncTimerRef.current = null;
      }
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

  const handleRetry = () => {
    setReloadToken((token) => token + 1);
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
    } catch (error: any) {
      const message =
        error?.response?.data?.detail ||
        error?.message ||
        'Failed to link repository';
      setRepoError(message);
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
    } catch (error: any) {
      const message =
        error?.response?.data?.detail ||
        error?.message ||
        'Failed to update primary repository';
      setToast({ open: true, type: 'error', msg: message });
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
    } catch (error: any) {
      const message =
        error?.response?.data?.detail ||
        error?.message ||
        'Failed to remove repository';
      setToast({ open: true, type: 'error', msg: message });
    } finally {
      setRepoAction(null);
    }
  };

  const updateTaskRows = useCallback(
    (list: any[]) => {
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
    [id, reloadToken],
  );

  const handleChange = (event: React.SyntheticEvent, newValue: number) => {
    setValue(newValue);
  };

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
      } catch (error: any) {
        if (!cancelled) {
          const message =
            error?.response?.data?.detail ||
            error?.message ||
            'Failed to load repositories';
          setToast({ open: true, type: 'error', msg: message });
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
  }, [id, reloadToken, loadProjectDetails]);

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
  }, [id, reloadToken, loadProjectDetails]);

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
              project_id: Number(id),
              limit: 20,
            });
            setHist(h.history || []);
          } catch {}
          try {
            logDebug("ProjectDetail: Loading tasks for project:", id);
            setProgress({
              loading: true,
              percent: 20,
              step: "Loading tasks...",
            });
            const list = await listTasksByProject(Number(id));
            logDebug("ProjectDetail: Tasks loaded:", list?.length);
            if (list.length === 0 && lastRowsRef.current.length > 0) {
              setToast({
                open: true,
                type: "warning",
                msg: "No tasks returned from Jira; keeping cached data.",
              });
            } else {
              updateTaskRows(list);
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
          } catch {}
          try {
            setProgress({
              loading: true,
              percent: 50,
              step: "Loading burndown...",
            });
            setBurndown(await getBurndown(Number(id)));
          } catch {}
          try {
            setProgress({
              loading: true,
              percent: 65,
              step: "Calculating velocity...",
            });
            const v = await getVelocity(Number(id));
            setVelocityAvg(v?.average_velocity || 0);
          } catch {}
          try {
            setProgress({
              loading: true,
              percent: 70,
              step: "Loading budget hours...",
            });
            const b = await getProjectBudgetHours(Number(id));
            setBudgetHours(b);
          } catch {}
          try {
            setProgress({
              loading: true,
              percent: 72,
              step: "Loading value metrics...",
            });
            const vm = await getProjectValueMetrics(Number(id));
            setValueMetrics(vm);
          } catch {}
          try {
            setProgress({
              loading: true,
              percent: 73,
              step: "Loading team members...",
            });
            const tm = await getTeamMembersActivity(Number(id));
            setTeamMembers(tm || []);
          } catch {}
          try {
            if (data?.jira_key) {
              setProgress({
                loading: true,
                percent: 75,
                step: "Loading boards...",
              });
              const b = await getBoardsForProject(data.jira_key);
              setBoards(b.boards || []);
              if ((b.boards || []).length) setBoardId(b.boards[0].id);
            }
          } catch {}
          try {
            setProgress({
              loading: true,
              percent: 85,
              step: "Loading sprints...",
            });
            const sp = await getProjectSprints(
              Number(id),
              10,
              typeof boardId === "number" ? boardId : undefined,
            );
            setSprints(sp.sprints || []);
            const active =
              (sp.sprints || []).find((s: any) => s.state === "active") ||
              (sp.sprints || [])[0];
            if (active) {
              setSelectedSprint(active.sprint_id);
              try {
                setProgress({
                  loading: true,
                  percent: 92,
                  step: "Loading sprint burndown...",
                });
                setSprintBurndown(await getSprintBurndown(active.sprint_id));
              } catch {}
              try {
                setProgress({
                  loading: true,
                  percent: 95,
                  step: "Computing sprint quality...",
                });
                setSprintQuality(await getSprintQuality(active.sprint_id));
              } catch {}
              try {
                setProgress({
                  loading: true,
                  percent: 98,
                  step: "Calculating sprint capacity...",
                });
                setSprintCapacity(await getSprintCapacity(active.sprint_id));
              } catch {}
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
                  } catch (e: any) {
                    if (!timedOut(e)) throw e;
                  }

                  setSyncProgress((p) => ({
                    ...p,
                    step: "Applying updates...",
                  }));
                  let list2: any[] = [];
                  try {
                    list2 = await listTasksByProject(Number(id), {
                      timeout: 120000,
                    });
                  } catch (e: any) {
                    if (timedOut(e)) {
                      let attempts = 0;
                      const maxAttempts = 30;
                      await new Promise<void>((resolve) => {
                        const iv = setInterval(async () => {
                          attempts++;
                          try {
                            list2 = await listTasksByProject(Number(id), {
                              timeout: 8000,
                            });
                          } catch {}
                          if (
                            (list2 && list2.length > 0) ||
                            attempts >= maxAttempts
                          ) {
                            clearInterval(iv);
                            resolve();
                          }
                        }, 2000);
                      });
                    } else {
                      throw e;
                    }
                  }

                  if (list2.length > 0) {
                    updateTaskRows(list2);
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
                } catch (e: any) {
                  if (syncTimerRef.current) clearInterval(syncTimerRef.current);
                  syncTimerRef.current = null;
                  setSyncing(false);
                  setSyncProgress({ active: false, percent: 0, step: "" });
                  setToast({
                    open: true,
                    type: "error",
                    msg: `Auto-sync failed: ${e?.response?.data?.detail || e.message}`,
                  });
                  try {
                    wsRef.current?.close();
                  } catch {}
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
          } catch (e: any) {
            if (syncTimerRef.current) clearInterval(syncTimerRef.current);
            syncTimerRef.current = null;
            setSyncing(false);
            setSyncProgress({ active: false, percent: 0, step: "" });
            try {
              wsRef.current?.close();
            } catch {}
            clearIntegrationStatusCache();
            autoSyncDisabledRef.current = true;
          }
        }
      } catch (e: any) {
        if (isDevelopment) {
          console.error('[ProjectDetail] Failed to load project', e);
        }
        const message =
          e?.response?.data?.detail ||
          e?.message ||
          'Failed to load project details';
        setError(message);
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
      if (autoSyncTimeoutRef.current !== null) {
        clearTimeout(autoSyncTimeoutRef.current);
        autoSyncTimeoutRef.current = null;
      }
      if (purgePollRef.current) clearInterval(purgePollRef.current);
      purgePollRef.current = null;
      if (purgeReqCtrlRef.current) purgeReqCtrlRef.current.abort();
      purgeReqCtrlRef.current = null;
    };
  }, [id]);

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
              const list = await listTasksByProject(Number(id), {
                timeout: 120000,
              });
              updateTaskRows(list);
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
          } catch {}
        };
        ws.onclose = () => {
          if (!closed) wsRef.current = null;
        };
      } catch {}
    })();
    return () => {
      closed = true;
      try {
        wsRef.current?.close();
      } catch {}
      wsRef.current = null;
    };
  }, [id]);

  const tasks = [
    {
      id: 1,
      key: "ECOM-123",
      summary: "Implement user authentication",
      status: "In Progress",
      assignee: "John Doe",
      estimate_hours: 16,
      spent_hours: 12,
      priority: "High",
    },
    // ... more tasks
  ];

  const burndownData = {
    labels: ["Week 1", "Week 2", "Week 3", "Week 4", "Week 5", "Week 6"],
    datasets: [
      {
        label: "Remaining Work",
        data: [320, 280, 240, 200, 160, 120],
        borderColor: "rgb(75, 192, 192)",
        backgroundColor: "rgba(75, 192, 192, 0.2)",
      },
    ],
  };

  const taskColumns: GridColDef[] = [
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
                {project.completed_tasks}/{project.total_tasks}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {project.total_tasks - project.completed_tasks} remaining
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
              <Typography variant="h5">{project.total_spent_hours}h</Typography>
              <Typography variant="body2" color="text.secondary">
                of {project.total_estimate_hours}h estimated
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
                {budgetHours ? `${budgetHours.total_spent_hours}h` : "—"}
              </Typography>
              <Typography
                variant="body2"
                color={budgetHours?.overrun ? "error" : "text.secondary"}
              >
                {budgetHours
                  ? `of ${budgetHours.total_estimate_hours}h ${budgetHours.overrun ? `(over by ${budgetHours.overrun_hours}h)` : ""}`
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
                  title={`${valueMetrics.value_delivered} value / ${valueMetrics.total_spent_hours} hours`}
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
      <Paper>
        <Tabs value={value} onChange={handleChange}>
          <Tab label="Tasks" />
          <Tab label="Progress" />
          <Tab label="Team" />
          <Tab label="Risks" />
          <Tab label="Sprints" />
          <Tab label="Quality" />
          <Tab label="Repositories" />
        </Tabs>

        <TabPanel value={value} index={0}>
          <Box height={500}>
            <DataGrid
              rows={rows}
              columns={taskColumns}
              checkboxSelection
              disableRowSelectionOnClick
              initialState={{
                pagination: { paginationModel: { page: 0, pageSize: 25 } },
              }}
              pageSizeOptions={[25, 50, 100]}
            />
          </Box>
        </TabPanel>

        <TabPanel value={value} index={1}>
          <Box height={400}>
            <Typography variant="h6" gutterBottom>
              Project Burndown
            </Typography>
            <Line
              data={{
                labels: (burndown?.ideal_burndown || []).map(
                  (p: any) => `Day ${p.day}`,
                ),
                datasets: [
                  {
                    label: "Ideal",
                    data: (burndown?.ideal_burndown || []).map(
                      (p: any) => p.ideal_remaining,
                    ),
                    borderColor: "rgba(255,99,132,0.8)",
                    backgroundColor: "rgba(255,99,132,0.1)",
                    borderDash: [5, 5],
                  },
                  {
                    label: "Actual",
                    data: (
                      burndown?.actual_burndown ||
                      burndown?.ideal_burndown ||
                      []
                    ).map((p: any) => p.remaining || p.ideal_remaining),
                    borderColor: "rgba(54,162,235,0.8)",
                    backgroundColor: "rgba(54,162,235,0.1)",
                  },
                ],
              }}
              options={{
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: "top" } },
              }}
            />
          </Box>
        </TabPanel>

        <TabPanel value={value} index={2}>
          <Typography variant="h6" gutterBottom>
            Team Members
          </Typography>
          <Grid container spacing={2}>
            {(teamMembers.length > 0 ? teamMembers : Array.from(
              new Map(
                rows
                  .filter((r) => r.assignee_name)
                  .map((r) => [r.assignee_email || r.assignee_name, r]),
              ).values(),
            ).map((r: any) => ({
              name: r.assignee_name,
              email: r.assignee_email,
              active_tasks: rows.filter((x) => x.assignee_name === r.assignee_name).length,
              total_tasks: rows.filter((x) => x.assignee_name === r.assignee_name).length,
              completed_tasks: 0,
              last_activity: null,
              days_since_activity: null,
            }))).map((member: any) => (
              <Grid
                item
                xs={12}
                sm={6}
                md={3}
                key={member.email || member.name}
              >
                <Card>
                  <CardContent>
                    <Typography variant="h6">{member.name}</Typography>
                    <Typography variant="body2" color="text.secondary">
                      {member.active_tasks} active tasks
                    </Typography>
                    {member.last_activity && (
                      <Typography
                        variant="caption"
                        color={
                          member.days_since_activity === null ? "text.disabled" :
                          member.days_since_activity === 0 ? "success.main" :
                          member.days_since_activity <= 3 ? "info.main" :
                          member.days_since_activity <= 7 ? "warning.main" :
                          "error.main"
                        }
                      >
                        Last activity: {
                          member.days_since_activity === 0 ? "today" :
                          member.days_since_activity === 1 ? "yesterday" :
                          `${member.days_since_activity} days ago`
                        }
                      </Typography>
                    )}
                  </CardContent>
                </Card>
              </Grid>
            ))}
          </Grid>
        </TabPanel>

        <TabPanel value={value} index={3}>
          <Typography variant="h6" gutterBottom>
            Risk Assessment
          </Typography>
          <Box>
            {(risks?.risks || []).map((risk: any, index: number) => (
              <Card key={index} sx={{ mb: 2 }}>
                <CardContent>
                  <Box display="flex" alignItems="center" gap={2}>
                    <Chip
                      label={risk.type}
                      color={
                        risk.severity === "high"
                          ? "error"
                          : risk.severity === "medium"
                            ? "warning"
                            : "success"
                      }
                    />
                    <Typography>{risk.message}</Typography>
                  </Box>
                </CardContent>
              </Card>
            ))}
          </Box>
        </TabPanel>

        {/* Sprints Tab */}
        <TabPanel value={value} index={4}>
          <Box mb={2} display="flex" alignItems="center" gap={2}>
            <FormControl size="small" sx={{ minWidth: 220 }}>
              <InputLabel>Board</InputLabel>
              <Select
                label="Board"
                value={boardId}
                onChange={async (e) => {
                  const bid = Number(e.target.value);
                  setBoardId(bid);
                  try {
                    const sp = await getProjectSprints(Number(id), 10, bid);
                    setSprints(sp.sprints || []);
                  } catch {}
                }}
              >
                {boards.map((b: any) => (
                  <MenuItem key={b.id} value={b.id}>
                    {b.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 220 }}>
              <InputLabel>Sprint</InputLabel>
              <Select
                label="Sprint"
                value={selectedSprint}
                onChange={async (e) => {
                  const sid = Number(e.target.value);
                  setSelectedSprint(sid);
                  try {
                    setSprintBurndown(await getSprintBurndown(sid));
                  } catch {}
                  try {
                    setSprintQuality(await getSprintQuality(sid));
                  } catch {}
                  try {
                    setSprintCapacity(await getSprintCapacity(sid));
                  } catch {}
                }}
              >
                {sprints.map((s: any) => (
                  <MenuItem key={s.sprint_id} value={s.sprint_id}>
                    {s.name} ({s.state})
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Box>

          {/* KPI cards */}
          <Grid container spacing={2} mb={2}>
            {(() => {
              const current = sprints.find(
                (s: any) => s.sprint_id === selectedSprint,
              );
              if (!current) return null;

              // Map backend fields to expected frontend fields with safe defaults
              const commitmentHours =
                current.commitment_hours ?? current.commitment ?? 0;
              const completedHours =
                current.completed_hours ?? current.completed ?? 0;
              const scopeAddedHours = current.scope_added_hours ?? 0;
              const predictabilityPct =
                current.predictability_pct ??
                (commitmentHours > 0
                  ? (completedHours / commitmentHours) * 100
                  : 0);
              const carryoverHours = current.carryover_hours ?? 0;

              // Forecast KPI
              let forecastLabel = "N/A";
              try {
                const sd = new Date(current.start_date).getTime();
                const ed = new Date(current.end_date).getTime();
                const now = Date.now();
                const totalDays = Math.max(1, (ed - sd) / (1000 * 3600 * 24));
                const elapsedDays = Math.max(
                  0,
                  Math.min(totalDays, (now - sd) / (1000 * 3600 * 24)),
                );
                const commit = Number(commitmentHours);
                const completed = Number(completedHours);
                const remaining = Math.max(commit - completed, 0);
                const daysLeft = Math.max(0.1, totalDays - elapsedDays);
                const paceNeeded = remaining / daysLeft;
                const paceCurrent =
                  elapsedDays > 0 ? completed / elapsedDays : 0;
                const onTrack =
                  paceCurrent + 0.01 >=
                  (commit / totalDays) * (elapsedDays / totalDays)
                    ? completed / commit >= elapsedDays / totalDays - 0.05
                    : completed / commit >= elapsedDays / totalDays - 0.05;
                forecastLabel = `${onTrack ? "On track" : "At risk"} — need ${Math.round(paceNeeded * 10) / 10}h/day`;
              } catch {}
              const cards = [
                {
                  title: "Commitment",
                  value: `${typeof commitmentHours === "number" ? commitmentHours.toFixed(1) : commitmentHours}h`,
                },
                {
                  title: "Completed",
                  value: `${typeof completedHours === "number" ? completedHours.toFixed(1) : completedHours}h`,
                },
                {
                  title: "Scope Change",
                  value: `${typeof scopeAddedHours === "number" ? scopeAddedHours.toFixed(1) : scopeAddedHours}h`,
                },
                {
                  title: "Predictability",
                  value: `${typeof predictabilityPct === "number" ? predictabilityPct.toFixed(1) : predictabilityPct}%`,
                },
                {
                  title: "Carryover",
                  value: `${typeof carryoverHours === "number" ? carryoverHours.toFixed(1) : carryoverHours}h`,
                },
                { title: "Forecast", value: forecastLabel },
              ];
              return cards.map((c, idx) => (
                <Grid item xs={12} sm={6} md={2.4} key={idx}>
                  <Card>
                    <CardContent>
                      <Typography color="textSecondary" gutterBottom>
                        {c.title}
                      </Typography>
                      <Typography variant="h5">{c.value}</Typography>
                    </CardContent>
                  </Card>
                </Grid>
              ));
            })()}
          </Grid>

          {/* Sprint Burndown */}
          <Paper sx={{ p: 2, mb: 2 }}>
            <Typography variant="h6" gutterBottom>
              Burndown
            </Typography>
            <Box height={300}>
              <Line
                data={{
                  labels: (sprintBurndown?.ideal_burndown || []).map(
                    (p: any) => `Day ${p.day}`,
                  ),
                  datasets: [
                    {
                      label: "Ideal",
                      data: (sprintBurndown?.ideal_burndown || []).map(
                        (p: any) => p.ideal_remaining,
                      ),
                      borderColor: "rgba(255,99,132,0.8)",
                      backgroundColor: "rgba(255,99,132,0.1)",
                      borderDash: [5, 5],
                    },
                    {
                      label: "Actual",
                      data: (
                        sprintBurndown?.actual_burndown ||
                        sprintBurndown?.ideal_burndown ||
                        []
                      ).map((p: any) => p.remaining || p.ideal_remaining),
                      borderColor: "rgba(54,162,235,0.8)",
                      backgroundColor: "rgba(54,162,235,0.1)",
                    },
                  ],
                }}
                options={{
                  responsive: true,
                  maintainAspectRatio: false,
                  plugins: { legend: { position: "top" } },
                }}
              />
            </Box>
          </Paper>

          {/* Sprint Capacity */}
          {sprintCapacity && (
            <Paper sx={{ p: 2, mb: 2 }}>
              <Typography variant="h6" gutterBottom>
                Capacity
              </Typography>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                Weeks: {sprintCapacity.weeks}, Capacity per person:{" "}
                {Math.round(sprintCapacity.capacity_hours_per_person * 10) / 10}
                h
              </Typography>
              <Box sx={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      <th style={{ textAlign: "left", padding: 8 }}>
                        Assignee
                      </th>
                      <th style={{ textAlign: "right", padding: 8 }}>
                        Planned (h)
                      </th>
                      <th style={{ textAlign: "right", padding: 8 }}>
                        Capacity (h)
                      </th>
                      <th style={{ textAlign: "right", padding: 8 }}>
                        Utilization %
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {sprintCapacity.assignees.map((r: any) => (
                      <tr key={r.assignee}>
                        <td style={{ padding: 8 }}>{r.assignee}</td>
                        <td style={{ textAlign: "right", padding: 8 }}>
                          {r.planned_hours}
                        </td>
                        <td style={{ textAlign: "right", padding: 8 }}>
                          {r.capacity_hours}
                        </td>
                        <td
                          style={{
                            textAlign: "right",
                            padding: 8,
                            color:
                              r.utilization_pct > 100
                                ? "#d32f2f"
                                : r.utilization_pct > 85
                                  ? "#ed6c02"
                                  : "inherit",
                          }}
                        >
                          {r.utilization_pct}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Box>
            </Paper>
          )}

          {/* Quality */}
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>
              Quality
            </Typography>
            <Grid container spacing={2}>
              <Grid item xs={12} sm={4}>
                <Card>
                  <CardContent>
                    <Typography color="textSecondary" gutterBottom>
                      DoD
                    </Typography>
                    <Typography variant="h5">
                      {(sprintQuality?.dod_pct ?? 0).toFixed(1)}%
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>
              <Grid item xs={12} sm={4}>
                <Card>
                  <CardContent>
                    <Typography color="textSecondary" gutterBottom>
                      Blockers
                    </Typography>
                    <Typography variant="h5">
                      {sprintQuality?.blockers ?? 0}
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>
              <Grid item xs={12} sm={4}>
                <Card>
                  <CardContent>
                    <Typography color="textSecondary" gutterBottom>
                      Bugs by Priority
                    </Typography>
                    <Typography variant="body2">
                      {sprintQuality?.bugs_by_priority
                        ? Object.entries(sprintQuality.bugs_by_priority)
                            .map(([k, v]) => `${k}: ${v}`)
                            .join(" · ")
                        : "N/A"}
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>
            </Grid>
          </Paper>
        </TabPanel>

        {/* Quality Tab */}
        <TabPanel value={value} index={5}>
          <Paper sx={{ p: 2, mb: 2 }}>
            <Typography variant="h6" gutterBottom>
              Quality Thresholds
            </Typography>
            <Box
              display="flex"
              gap={2}
              alignItems="center"
              flexWrap="wrap"
              mb={1}
            >
              <TextField
                label="Min Line %"
                type="number"
                size="small"
                inputProps={{ step: 0.01, min: 0, max: 1 }}
                value={thresholds.min_line ?? ""}
                onChange={(e) =>
                  setThresholds((t) => ({
                    ...t,
                    min_line:
                      e.target.value === "" ? "" : Number(e.target.value),
                  }))
                }
              />
              <TextField
                label="Min Branch %"
                type="number"
                size="small"
                inputProps={{ step: 0.01, min: 0, max: 1 }}
                value={thresholds.min_branch ?? ""}
                onChange={(e) =>
                  setThresholds((t) => ({
                    ...t,
                    min_branch:
                      e.target.value === "" ? "" : Number(e.target.value),
                  }))
                }
              />
              <Button
                variant="contained"
                size="small"
                disabled={qualityLoading}
                onClick={async () => {
                  try {
                    setQualityLoading(true);
                    await updateProject(Number(id), {
                      quality_thresholds: {
                        min_line:
                          thresholds.min_line === ""
                            ? null
                            : thresholds.min_line,
                        min_branch:
                          thresholds.min_branch === ""
                            ? null
                            : thresholds.min_branch,
                      },
                    } as any);
                    setToast({
                      open: true,
                      type: "success",
                      msg: "Thresholds saved",
                    });
                  } catch (e: any) {
                    setToast({
                      open: true,
                      type: "error",
                      msg: e?.message || "Save failed",
                    });
                  } finally {
                    setQualityLoading(false);
                  }
                }}
              >
                Save
              </Button>
              <Button
                size="small"
                onClick={() =>
                  setThresholds({ min_line: 0.8, min_branch: 0.7 })
                }
              >
                Normal
              </Button>
              <Button
                size="small"
                onClick={() =>
                  setThresholds({ min_line: 0.9, min_branch: 0.8 })
                }
              >
                Strict
              </Button>
              <Button
                size="small"
                onClick={() =>
                  setThresholds({ min_line: 0.7, min_branch: 0.6 })
                }
              >
                Lenient
              </Button>
            </Box>
            {/* History Trend */}
            <Box>
              <Typography variant="subtitle2" gutterBottom>
                Gate History (last 20)
              </Typography>
              <Box height={220}>
                <Line
                  data={{
                    labels: (hist || []).map((h) =>
                      new Date(h.created_at).toLocaleDateString(),
                    ),
                    datasets: [
                      {
                        label: "Pass",
                        data: (hist || []).map((h) => (h.passed ? 1 : 0)),
                        borderColor: "rgba(76,175,80,0.9)",
                        backgroundColor: "rgba(76,175,80,0.2)",
                      },
                    ],
                  }}
                  options={{
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                      y: {
                        min: 0,
                        max: 1,
                        ticks: { callback: (v) => (v ? "PASS" : "FAIL") },
                      },
                    },
                    plugins: { legend: { display: false } },
                  }}
                />
              </Box>
            </Box>
            {/* Quality Score */}
            <Box display="flex" gap={3} alignItems="center" mt={2}>
              <Box>
                <Typography variant="subtitle2">
                  Project Quality Score
                </Typography>
                <Typography variant="h5">
                  {(() => {
                    const n = hist.length;
                    if (!n) return "N/A";
                    const passRatio =
                      hist.reduce((a, h) => a + (h.passed ? 1 : 0), 0) / n;
                    const avgCov =
                      hist
                        .map((h) => h.line_coverage ?? 1)
                        .reduce((a, b) => a + b, 0) / n;
                    const score =
                      Math.round(passRatio * (avgCov || 1) * 1000) / 10;
                    return `${score}`;
                  })()}
                  %
                </Typography>
              </Box>
              <Box>
                <Typography variant="subtitle2">Actions</Typography>
                <Button
                  size="small"
                  variant="outlined"
                  onClick={() => window.open("/quality", "_blank")}
                >
                  Open Quality Page
                </Button>
                <Button
                  size="small"
                  variant="contained"
                  sx={{ ml: 1 }}
                  disabled={bulkProgress.active}
                  onClick={async () => {
                    try {
                      setBulkProgress({
                        active: true,
                        percent: 0,
                        step: "Fetching PRs...",
                      });
                      const prs = await listPullRequests({
                        project_id: Number(id),
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
                            pr_number: list[i].number,
                            project_id: Number(id),
                            provider: (list[i].provider || "github") as any,
                          });
                        } catch {}
                      }
                      setBulkProgress({
                        active: false,
                        percent: 100,
                        step: "Done",
                      });
                      const h = await getQualityHistory({
                        project_id: Number(id),
                        limit: 20,
                      });
                      setHist(h.history || []);
                    } catch (e: any) {
                      setBulkProgress({ active: false, percent: 0, step: "" });
                      setToast({
                        open: true,
                        type: "error",
                        msg: e?.message || "Bulk check failed",
                      });
                    }
                  }}
                >
                  Check All PRs
                </Button>
                {bulkProgress.active && (
                  <Box sx={{ display: "inline-block", ml: 2 }}>
                    <CircularProgressWithLabel
                      value={bulkProgress.percent}
                      label={bulkProgress.step}
                      size={40}
                    />
                  </Box>
                )}
              </Box>
            </Box>
          </Paper>
        </TabPanel>

        <TabPanel value={value} index={6}>
          <Paper sx={{ p: 2, mb: 2 }}>
            <Box
              display="flex"
              justifyContent="space-between"
              alignItems="center"
              flexWrap="wrap"
              gap={1}
            >
              <Typography variant="h6">Repositories</Typography>
              <Button
                variant="contained"
                size="small"
                onClick={handleOpenRepoDialog}
              >
                Link Repository
              </Button>
            </Box>
            <Box mt={2} display="flex" gap={1} flexWrap="wrap">
              <Chip
                size="small"
                label={`GitHub: ${repoProviders.github ? "configured" : "not configured"}`}
                color={repoProviders.github ? "success" : "default"}
              />
              <Chip
                size="small"
                label={`GitLab: ${repoProviders.gitlab ? "configured" : "not configured"}`}
                color={repoProviders.gitlab ? "success" : "default"}
              />
            </Box>
            {!repoProviders.github && !repoProviders.gitlab && (
              <Alert severity="info" sx={{ mt: 2 }}>
                Configure GitHub or GitLab integration in Settings to link repositories.
              </Alert>
            )}
            {repoLoading && <LinearProgress sx={{ mt: 2 }} />}
            <Table size="small" sx={{ mt: 2 }}>
              <TableHead>
                <TableRow>
                  <TableCell>Provider</TableCell>
                  <TableCell>Repository</TableCell>
                  <TableCell>Primary</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {repoBindings.map((binding) => (
                  <TableRow key={binding.id}>
                    <TableCell width={120}>
                      <Chip
                        size="small"
                        color={binding.repository.provider === "gitlab" ? "primary" : "default"}
                        label={binding.repository.provider === "gitlab" ? "GitLab" : "GitHub"}
                      />
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" fontWeight={600}>
                        {binding.repository.repo_slug}
                      </Typography>
                      {binding.repository.default_branch && (
                        <Typography variant="caption" color="text.secondary">
                          Default branch: {binding.repository.default_branch}
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell width={160}>
                      {binding.is_primary ? (
                        <Chip label="Primary" color="success" size="small" />
                      ) : (
                        <Button
                          size="small"
                          onClick={() => handleSetPrimaryRepository(binding)}
                          disabled={repoAction?.type === "primary" && repoAction.id === binding.repository_id}
                        >
                          {repoAction?.type === "primary" && repoAction.id === binding.repository_id
                            ? "Updating..."
                            : "Set Primary"}
                        </Button>
                      )}
                    </TableCell>
                    <TableCell align="right" width={140}>
                      <Button
                        size="small"
                        color="error"
                        onClick={() => handleRemoveRepository(binding)}
                        disabled={repoAction?.type === "remove" && repoAction.id === binding.repository_id}
                      >
                        {repoAction?.type === "remove" && repoAction.id === binding.repository_id
                          ? "Removing..."
                          : "Remove"}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {!repoLoading && repoBindings.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={4}>
                      <Typography variant="body2" color="text.secondary">
                        No repositories linked yet.
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </Paper>
        </TabPanel>

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
                onChange={(e) =>
                  setRepoForm((form) => ({
                    ...form,
                    provider: e.target.value as RepositoryProvider,
                  }))
                }
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
                  } catch {}
                  setSyncing(true);
                  await syncJiraProject(project.jira_key);
                  // Poll tasks until available or timeout
                  let attempts = 0;
                  const maxAttempts = 30; // ~60s if interval 2s
                  if (purgePollRef.current) clearInterval(purgePollRef.current);
                  purgePollRef.current = setInterval(async () => {
                    attempts++;
                    // abort previous in-flight request before issuing a new poll
                    if (purgeReqCtrlRef.current)
                      purgeReqCtrlRef.current.abort();
                    purgeReqCtrlRef.current = new AbortController();
                    const list = await listTasksByProject(Number(id), {
                      signal: purgeReqCtrlRef.current.signal,
                    });
                    if (list.length > 0 || attempts >= maxAttempts) {
                      clearInterval(purgePollRef.current);
                      purgePollRef.current = null;
                      if (purgeReqCtrlRef.current) {
                        purgeReqCtrlRef.current.abort();
                        purgeReqCtrlRef.current = null;
                      }
                      updateTaskRows(list);
                      setSyncing(false);
                      setToast({
                        open: true,
                        type: list.length > 0 ? "success" : "error",
                        msg:
                          list.length > 0
                            ? "Resync completed"
                            : "Timeout while waiting for data",
                      });
                    }
                  }, 2000);
                } catch (e: any) {
                  setSyncing(false);
                  setToast({
                    open: true,
                    type: "error",
                    msg: `Purge/Resync failed: ${e?.response?.data?.detail || e.message}`,
                  });
                }
              }}
            >
              Delete and Resync
            </Button>
          </DialogActions>
        </Dialog>
      </Paper>
    </Box>
  );
};

export default ProjectDetail;

