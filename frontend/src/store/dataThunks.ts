import { createAsyncThunk } from '@reduxjs/toolkit';
import { listProjects, listSprints, listTasks, listTasksPaginated } from '../services/api';
import { setProjects, setLoading, setError, setCurrentProject } from './projectSlice';
import { setTasks, setTasksLoading, setTasksError, type Task } from './taskSlice';
import { setSprints, setSprintsLoading, setSprintsError, setActiveSprintByProject } from './sprintSlice';
import { AppDispatch, RootState } from './store';
import { getErrorMessage } from '../utils/errorUtils';
import {
  TASK_SCOPE_DEFAULTS,
  type TaskScope,
} from '../pages/dashboard/dashboardContract';

const CACHE_TTL = 60000; // 1 minute cache

// Track active project loading to prevent duplicates
let projectsLoadingPromise: Promise<void> | null = null;

const loadProjectTasksWithScope = async (
  projectId: number
): Promise<{ tasks: Task[]; taskScope: TaskScope }> => {
  const tasks: Task[] = [];
  let total: number | undefined;
  let skip = 0;
  let pagesFetched = 0;
  let hasNext = false;
  let capHit = false;

  while (pagesFetched < TASK_SCOPE_DEFAULTS.maxPages && tasks.length < TASK_SCOPE_DEFAULTS.maxTasks) {
    const response = await listTasksPaginated(
      { projectId, skip, limit: TASK_SCOPE_DEFAULTS.pageSize },
      { timeout: 30000 }
    );
    const pageTasks = response.data as Task[];
    total = response.meta.total;
    hasNext = response.meta.has_next;
    pagesFetched += 1;

    if (pageTasks.length === 0) {
      hasNext = false;
      break;
    }

    const remaining = TASK_SCOPE_DEFAULTS.maxTasks - tasks.length;
    if (remaining <= 0) {
      capHit = true;
      break;
    }

    tasks.push(...pageTasks.slice(0, remaining));

    if (!hasNext) {
      break;
    }

    if (pagesFetched >= TASK_SCOPE_DEFAULTS.maxPages || tasks.length >= TASK_SCOPE_DEFAULTS.maxTasks) {
      capHit = true;
      break;
    }

    skip += TASK_SCOPE_DEFAULTS.pageSize;
  }

  const isPartial =
    capHit ||
    hasNext ||
    (typeof total === 'number' ? tasks.length < total : false);

  return {
    tasks,
    taskScope: {
      total,
      fetched: tasks.length,
      hasNext: hasNext || capHit,
      isPartial,
      capHit,
    },
  };
};

// Load all projects with their details
export const loadAllProjects = createAsyncThunk<
  void,
  { force?: boolean },
  { dispatch: AppDispatch; state: RootState }
>('data/loadAllProjects', async ({ force = false }, { dispatch, getState }) => {
  const state = getState();
  const lastLoadedAt = state.project.lastLoadedAt;

  // Check cache validity
  if (!force && lastLoadedAt && Date.now() - lastLoadedAt < CACHE_TTL) {
    return;
  }

  // If already loading, wait for the existing promise
  if (projectsLoadingPromise) {
    return projectsLoadingPromise;
  }

  const loadProjects = async () => {
    dispatch(setLoading(true));
    try {
      const projectsResp = await listProjects();
      const projects = projectsResp.data;

      dispatch(setProjects(projects));
      // Do not eagerly fetch details for every project here.
      // For large workspaces this creates long blocking startup loads and UI freezes.
      // Pages that need detailed project stats fetch them on demand.
      dispatch(setError(null));
    } catch (err: unknown) {
      console.error('[Redux] Failed to load projects:', err);
      dispatch(setError(getErrorMessage(err, 'Failed to load projects')));
    } finally {
      dispatch(setLoading(false));
      projectsLoadingPromise = null;
    }
  };

  projectsLoadingPromise = loadProjects();
  return projectsLoadingPromise;
});

// Load all tasks
export const loadAllTasks = createAsyncThunk<
  void,
  { force?: boolean; projectId?: number },
  { dispatch: AppDispatch; state: RootState }
