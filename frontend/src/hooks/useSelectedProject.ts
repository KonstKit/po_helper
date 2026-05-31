import { useCallback, useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import type { RootState, AppDispatch } from '../store/store';
import { setProjects, setCurrentProject, setError, setLastLoadedAt } from '../store/projectSlice';
import { listProjects } from '../services/api/projects';
import { readStoredJson, writeStoredJson } from '../utils/browserStorage';

const STORAGE_KEY = 'po_helper_selected_project_id';

// Guards against N hook instances (the header selector + every consuming page)
// all firing the project-list fetch on a cold load. Module-scoped so all
// instances share it; reset in `finally` so a failed load can still be retried
// (UX review M-1: previously each instance issued its own duplicate request).
let projectsFetchInFlight = false;

// Migration helper: older builds persisted the selected project under the
// Dashboard's own keys. If the new key is absent we honour the old last/recent
// selection once, so upgrading users don't land on the wrong project (codex P2).
function readLegacyDashboardProjectId(): number | null {
  try {
    const last = localStorage.getItem('dashboard_last_project_id');
    if (last) {
      const n = Number(last);
      if (Number.isFinite(n) && n > 0) return n;
    }
    const recentRaw = localStorage.getItem('dashboard_recent_project_ids');
    if (recentRaw) {
      const arr = JSON.parse(recentRaw);
      if (Array.isArray(arr) && arr.length > 0) {
        const n = Number(arr[0]);
        if (Number.isFinite(n) && n > 0) return n;
      }
    }
  } catch {
    /* ignore malformed legacy storage */
  }
  return null;
}

/**
 * Single source of truth for the globally-selected project (UX review C4).
 *
 * The app previously selected a project four different ways (Dashboard chips,
 * Analytics dropdown, Quality/Visualization dropdowns, a free-text "Project ID"
 * field in Review) and the choice did not carry across pages. This hook backs a
 * single global selector: it loads the project list once, restores the last
 * choice from localStorage, and exposes `selectProject` so any screen — and the
 * header selector — reads/writes the same Redux `currentProject`.
 */
export function useSelectedProject() {
  const dispatch = useDispatch<AppDispatch>();
  const projects = useSelector((s: RootState) => s.project.projects);
  const currentProject = useSelector((s: RootState) => s.project.currentProject);
  const loading = useSelector((s: RootState) => s.project.loading);
  // Set by the `setProjects` reducer, so it is a reliable "the list has loaded"
  // signal even though this hook fetches without toggling `loading`. Consumers
  // (e.g. ReviewQueue) use it to avoid firing project-scoped requests before the
  // global selection settles (codex).
  const lastLoadedAt = useSelector((s: RootState) => s.project.lastLoadedAt);
  const error = useSelector((s: RootState) => s.project.error);

  // Load the project list once if it has not been fetched yet. The module-level
  // in-flight guard prevents the header selector and the consuming page from each
  // issuing a duplicate request on a cold load (UX review M-1).
  useEffect(() => {
    if (projects.length > 0 || projectsFetchInFlight) return;
    let cancelled = false;
    projectsFetchInFlight = true;
    listProjects({ limit: 200 })
      .then((res) => {
        if (cancelled) return;
        const items = Array.isArray(res?.data) ? res.data : [];
        dispatch(setProjects(items as never));
        dispatch(setError(null));
      })
      .catch(() => {
        if (cancelled) return;
        // Mark the load as settled-with-error so project-scoped pages stop
        // waiting on `ready` instead of hanging forever on a failed list load
        // (codex P2). lastLoadedAt is the "settled" signal; error carries why.
        dispatch(setError('Failed to load projects'));
        dispatch(setLastLoadedAt(Date.now()));
      })
      .finally(() => {
        projectsFetchInFlight = false;
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Restore the persisted selection (or default to the first project) once the
  // list is available and nothing is selected yet.
  useEffect(() => {
    if (currentProject || projects.length === 0) return;
    // Prefer the new key; for users upgrading from the old per-page selection,
    // fall back to the Dashboard's previous last/recent project keys before
    // defaulting to the first project (codex P2).
    const storedId =
      readStoredJson<number | null>(STORAGE_KEY, null) ?? readLegacyDashboardProjectId();
    const match =
      (storedId != null && projects.find((p) => p.id === storedId)) || projects[0] || null;
    if (match) {
      dispatch(setCurrentProject(match));
      // Migrate the resolved selection into the new key so this runs once.
      writeStoredJson(STORAGE_KEY, match.id);
    }
  }, [currentProject, projects, dispatch]);

  const selectProject = useCallback(
    (id: number | null) => {
      if (id == null) return;
      const match = projects.find((p) => p.id === id);
      if (match) {
        dispatch(setCurrentProject(match));
        writeStoredJson(STORAGE_KEY, id);
      }
    },
    [projects, dispatch],
  );

  return {
    projects,
    currentProject,
    projectId: currentProject?.id ?? null,
    selectProject,
    loading,
    lastLoadedAt,
    error,
    // True once the project list has settled (loaded OR failed) OR we already
    // have project context (a preloaded / rehydrated store where lastLoadedAt is
    // still null). Project-scoped pages gate on this, so it must NOT stay false
    // when projects/currentProject are already present (codex P1).
    ready:
      lastLoadedAt != null || error != null || projects.length > 0 || currentProject != null,
  };
}

export default useSelectedProject;
