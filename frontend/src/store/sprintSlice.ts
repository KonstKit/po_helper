import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { logout } from './authSlice';
import type { Sprint } from '../services/api';
import { selectActiveSprint } from '../utils/sprintNormalization';

interface SprintState {
  sprints: Sprint[];
  activeSprint: Sprint | null;
  loading: boolean;
  error: string | null;
  lastLoadedAt: number | null;
  lastLoadedAtByProject: Record<number, number>;
  sprintsByProject: Record<number, Sprint[]>;
}

const createInitialState = (): SprintState => ({
  sprints: [],
  activeSprint: null,
  loading: false,
  error: null,
  lastLoadedAt: null,
  lastLoadedAtByProject: {},
  sprintsByProject: {},
});

const initialState: SprintState = createInitialState();

const sprintSlice = createSlice({
  name: 'sprint',
  initialState,
  reducers: {
    setSprints: (state, action: PayloadAction<{ projectId: number; sprints: Sprint[] }>) => {
      const { projectId, sprints } = action.payload;
      const now = Date.now();

      state.sprints = sprints;
      state.lastLoadedAt = now;
      state.lastLoadedAtByProject[projectId] = now;
      state.sprintsByProject[projectId] = sprints;
      state.activeSprint = selectActiveSprint(sprints);
    },
    setActiveSprintByProject: (state, action: PayloadAction<number>) => {
      const sprints = state.sprintsByProject[action.payload] || [];
      state.sprints = sprints;
      state.activeSprint = selectActiveSprint(sprints);
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

export const { setSprints, setActiveSprintByProject, setActiveSprint, setSprintsLoading, setSprintsError } = sprintSlice.actions;
export default sprintSlice.reducer;
