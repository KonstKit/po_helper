import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { logout } from './authSlice';

interface Project {
  id: number;
  jira_key: string;
  name: string;
  description?: string;
  status: string;
  total_tasks?: number;
  completed_tasks?: number;
  in_progress_tasks?: number;
  total_estimate_hours?: number;
  total_spent_hours?: number;
  completion_percentage?: number;
}

interface ProjectState {
  projects: Project[];
  currentProject: Project | null;
  loading: boolean;
  error: string | null;
  lastLoadedAt: number | null;
}

const createInitialState = (): ProjectState => ({
  projects: [],
  currentProject: null,
  loading: false,
  error: null,
  lastLoadedAt: null,
});

const initialState: ProjectState = createInitialState();

const projectSlice = createSlice({
  name: 'project',
  initialState,
  reducers: {
    setProjects: (state, action: PayloadAction<Project[]>) => {
      state.projects = action.payload;
      state.lastLoadedAt = Date.now();
    },
    setLastLoadedAt: (state, action: PayloadAction<number | null>) => {
      state.lastLoadedAt = action.payload;
    },
    setCurrentProject: (state, action: PayloadAction<Project>) => {
      state.currentProject = action.payload;
    },
    setLoading: (state, action: PayloadAction<boolean>) => {
      state.loading = action.payload;
    },
    setError: (state, action: PayloadAction<string | null>) => {
      state.error = action.payload;
    },
  },
  extraReducers: (builder) => {
    builder.addCase(logout, () => createInitialState());
  },
});

export const { setProjects, setCurrentProject, setLoading, setError, setLastLoadedAt } = projectSlice.actions;
export default projectSlice.reducer;
