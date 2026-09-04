import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Skeleton,
} from "@mui/material";
import { GridColDef, GridPaginationModel } from "@mui/x-data-grid";
import {
  getProjectById,
  listTasksByProjectPaginated,
  getBurndown,
  getRisks,
  getProjectBudgetHours,
  getProjectValueMetrics,
  getTeamMembersActivity,
} from "../services/api";
import type {
  Project,
  TaskItem,
  BurndownResponse,
  RisksResponse,
  TeamMemberActivity,
  BudgetHoursResponse,
  ValueMetricsResponse,
} from "../services/api";
import { Snackbar, Alert, Tooltip } from "@mui/material";
import CircularProgressWithLabel from "../components/CircularProgressWithLabel";
import RepositoryDialog from "./projectDetail/RepositoryDialog";
import { useProjectRepositories } from "./projectDetail/useProjectRepositories";
import { useProjectSync } from "./projectDetail/useProjectSync";
import { useQualityControl } from "./projectDetail/useQualityControl";
import { useSprintInsights } from "./projectDetail/useSprintInsights";
import { isDevelopment } from "../utils/env";
import { getErrorMessage } from "../utils/errorUtils";
import ProjectDetailTabs from "./projectDetail/ProjectDetailTabs";


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

  const handleRetry = async () => {
    setError(null);
    setLoading(true);
    try {
      await loadProjectDetails(true);
      await fetchTasksPage();
    } catch (err) {
      setError(getErrorMessage(err, 'Failed to reload project data'));
    } finally {
      setLoading(false);
    }
  };

  // Tracks the previously-loaded project id so the load effect can tell an actual
  // project switch (clear stale data) from the initial mount (keep cached tasks).
  const prevProjectIdRef = useRef<string | undefined>(undefined);
  // Server-side pagination state for tasks
  const [taskPaginationModel, setTaskPaginationModel] = useState<GridPaginationModel>({ page: 0, pageSize: 25 });
  const [taskRowCount, setTaskRowCount] = useState(0);
  const [risks, setRisks] = useState<RisksResponse | null>(null);
  const [burndown, setBurndown] = useState<BurndownResponse | null>(null);
  const [budgetHours, setBudgetHours] = useState<BudgetHoursResponse | null>(null);
  const [valueMetrics, setValueMetrics] = useState<ValueMetricsResponse | null>(null);
  const [teamMembers, setTeamMembers] = useState<TeamMemberActivity[]>([]);
  // Per-section loading flags so each section renders its own in-place skeleton
  // instead of blocking the whole page behind a single overlay. The slow
  // "sprint analytics" section in particular must not gate unrelated sections.
  const [sectionLoading, setSectionLoading] = useState<{
    metrics: boolean;
    tasks: boolean;
    burndown: boolean;
    team: boolean;
    risks: boolean;
    sprints: boolean;
    sprintInsights: boolean;
  }>({
    metrics: true,
    tasks: true,
    burndown: true,
    team: true,
    risks: true,
    sprints: true,
    sprintInsights: true,
  });
  const showToast = useCallback((t: { open: boolean; type: "success" | "error" | "info" | "warning"; msg: string }) => {
    setToast(t);
  }, []);
  const repo = useProjectRepositories({
    projectId: id,
    showToast,
  });
  const [toast, setToast] = useState<{
    open: boolean;
    type: "success" | "error" | "info" | "warning";
    msg: string;
  }>({ open: false, type: "info", msg: "" });

  // Surface non-fatal failures instead of `void err` (roadmap E3)
  const logNonFatal = useCallback((label: string, err: unknown) => {
    console.warn(`[ProjectDetail] ${label} failed:`, err);
  }, []);
  const quality = useQualityControl({ projectId: id, showToast, logNonFatal });
  const {
    thresholds,
    setThresholds,
    hist,
    qualityLoading,
    bulkProgress,
    loadQualityHistory,
    handleSaveThresholds,
    handleBulkQualityCheck,
    applyThresholds,
  } = quality;
  const sprintInsights = useSprintInsights({
    projectId: id,
    logNonFatal,
    setSectionLoading,
  });
  const {
    boards,
    boardId,
    sprints,
    selectedSprint,
    sprintBurndown,
    sprintQuality,
    sprintCapacity,
    handleBoardChange,
    handleSprintChange,
    loadSprintsSection,
    resetForProjectSwitch,
  } = sprintInsights;
  const [error, setError] = useState<string | null>(null);
  const taskPaginationRef = useRef(taskPaginationModel);
  useEffect(() => {
    taskPaginationRef.current = taskPaginationModel;
  }, [taskPaginationModel]);

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
    applyThresholds(data?.quality_thresholds || {});
  }, [applyThresholds]);

  const loadProjectDetails = useCallback(async (forceRefresh = false) => {
    if (!id || Number.isNaN(Number(id))) {
      return null;
    }
    const data = await getProjectById(Number(id), undefined, { skipCache: forceRefresh });
    applyProjectData(data);
    return data;
  }, [id, applyProjectData]);

  const handleTasksLoaded = useCallback(
    (rows: TaskItem[], total: number) => {
      setRows(rows);
      setTaskRowCount(total);
      lastRowsRef.current = rows;
    },
    [],
  );
  const reloadProjectAfterSync = useCallback(async () => {
    await loadProjectDetails(true);
  }, [loadProjectDetails]);
  const {
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
  } = useProjectSync({
    projectId: id,
    jiraKey: project?.jira_key,
    taskPaginationRef,
    showToast,
    logNonFatal,
    onTasksLoaded: handleTasksLoaded,
    onProjectReload: reloadProjectAfterSync,
  });

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
          // Codex P2 (round 4): a project with no cached tasks must not inherit
          // the previous project's rows/fallback. The cache-restore effect owns
          // rows + lastRowsRef, so clear both here for the no-cache case (the
          // load effect no longer clears them, to preserve a real cache hit).
          setRows([]);
          lastRowsRef.current = [];
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
    void fetchTasksPage();
  }, [fetchTasksPage]);

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
      // Reset per-section skeletons so they reappear when switching projects.
      setSectionLoading({
        metrics: true,
        tasks: true,
        burndown: true,
        team: true,
        risks: true,
        sprints: true,
        sprintInsights: true,
      });
      // Codex P2 (rounds 1+3): clear the previous project's section data on an
      // actual project SWITCH only — not on the initial mount, where doing so
      // would wipe the cached-task restore (lastRowsRef) that backs the
      // empty/failed-Jira fallback below. The skeletons are gated on emptiness,
      // so resetting only the loading flags is not enough to hide stale data.
      const isProjectSwitch =
        prevProjectIdRef.current !== undefined && prevProjectIdRef.current !== id;
      prevProjectIdRef.current = id;
      if (isProjectSwitch) {
        // NB: rows + lastRowsRef are owned by the cache-restore effect (it sets
        // them to the new project's cache or clears them when there is none), so
        // we must NOT clear them here — doing so wiped the new project's cached-
        // task fallback (codex P2, round 4).
        setRisks(null);
        setBurndown(null);
        resetForProjectSwitch();
        setBudgetHours(null);
        setValueMetrics(null);
        setTeamMembers([]);
      }
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
          // Project core data is available: render the page shell, stat cards
          // and tabs immediately. The remaining sections load independently
          // below and each shows its own in-place skeleton until ready, so a
          // slow section (e.g. sprint analytics) never gates the whole screen.
          setLoading(false);
          setProgress({ loading: false, percent: 100, step: "Ready" });

          // Load thresholds and initial history (drives the Quality tab chart).
          void loadQualityHistory();
          // --- Independent section loads (run in parallel) -------------------
          // Each toggles only its own loading flag so sections fill in as soon
          // as their data arrives, rather than waiting on each other.

          const loadTasksSection = (async () => {
            try {
              logDebug("ProjectDetail: Loading tasks for project:", id);
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
            } finally {
              setSectionLoading((s) => ({ ...s, tasks: false }));
            }
          })();

          const loadRisksSection = (async () => {
            try {
              setRisks(await getRisks(Number(id)));
            } catch (err) { logNonFatal('background load', err); }
            finally {
              setSectionLoading((s) => ({ ...s, risks: false }));
            }
          })();

          const loadBurndownSection = (async () => {
            try {
              setBurndown(await getBurndown(Number(id)));
            } catch (err) { logNonFatal('background load', err); }
            finally {
              setSectionLoading((s) => ({ ...s, burndown: false }));
            }
          })();

          // Budget hours, value metrics and ROI all feed the top stat cards.
          const loadMetricsSection = (async () => {
            try {
              const b = await getProjectBudgetHours(Number(id));
              setBudgetHours(b);
            } catch (err) { logNonFatal('background load', err); }
            try {
              const vm = await getProjectValueMetrics(Number(id));
              setValueMetrics(vm);
            } catch (err) { logNonFatal('background load', err); }
            setSectionLoading((s) => ({ ...s, metrics: false }));
          })();

          const loadTeamSection = (async () => {
            try {
              const tm = await getTeamMembersActivity(Number(id));
              setTeamMembers(tm || []);
            } catch (err) { logNonFatal('background load', err); }
            finally {
              setSectionLoading((s) => ({ ...s, team: false }));
            }
          })();

          // Boards -> sprints -> sprint analytics form one dependent chain, but
          // it runs as its own parallel branch so the slow sprint-analytics
          // fetch never blocks the unrelated sections above.
          // Wait for all sections to settle before evaluating auto-sync below,
          // but the UI has already rendered with per-section skeletons.
          await Promise.allSettled([
            loadTasksSection,
            loadRisksSection,
            loadBurndownSection,
            loadMetricsSection,
            loadTeamSection,
            loadSprintsSection(data?.jira_key),
          ]);
          // Auto-sync if last sync older than 12h
          const lastSync = data?.meta?.last_sync_at
            ? new Date(data.meta.last_sync_at).getTime()
            : 0;
          runAutoSyncIfStale(lastSync, data.jira_key, Number(id));
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
      // stop every sync-domain timer owned by useProjectSync (ticker,
      // status poll, auto-sync timeout, purge poll) on unmount/navigation
      stopSyncActivity();
    };
  }, [id, loadProjectDetails, logNonFatal, loadQualityHistory, loadSprintsSection, resetForProjectSwitch, runAutoSyncIfStale, setSyncProgress, setSyncing, stopSyncActivity]);
  const taskColumns: GridColDef<TaskItem>[] = useMemo(() => ([
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
  ]), []);

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
              {sectionLoading.metrics && !budgetHours ? (
                <>
                  <Skeleton variant="text" width="50%" height={36} />
                  <Skeleton variant="text" width="70%" height={20} />
                  <Skeleton variant="rectangular" width="100%" height={4} sx={{ mt: 1, borderRadius: 1 }} />
                </>
              ) : (
                <>
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
                </>
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
              {sectionLoading.metrics && !valueMetrics ? (
                <Skeleton variant="rounded" width={96} height={32} />
              ) : valueMetrics ? (
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
        sectionLoading={sectionLoading}
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
        repoProviders={repo.repoProviders}
        repoLoading={repo.repoLoading}
        repoBindings={repo.repoBindings}
        repoAction={repo.repoAction}
        onOpenRepoDialog={repo.handleOpenRepoDialog}
        onSetPrimaryRepository={repo.handleSetPrimaryRepository}
        onRemoveRepository={repo.handleRemoveRepository}
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


        <RepositoryDialog repo={repo} />
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
              onClick={() => void handlePurgeAndResync(project)}
            >
              Delete and Resync
            </Button>
          </DialogActions>
        </Dialog>
    </Box>
  );
};

export default ProjectDetail;
