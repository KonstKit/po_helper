import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { logout } from './authSlice';

export interface Task {
  id: number;
  key: string;
  summary: string;
  status: string;
  priority?: string;
  assignee_name?: string;
  project_id?: number | null;
  estimate_hours?: number;
  spent_hours?: number;
  due_date?: string | null;
  created_date?: string | null;
  updated_date?: string | null;
  is_blocker?: boolean;
  business_value?: number | null;
}

interface TaskState {
  tasks: Task[];
  loading: boolean;
  error: string | null;
  lastLoadedAt: number | null;
  lastLoadedAllAt: number | null;
  lastLoadedAtByProject: Record<number, number>;
  tasksByProject: Record<number, Task[]>;
}

const createInitialState = (): TaskState => ({
  tasks: [],
  loading: false,
  error: null,
  lastLoadedAt: null,
  lastLoadedAllAt: null,
  lastLoadedAtByProject: {},
  tasksByProject: {},
});

const initialState: TaskState = createInitialState();

const taskSlice = createSlice({
  name: 'task',
  initialState,
  reducers: {
    setTasks: (state, action: PayloadAction<{ tasks: Task[]; projectId?: number }>) => {
      const { tasks, projectId } = action.payload;
      const now = Date.now();
      state.tasks = tasks;
      state.lastLoadedAt = now;

      if (typeof projectId === 'number') {
        state.lastLoadedAtByProject[projectId] = now;
        state.tasksByProject[projectId] = tasks;
      } else {
        state.lastLoadedAllAt = now;
        state.tasksByProject = {};
        tasks.forEach((task: Task) => {
          if (typeof task.project_id !== 'number') return;
          if (!state.tasksByProject[task.project_id]) {
            state.tasksByProject[task.project_id] = [];
          }
          state.tasksByProject[task.project_id].push(task);
          state.lastLoadedAtByProject[task.project_id] = now;
        });
      }
    },
    updateTask: (state, action: PayloadAction<Task>) => {
      const index = state.tasks.findIndex((task: Task) => task.id === action.payload.id);
      if (index !== -1) {
        state.tasks[index] = action.payload;
      }
      const projectId = action.payload.project_id;
      if (typeof projectId !== 'number') {
        return;
      }
      const projectTasks = state.tasksByProject[projectId];
      if (projectTasks) {
        const projectIndex = projectTasks.findIndex((task: Task) => task.id === action.payload.id);
        if (projectIndex !== -1) {
          projectTasks[projectIndex] = action.payload;
        }
      }
    },
    setTasksLoading: (state, action: PayloadAction<boolean>) => {
      state.loading = action.payload;
    },
    setTasksError: (state, action: PayloadAction<string | null>) => {
      state.error = action.payload;
    },
  },
  extraReducers: (builder) => {
    builder.addCase(logout, () => createInitialState());
  },
});

export const { setTasks, updateTask, setTasksLoading, setTasksError } = taskSlice.actions;
export default taskSlice.reducer;