>('data/loadAllTasks', async ({ force = false, projectId }, { dispatch, getState }) => {
  const state = getState();
  const { lastLoadedAllAt, lastLoadedAtByProject, taskScopeByProject } = state.task;

  if (!force) {
    if (typeof projectId === 'number') {
      const lastProjectLoad = lastLoadedAtByProject[projectId];
      const taskScope = taskScopeByProject[projectId];
      if (lastProjectLoad && Date.now() - lastProjectLoad < CACHE_TTL && taskScope && !taskScope.isPartial) {
        return;
      }
    } else if (lastLoadedAllAt && Date.now() - lastLoadedAllAt < CACHE_TTL) {
      return;
    }
  }

  dispatch(setTasksLoading(true));
  try {
    if (typeof projectId === 'number') {
      const { tasks, taskScope } = await loadProjectTasksWithScope(projectId);
      dispatch(setTasks({ tasks, projectId, taskScope, updateProjectFreshness: true }));
    } else {
      const tasks = (await listTasks(undefined, { timeout: 30000 })) as Task[];
      dispatch(setTasks({ tasks, updateProjectFreshness: false }));
    }

    dispatch(setTasksError(null));
  } catch (err: unknown) {
    console.error('[Redux] Failed to load tasks:', err);
    dispatch(setTasksError(getErrorMessage(err, 'Failed to load tasks')));
  } finally {
    dispatch(setTasksLoading(false));
  }
});

// Load all sprints
export const loadAllSprints = createAsyncThunk<
  void,
  { force?: boolean; projectId?: number },
  { dispatch: AppDispatch; state: RootState }
>('data/loadAllSprints', async ({ force = false, projectId }, { dispatch, getState }) => {
  if (typeof projectId !== 'number') {
    return;
  }

  const state = getState();
  const lastLoadedAt = state.sprint.lastLoadedAtByProject[projectId];
  const hasCachedProjectSprints = Array.isArray(state.sprint.sprintsByProject[projectId]);

  if (!force && lastLoadedAt && Date.now() - lastLoadedAt < CACHE_TTL && hasCachedProjectSprints) {
    dispatch(setActiveSprintByProject(projectId));
    dispatch(setSprintsError(null));
    return;
  }

  dispatch(setSprintsLoading(true));
  try {
    const sprints = await listSprints({ projectId }, { timeout: 30000 });

    dispatch(setSprints({ projectId, sprints }));
    dispatch(setSprintsError(null));
  } catch (err: unknown) {
    console.error('[Redux] Failed to load sprints:', err);
    dispatch(setSprintsError(getErrorMessage(err, 'Failed to load sprints')));
  } finally {
    dispatch(setSprintsLoading(false));
  }
});

// Load all data for a specific project
export const loadProjectData = createAsyncThunk<
  void,
  { projectId: number; force?: boolean },
  { dispatch: AppDispatch; state: RootState }
>('data/loadProjectData', async ({ projectId, force = false }, { dispatch, getState }) => {

  // Load all data in parallel
  await Promise.all([
    dispatch(loadAllProjects({ force })),
    dispatch(loadAllTasks({ force, projectId })),
    dispatch(loadAllSprints({ force, projectId }))
  ]);

  // Set current project
  const state = getState();
  const project = state.project.projects.find(p => p.id === projectId);
  if (project) {
    dispatch(setCurrentProject(project));
  }
});

// Track if initialization is already in progress
let initializationInProgress = false;

// Initialize app data on startup
export const initializeAppData = createAsyncThunk<
  void,
  void,
  { dispatch: AppDispatch }
>('data/initialize', async (_, { dispatch }) => {
  // Prevent duplicate initialization
  if (initializationInProgress) {
    return;
  }

  initializationInProgress = true;

  try {
    // Load projects first
    await dispatch(loadAllProjects({ force: false })); // Changed to false to use cache if available

    // Then load tasks in background.
    // Sprint loading is project-scoped only and starts when project context is known.
    dispatch(loadAllTasks({ force: false }));
  } catch (error) {
    console.error('[Redux] Error initializing app data:', error);
  } finally {
    initializationInProgress = false;
  }
});
