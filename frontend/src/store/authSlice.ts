import { createAsyncThunk, createSlice, PayloadAction } from "@reduxjs/toolkit";
import { analytics } from "../services/analytics";
import api from "../services/api/client";

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
  isAuthenticated: boolean;
  /** 'probing' until the boot /users/me check resolves. */
  sessionProbe: 'probing' | 'done';
  loading: boolean;
}

// Boot-time session restore: the httpOnly cookie cannot be read from JS, so
// the app asks the backend whether the session is alive (JWT storage M2).
export const probeSession = createAsyncThunk(
  'auth/probeSession',
  async (_, { rejectWithValue }) => {
    try {
      // SESSION_PROBE marks the request: the axios response interceptor
      // suppresses the auth-error broadcast for it, so a stale probe 401
      // can never log a freshly signed-in user out.
      const { data } = await api.get<User>('/v1/users/me', { headers: { "X-Session-Probe": "1" } });
      return data;
    } catch (e) {
      // Only a confirmed 401 (dead cookie session) may trigger the
      // auth-error cleanup downstream; network/5xx failures must not
      // log out a possibly-valid session.
      const status = (e as { response?: { status?: number } })?.response?.status;
      return rejectWithValue({ status: status ?? null });
    }
  },
);

const initialState: AuthState = {
  user: null,
  isAuthenticated: false,
  sessionProbe: 'probing',
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
    loginSuccess: (state, action: PayloadAction<{ user: User }>) => {
      state.user = action.payload.user;
      state.isAuthenticated = true;
      state.sessionProbe = 'done';
      state.loading = false;
      // The owner identity now comes from the authenticated user (the
      // httpOnly cookie hides the JWT from JS). Set it before the
      // inherited-state check below.
      analytics.setSessionOwner(action.payload.user.email);
      analytics.setConfirmedSessionOwner(action.payload.user.email);
      analytics.dropInheritedStateIfOwnerChanged();
      analytics.resumePendingFlushIfAny();
    },
    loginFailure: (state) => {
      state.loading = false;
    },
    logout: (state) => {
      state.user = null;
      state.isAuthenticated = false;
      state.sessionProbe = 'done';
      // Legacy cleanup: the localStorage token is gone since M2.
      localStorage.removeItem('token');
      analytics.clearSessionOwner();
      analytics.clearConfirmedSessionOwner();
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(probeSession.fulfilled, (state, action) => {
        // Stale-probe guard: a probe that settles after login/logout must
        // not overwrite the newer auth decision.
        if (state.sessionProbe !== "probing") return;
        state.user = action.payload;
        state.isAuthenticated = true;
        state.sessionProbe = 'done';
        analytics.setSessionOwner(action.payload.email);
        // Confirm the session identity for the cross-tab analytics gate.
        analytics.setConfirmedSessionOwner(action.payload.email);
        // Cold start with a persisted pending batch: the constructor skips
        // the resume while no owner is known; now the probe confirmed one.
        analytics.resumePendingFlushIfAny();
      })
      .addCase(probeSession.rejected, (state, action) => {
        if (state.sessionProbe !== "probing") return;
        state.isAuthenticated = false;
        state.sessionProbe = 'done';
        const payload = action.payload as { status?: number | null } | undefined;
        if (payload?.status !== 401) return;
        // Do not run cleanup while an OAuth callback is pending: wiping
        // sessionStorage and navigating would discard the callback
        // parameters before the Login flow consumes them.
        const onOAuthCallback =
          typeof window !== 'undefined' &&
          (new URLSearchParams(window.location.search).has('code') ||
            sessionStorage.getItem('oauth_provider') !== null);
        if (onOAuthCallback) return;
        // The cookie session is dead: route through the standard cleanup
        // (analytics soft reset + user-data storage clear) so a previous
        // user's cached state cannot leak into the next login.
        // Deferred to a microtask: the reducer must stay synchronous and
        // the auth-error listener performs its own Redux dispatches.
        if (typeof window !== 'undefined') {
          queueMicrotask(() => {
            window.dispatchEvent(new CustomEvent('auth-error'));
          });
        }
      });
  },
});

export const { setUser, loginStart, loginSuccess, loginFailure, logout } = authSlice.actions;
export default authSlice.reducer;
