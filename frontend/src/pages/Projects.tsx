import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Box,
  Typography,
  Card,
  CardContent,
  Grid,
  Button,
  Chip,
  LinearProgress,
  IconButton,
  Menu,
  MenuItem,
  FormControl,
  InputLabel,
  Select,
  Dialog,
  DialogTitle,
  DialogContent,
  TextField,
  DialogActions,
  Skeleton,
  type ChipProps,
} from "@mui/material";
import {
  Add as AddIcon,
  MoreVert as MoreVertIcon,
  Folder as FolderIcon,
} from "@mui/icons-material";
import { useDispatch, useSelector } from "react-redux";
import type { RootState, AppDispatch } from "../store/store";
import type { SelectChangeEvent } from "@mui/material/Select";
import {
  setProjects as setProjectsAction,
  setLoading as setLoadingAction,
  setError as setErrorAction,
} from "../store/projectSlice";
import {
  getCurrentUser,
  listProjects,
  createProject as apiCreateProject,
  deleteProject as apiDeleteProject,
  updateProject as apiUpdateProject,
  getProjectById,
  syncJiraProject,
  withRetry,
  listJiraProjects,
  type Project,
} from "../services/api";
import CircularProgressWithLabel from "../components/CircularProgressWithLabel";
import { getErrorMessage, isRequestCanceled } from "../utils/errorUtils";

type ProjectStats = Partial<Project> & {
  total_tasks?: number;
  completed_tasks?: number;
  completion_percentage?: number;
  total_estimate_hours?: number;
  total_spent_hours?: number;
};

type NewProject = {
  name: string;
  jira_key: string;
  description: string;
};

const EMPTY_PROJECT: NewProject = {
  name: "",
  jira_key: "",
  description: "",
};

const PROJECTS_TTL_MS = 60_000; // 1 minute cache for projects list

