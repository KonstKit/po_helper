import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { analytics } from '../services/analytics';

interface User {
  id: number;
  email: string;
  username: string;
  full_name?: string;
  is_active: boolean;
  is_superuser: boolean;
}

interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  loading: boolean;
}

const initialState: AuthState = {
  user: null,
  token: localStorage.getItem('token'),
  isAuthenticated: !!localStorage.getItem('token'),
  loading: false,
};

const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    setUser: (state, action: PayloadAction<User | null>) => {
      state.user = action.payload;
    },
    loginStart: (state) => {
      state.loading = true;
    },
    loginSuccess: (state, action: PayloadAction<{ user: User; token: string }>) => {
      state.user = action.payload.user;
      state.token = action.payload.token;
      state.isAuthenticated = true;
      state.loading = false;
      localStorage.setItem('token', action.payload.token);
      // Detect cross-user signin on the same tab. If the previous session
      // ended via auth-error (softResetForAuthError persisted its owner
      // marker), compare it against the new token's owner; if different,
      // wipe inherited UI analytics state. Same-user re-auth is a no-op.
      analytics.dropInheritedStateIfOwnerChanged();
      // Same-user re-auth and cold-start-with-queue paths leave a
      // persisted pending batch but no active flush timer; arm it now
      // so events do not sit indefinitely waiting for the next tracked
      // interaction.
      analytics.resumePendingFlushIfAny();
    },
    loginFailure: (state) => {
      state.loading = false;
    },
    logout: (state) => {
      state.user = null;
      state.token = null;
      state.isAuthenticated = false;
      localStorage.removeItem('token');
    },
  },
});

export const { setUser, loginStart, loginSuccess, loginFailure, logout } = authSlice.actions;
export default authSlice.reducer;
