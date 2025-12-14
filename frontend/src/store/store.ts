import { configureStore } from '@reduxjs/toolkit';
import authReducer from './authSlice';
import projectReducer from './projectSlice';
import taskReducer from './taskSlice';
import sprintReducer from './sprintSlice';

export const store = configureStore({
  reducer: {
    auth: authReducer,
    project: projectReducer,
    task: taskReducer,
    sprint: sprintReducer,
  },
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;