const Projects = () => {
  const navigate = useNavigate();
  const dispatch = useDispatch<AppDispatch>();
  const projectsState = useSelector((s: RootState) => s.project);
  const lastLoadedAt = projectsState.lastLoadedAt;
  const authUser = useSelector((s: RootState) => s.auth.user);
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [openDialog, setOpenDialog] = useState(false);
  const [newProject, setNewProject] = useState<NewProject>(EMPTY_PROJECT);
  const [jiraProjects, setJiraProjects] = useState<
    { key: string; name: string; id: number | string }[]
  >([]);

  const [syncingProjectId, setSyncingProjectId] = useState<number | null>(null);

  const projects = projectsState.projects;
  const [statsMap, setStatsMap] = useState<Record<number, ProjectStats>>({});
  const [progress, setProgress] = useState<{
    loading: boolean;
    percent: number;
    step: string;
  }>({ loading: false, percent: 0, step: "" });
  const abortRef = useRef<AbortController | null>(null);
  const hasLoadedRef = useRef(false);
  const handleNewProjectChange = useCallback(
    <K extends keyof NewProject>(field: K, value: NewProject[K]) => {
      setNewProject((prev) => ({ ...prev, [field]: value }));
    },
    []
  );
  const handleJiraProjectSelect = useCallback(
    (event: SelectChangeEvent<string>) => {
      handleNewProjectChange("jira_key", event.target.value);
    },
    [handleNewProjectChange]
  );

  const loadProjects = useCallback(async (force: boolean = false) => {
    try {
      // Prevent duplicate loads
      if (!force && hasLoadedRef.current && projects.length > 0) {
        return;
      }

      // cancel previous in-flight
      if (abortRef.current) {
        abortRef.current.abort();
      }
      const controller = new AbortController();
      abortRef.current = controller;
      const shouldFetchList =
        force ||
        projects.length === 0 ||
        !lastLoadedAt ||
        Date.now() - lastLoadedAt > PROJECTS_TTL_MS;
      let data: Project[] = projects;
      if (shouldFetchList) {
        dispatch(setLoadingAction(true));
        setProgress({ loading: true, percent: 5, step: "Loading projects..." });
        const response = await withRetry(() => listProjects(), {
          retries: 2,
          baseDelayMs: 400,
        });
        data = response.data;
        hasLoadedRef.current = true;
      }
      dispatch(setProjectsAction(data));
      dispatch(setErrorAction(null));
      // Hide global spinner once list is ready; load details in background
      dispatch(setLoadingAction(false));
      setProgress({ loading: false, percent: 100, step: "Ready" });

      // Fetch details in batches with fail-safe; do not block page
      const BATCH_SIZE = 3;
      const statsMapTemp: Record<number, ProjectStats> = {};

      for (let i = 0; i < data.length; i += BATCH_SIZE) {
        if (controller.signal.aborted) break;

        const batch = data.slice(i, i + BATCH_SIZE);
        const results = await Promise.allSettled(
          batch.map((project: Project) =>
            withRetry(() => getProjectById(project.id, { signal: controller.signal }), {
              retries: 1,
              baseDelayMs: 200,
            }),
          ),
        );

        batch.forEach((project: Project, idx: number) => {
          const result = results[idx];
          statsMapTemp[project.id] = result.status === "fulfilled" ? result.value : {};
        });
        setStatsMap({ ...statsMapTemp });
      }
    } catch (e: unknown) {
      if (isRequestCanceled(e)) return; // ignore aborted requests
      dispatch(setErrorAction(getErrorMessage(e, "Failed to load projects")));
    } finally {
      // already handled above; keep state consistent on unexpected paths
      dispatch(setLoadingAction(false));
      setProgress({ loading: false, percent: 100, step: "Ready" });
    }
  }, [dispatch, lastLoadedAt, projects]);

  useEffect(() => {
    let isMounted = true;

    const load = async () => {
      // Only load if we don't have projects or cache is expired
      const needsLoad =
        projects.length === 0 ||
        !lastLoadedAt ||
        Date.now() - lastLoadedAt > PROJECTS_TTL_MS;

      if (isMounted && needsLoad) {
        await loadProjects().catch((err) =>
          console.error("Failed to load projects on mount:", err),
        );
      } else if (projects.length > 0 && !hasLoadedRef.current) {
        // If we have projects, load stats in batches to avoid overwhelming backend
        const controller = new AbortController();
        abortRef.current = controller;

        try {
          const BATCH_SIZE = 3; // Load 3 projects at a time
          const statsMapTemp: Record<number, ProjectStats> = {};

          for (let i = 0; i < projects.length; i += BATCH_SIZE) {
            if (!isMounted || controller.signal.aborted) break;

            const batch = projects.slice(i, i + BATCH_SIZE);
            const results = await Promise.allSettled(
              batch.map((project: Project) =>
                withRetry(
                  () => getProjectById(project.id, { signal: controller.signal }),
                  { retries: 1, baseDelayMs: 200 },
                ),
              ),
            );

            if (isMounted) {
              batch.forEach((project: Project, idx: number) => {
                const result = results[idx];
                statsMapTemp[project.id] = result.status === "fulfilled" ? result.value : {};
              });
              setStatsMap({ ...statsMapTemp });
            }
          }

          hasLoadedRef.current = true;
        } catch (e: unknown) {
          if (!isRequestCanceled(e)) {
            console.error("Failed to load project stats:", e);
          }
        }
      }
    };

    load();

    return () => {
      isMounted = false;
      // Don't reset hasLoadedRef - we want to keep loaded state
      // hasLoadedRef.current = false;
      // cancel any pending when leaving page
      if (abortRef.current) {
        abortRef.current.abort();
        abortRef.current = null;
      }
    };
  }, [lastLoadedAt, loadProjects, projects]);

  useEffect(() => {
    if (!openDialog) return;
    const ctrl = new AbortController();
    (async () => {
      try {
        const data = await listJiraProjects(undefined, { signal: ctrl.signal });
        setJiraProjects(data.projects || []);
      } catch (e: unknown) {
        if (isRequestCanceled(e)) return;
      }
    })();
    return () => ctrl.abort();
  }, [openDialog]);

  const handleMenuClick = (
    event: React.MouseEvent<HTMLElement>,
    project: Project,
  ) => {
    setAnchorEl(event.currentTarget);
    setSelectedProject(project);
  };

  const handleMenuClose = () => {
    setAnchorEl(null);
    setSelectedProject(null);
  };

  const ensureOwnerId = async (): Promise<number> => {
    if (authUser?.id) return authUser.id;
    const me = await getCurrentUser();
    return me.id;
  };

  const handleCreateProject = async () => {
    try {
      const owner_id = await ensureOwnerId();
      await apiCreateProject({ ...newProject, owner_id });
      setOpenDialog(false);
      setNewProject(EMPTY_PROJECT);
      await loadProjects(true); // force refresh to include the new project
    } catch (e) {
      dispatch(setErrorAction(getErrorMessage(e, "Failed to create project")));
    }
  };

  const handleSyncProject = async () => {
    if (!selectedProject || !selectedProject.jira_key) {
      return;
    }
    const projectToSync = selectedProject;
    try {
      setSyncingProjectId(projectToSync.id ?? null);
      setProgress({
        loading: true,
        percent: 5,
        step: `Syncing ${projectToSync.name || projectToSync.jira_key}...`,
      });
      await syncJiraProject(projectToSync.jira_key, { timeout: 15000 });
      await loadProjects(true);
      dispatch(setErrorAction(null));
    } catch (e: unknown) {
      dispatch(setErrorAction(getErrorMessage(e, "Failed to sync project")));
    } finally {
      setSyncingProjectId(null);
      setProgress({ loading: false, percent: 100, step: "Ready" });
      handleMenuClose();
    }
  };

  const getStatusColor = (status: string): ChipProps["color"] => {
    switch (status) {
      case "active":
        return "success";
      case "planning":
        return "warning";
      case "completed":
        return "info";
      default:
        return "default";
    }
  };

  return (
    <Box>
      <Box
        display="flex"
        justifyContent="space-between"
        alignItems="center"
        mb={3}
      >
        <Typography variant="h4">Projects</Typography>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setOpenDialog(true)}
        >
          New Project
        </Button>
      </Box>

      <Grid container spacing={3}>
        {projectsState.loading && (
          <Grid item xs={12}>
            <Box display="flex" justifyContent="center" my={2}>
              <CircularProgressWithLabel
                value={progress.percent}
                label={progress.step}
              />
            </Box>
          </Grid>
        )}
        {!projectsState.loading && projects.length === 0 && (
          <Grid item xs={12}>
            <Typography variant="body1" color="text.secondary" align="center">
              No projects found. Click &quot;New Project&quot; to create one.
            </Typography>
          </Grid>
        )}
        {projects.map((project) => {
          const details = statsMap[project.id] ?? project;
          const hasTaskStats = typeof details?.total_tasks !== "undefined";
          const hasProgress =
            typeof details?.completion_percentage !== "undefined";
          const hasEstimateStats =
            typeof details?.total_estimate_hours !== "undefined" ||
            typeof details?.total_spent_hours !== "undefined";

          return (
            <Grid item xs={12} sm={6} md={4} key={project.id}>
              <Card
                sx={{
                  height: "100%",
                  cursor: "pointer",
                  "&:hover": { elevation: 4 },
                }}
                onClick={() => navigate(`/projects/${project.id}`)}
              >
                <CardContent>
                  <Box
                    display="flex"
                    justifyContent="space-between"
                    alignItems="flex-start"
                  >
                    <Box display="flex" alignItems="center" mb={2}>
                      <FolderIcon color="primary" sx={{ mr: 1 }} />
                      <Typography variant="h6" component="h2">
                        {project.name}
                      </Typography>
                    </Box>
                    <IconButton
                      size="small"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleMenuClick(e, project);
                      }}
                    >
                      <MoreVertIcon />
                    </IconButton>
                  </Box>

                  <Box mb={2}>
                    <Chip
                      label={project.status}
                      color={getStatusColor(project.status)}
                      size="small"
                    />
                    <Typography
                      variant="body2"
                      color="text.secondary"
                      sx={{ mt: 1 }}
                    >
                      Key: {project.jira_key}
                    </Typography>
                  </Box>

                  <Typography variant="body2" color="text.secondary" mb={2}>
                    {project.description}
                  </Typography>

                  <Box mb={2}>
                    <Box display="flex" justifyContent="space-between" mb={1}>
                      <Typography variant="body2">Progress</Typography>
                      <Typography variant="body2">
                        {hasTaskStats ? (
                          `${details?.completed_tasks ?? 0}/${details?.total_tasks ?? 0} tasks`
                        ) : (
                          <Skeleton width={80} />
                        )}
                      </Typography>
                    </Box>
                    {hasProgress ? (
                      <>
                        <LinearProgress
                          variant="determinate"
                          value={
                            Math.round(
                              Number(details?.completion_percentage ?? 0) * 10,
                            ) / 10
                          }
                          sx={{ height: 8, borderRadius: 4 }}
                        />
                        <Typography
                          variant="body2"
                          color="text.secondary"
                          mt={0.5}
                        >
                          {Number(details?.completion_percentage ?? 0).toFixed(
                            1,
                          )}
                          % Complete
                        </Typography>
                      </>
                    ) : (
                      <>
                        <Skeleton
                          variant="rectangular"
                          height={8}
                          sx={{ borderRadius: 4 }}
                        />
                        <Skeleton width={100} sx={{ mt: 0.5 }} />
                      </>
                    )}
                  </Box>

                  <Box display="flex" justifyContent="space-between">
                    {hasEstimateStats ? (
                      <>
                        <Typography variant="body2" color="text.secondary">
                          Estimate: {details?.total_estimate_hours ?? 0}h
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                          Spent: {details?.total_spent_hours ?? 0}h
                        </Typography>
                      </>
                    ) : (
                      <>
                        <Skeleton width={120} />
                        <Skeleton width={100} />
                      </>
                    )}
                  </Box>
                </CardContent>
              </Card>
            </Grid>
          );
        })}
      </Grid>

      <Menu
        anchorEl={anchorEl}
        open={Boolean(anchorEl)}
        onClose={handleMenuClose}
      >
        <MenuItem onClick={() => navigate(`/projects/${selectedProject?.id}`)}>
          View Details
        </MenuItem>
        <MenuItem
          onClick={() => {
            setOpenDialog(true);
            if (selectedProject)
              setNewProject({
                name: selectedProject.name,
                jira_key: selectedProject.jira_key,
                description: selectedProject.description || "",
              });
          }}
        >
          Edit Project
        </MenuItem>
        <MenuItem
          onClick={() => void handleSyncProject()}
          disabled={
            !selectedProject || syncingProjectId === selectedProject?.id
          }
        >
          {syncingProjectId === selectedProject?.id
            ? "Syncing..."
            : "Sync with Jira"}
        </MenuItem>
        <MenuItem
          onClick={async () => {
            if (selectedProject && confirm("Delete this project?")) {
              await apiDeleteProject(selectedProject.id);
              handleMenuClose();
              await loadProjects(true);
            }
          }}
          sx={{ color: "error.main" }}
        >
          Delete Project
        </MenuItem>
      </Menu>

      {/* Create Project Dialog */}
      <Dialog
        open={openDialog}
        onClose={() => setOpenDialog(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>
          {selectedProject ? "Edit Project" : "Create New Project"}
        </DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            margin="dense"
            label="Project Name"
            fullWidth
            variant="outlined"
            value={newProject.name}
            onChange={(e) => handleNewProjectChange("name", e.target.value)}
            sx={{ mb: 2 }}
          />
          <TextField
            margin="dense"
            label="Jira Key (or pick below)"
            fullWidth
            variant="outlined"
            value={newProject.jira_key}
            onChange={(e) => handleNewProjectChange("jira_key", e.target.value)}
            sx={{ mb: 2 }}
          />
          <FormControl fullWidth size="small" sx={{ mb: 2 }}>
            <InputLabel>Pick Jira Project</InputLabel>
            <Select
              label="Pick Jira Project"
              value={newProject.jira_key}
              onChange={handleJiraProjectSelect}
            >
              {jiraProjects.map((jp) => (
                <MenuItem key={jp.id} value={jp.key}>
                  {jp.key} — {jp.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            margin="dense"
            label="Description"
            fullWidth
            multiline
            rows={3}
            variant="outlined"
            value={newProject.description}
            onChange={(e) => handleNewProjectChange("description", e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpenDialog(false)}>Cancel</Button>
          {selectedProject ? (
            <Button
              onClick={async () => {
                await apiUpdateProject(selectedProject.id, {
                  jira_key: newProject.jira_key,
                  name: newProject.name,
                  description: newProject.description,
                });
                setOpenDialog(false);
                setSelectedProject(null);
                await loadProjects(true);
              }}
              variant="contained"
            >
              Save
            </Button>
          ) : (
            <Button onClick={handleCreateProject} variant="contained">
              Create
            </Button>
          )}
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default Projects;
