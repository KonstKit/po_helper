import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { logout } from './authSlice';

interface Sprint {
  id: number;
  project_id: number;
  jira_id?: string;
  name: string;
  start_date?: string;
  end_date?: string;
  status: string;
  progress?: number;
  total_tasks?: number;
  completed_tasks?: number;
  total_estimate?: number;
  total_spent?: number;
}

interface SprintState {
  sprints: Sprint[];
  activeSprint: Sprint | null;
  loading: boolean;
  error: string | null;
  lastLoadedAt: number | null;
  sprintsByProject: Record<number, Sprint[]>;
}

const createInitialState = (): SprintState => ({
  sprints: [],
  activeSprint: null,
  loading: false,
  error: null,
  lastLoadedAt: null,
  sprintsByProject: {},
});

const initialState: SprintState = createInitialState();

const sprintSlice = createSlice({
  name: 'sprint',
  initialState,
  reducers: {
    setSprints: (state, action: PayloadAction<Sprint[]>) => {
      state.sprints = action.payload;
      state.lastLoadedAt = Date.now();

      // Group sprints by project
      state.sprintsByProject = {};
      action.payload.forEach(sprint => {
        if (!state.sprintsByProject[sprint.project_id]) {
          state.sprintsByProject[sprint.project_id] = [];
        }
        state.sprintsByProject[sprint.project_id].push(sprint);
      });

      // Find active sprint
      state.activeSprint = action.payload.find(s => s.status === 'active') || null;
    },
    setActiveSprint: (state, action: PayloadAction<Sprint | null>) => {
      state.activeSprint = action.payload;
    },
    setSprintsLoading: (state, action: PayloadAction<boolean>) => {
      state.loading = action.payload;
    },
    setSprintsError: (state, action: PayloadAction<string | null>) => {
      state.error = action.payload;
    },
  },
  extraReducers: (builder) => {
    builder.addCase(logout, () => createInitialState());
  },
});

export const { setSprints, setActiveSprint, setSprintsLoading, setSprintsError } = sprintSlice.actions;
export default sprintSlice.reducer;
