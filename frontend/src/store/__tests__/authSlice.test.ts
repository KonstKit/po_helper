import { configureStore } from "@reduxjs/toolkit";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../services/api/client", () => ({
  default: { get: vi.fn(), post: vi.fn() },
}));

vi.mock("../../services/analytics", () => ({
  analytics: {
    readAuthGeneration: vi.fn(() => 0),
    bumpAuthGeneration: vi.fn(),
    setSessionOwner: vi.fn(),
    setConfirmedSessionOwner: vi.fn(),
    clearSessionOwner: vi.fn(),
    clearConfirmedSessionOwner: vi.fn(),
    dropInheritedStateIfOwnerChanged: vi.fn(),
    resumePendingFlushIfAny: vi.fn(),
  },
}));

import api from "../../services/api/client";
import { analytics } from "../../services/analytics";
import authReducer, { logout, probeSession } from "../authSlice";

const user = { id: 1, email: "probe@example.com", username: "probe", is_active: true, is_superuser: false };

const probingState = { user: null, isAuthenticated: false, sessionProbe: "probing" as const, loading: false };

const flush = () => new Promise((r) => setTimeout(r, 0));

describe("authSlice probeSession (JWT storage M2)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: user });
  });

  it("cold start: a fulfilled probe accepts the session, sets the owner and resumes the pending flush", async () => {
    const dispatch = vi.fn();
    await probeSession()(dispatch, () => ({}), undefined);
    const action = dispatch.mock.calls.map((c) => c[0]).find((a) => a.type === probeSession.fulfilled.type);
    expect(action).toBeDefined();
    const state = authReducer(probingState, action);
    expect(state.isAuthenticated).toBe(true);
    expect(state.sessionProbe).toBe("done");
    expect(analytics.setSessionOwner).toHaveBeenCalledWith(user.email);
    // Regression: the boot probe must arm the pending analytics flush.
    expect(analytics.resumePendingFlushIfAny).toHaveBeenCalled();
  });

  it("a rejected boot probe broadcasts auth-error and the real listener performs cleanup", async () => {
    const store = configureStore({ reducer: { auth: authReducer } });
    (api.get as ReturnType<typeof vi.fn>).mockRejectedValue(
      Object.assign(new Error("401"), { response: { status: 401 } }),
    );
    const listener = vi.fn(() => {
      // mirrors App.tsx: the auth-error listener performs the cleanup
      // logout, which clears the analytics session owner
      store.dispatch(logout());
    });
    window.addEventListener("auth-error", listener);
    try {
      await store.dispatch(probeSession());
      await flush();
      expect(listener).toHaveBeenCalled();
      expect(store.getState().auth.isAuthenticated).toBe(false);
      expect(analytics.clearSessionOwner).toHaveBeenCalled();
    } finally {
      window.removeEventListener("auth-error", listener);
    }
  });

  it("a probe failure that is not a 401 (network/5xx) does not broadcast auth-error", async () => {
    const store = configureStore({ reducer: { auth: authReducer } });
    (api.get as ReturnType<typeof vi.fn>).mockRejectedValue(
      Object.assign(new Error("upstream down"), { response: { status: 503 } }),
    );
    const dispatched = vi.spyOn(window, "dispatchEvent");
    await store.dispatch(probeSession());
    await new Promise((r) => setTimeout(r, 0));
    const authError = dispatched.mock.calls
      .map((c) => c[0] as CustomEvent)
      .find((e) => e.type === "auth-error");
    expect(authError).toBeUndefined();
    expect(store.getState().auth.isAuthenticated).toBe(false);
    dispatched.mockRestore();
  });

  it("a stale fulfilled probe cannot re-authenticate after logout", () => {
    const loggedOut = { user: null, isAuthenticated: false, sessionProbe: "done" as const, loading: false };
    const state = authReducer(loggedOut, probeSession.fulfilled(user, "req", undefined));
    expect(state.isAuthenticated).toBe(false);
    expect(state.user).toBeNull();
    expect(analytics.setSessionOwner).not.toHaveBeenCalled();
  });

  it("logout clears the analytics session owner", () => {
    const signedIn = { user, isAuthenticated: true, sessionProbe: "done" as const, loading: false };
    authReducer(signedIn, logout());
    expect(analytics.clearSessionOwner).toHaveBeenCalled();
  });
});
