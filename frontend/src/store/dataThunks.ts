import { createAsyncThunk } from '@reduxjs/toolkit';
import {
  listProjects,
  getProjectById,
  listTasks,
  listSprints
} from '../services/api';
import { setProjects, setLoading, setError, setCurrentProject } from './projectSlice';
import { setTasks, setTasksLoading, setTasksError } from './taskSlice';
import { setSprints, setSprintsLoading, setSprintsError } from './sprintSlice';
import { AppDispatch, RootState } from './store';

const CACHE_TTL = 60000; // 1 minute cache

// Track active project loading to prevent duplicates
let projectsLoadingPromise: Promise<void> | null = null;

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
    console.log('[Redux] Using cached projects data');
    return;
  }

  // If already loading, wait for the existing promise
  if (projectsLoadingPromise) {
    console.log('[Redux] Projects already loading, waiting for completion');
    return projectsLoadingPromise;
  }

  const loadProjects = async () => {
    dispatch(setLoading(true));
    try {
      console.log('[Redux] Loading projects list...');
      const projects = await listProjects({ timeout: 30000 });

      dispatch(setProjects(projects));

      // Load project details in parallel for dashboard stats
      console.log('[Redux] Loading project details...');
      const projectDetails = await Promise.allSettled(
        projects.map(p => getProjectById(p.id, { timeout: 30000 }))
      );

      // Merge details into projects
      const enhancedProjects = projects.map((p, idx) => {
        const result = projectDetails[idx];
        if (result.status === 'fulfilled') {
          return { ...p, ...result.value };
        }
        return p;
      });

      dispatch(setProjects(enhancedProjects));
      dispatch(setError(null));
    } catch (err: any) {
      console.error('[Redux] Failed to load projects:', err);
      dispatch(setError(err.message || 'Failed to load projects'));
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
  const { lastLoadedAllAt, lastLoadedAtByProject } = state.task;

  if (!force) {
    if (typeof projectId === 'number') {
      const lastProjectLoad = lastLoadedAtByProject[projectId];
      if (lastProjectLoad && Date.now() - lastProjectLoad < CACHE_TTL) {
        console.log(`[Redux] Using cached tasks data for project ${projectId}`);
        return;
      }
    } else if (lastLoadedAllAt && Date.now() - lastLoadedAllAt < CACHE_TTL) {
      console.log('[Redux] Using cached tasks data (all projects)');
      return;
    }
  }

  dispatch(setTasksLoading(true));
  try {
    console.log('[Redux] Loading tasks...');
    const tasks = await listTasks({ project_id: projectId }, { timeout: 30000 });

    dispatch(setTasks({ tasks, projectId }));
    dispatch(setTasksError(null));
  } catch (err: any) {
    console.error('[Redux] Failed to load tasks:', err);
    dispatch(setTasksError(err.message || 'Failed to load tasks'));
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
  const state = getState();
  const lastLoadedAt = state.sprint.lastLoadedAt;

  // Check cache validity
  if (!force && lastLoadedAt && Date.now() - lastLoadedAt < CACHE_TTL) {
    console.log('[Redux] Using cached sprints data');
    return;
  }

  dispatch(setSprintsLoading(true));
  try {
    console.log('[Redux] Loading sprints...');
    const sprints = await listSprints({ project_id: projectId }, { timeout: 30000 });

    dispatch(setSprints(sprints));
    dispatch(setSprintsError(null));
  } catch (err: any) {
    console.error('[Redux] Failed to load sprints:', err);
    dispatch(setSprintsError(err.message || 'Failed to load sprints'));
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
  console.log(`[Redux] Loading all data for project ${projectId}`);

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
    console.log('[Redux] Initialization already in progress, skipping');
    return;
  }

  initializationInProgress = true;
  console.log('[Redux] Initializing app data...');

  try {
    // Load projects first
    await dispatch(loadAllProjects({ force: false })); // Changed to false to use cache if available

    // Then load tasks and sprints in parallel
    // Don't wait for all to complete, let them load in background
    dispatch(loadAllTasks({ force: false }));
    dispatch(loadAllSprints({ force: false }));
  } catch (error) {
    console.error('[Redux] Error initializing app data:', error);
  } finally {
    initializationInProgress = false;
  }

  console.log('[Redux] App data initialization started');
});