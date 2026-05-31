import { useCallback, useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import type { RootState, AppDispatch } from '../store/store';
import { setProjects, setCurrentProject } from '../store/projectSlice';
import { listProjects } from '../services/api/projects';
import { readStoredJson, writeStoredJson } from '../utils/browserStorage';

const STORAGE_KEY = 'po_helper_selected_project_id';

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

  // Load the project list once if it has not been fetched yet.
  useEffect(() => {
    let cancelled = false;
    if (projects.length === 0) {
      listProjects({ limit: 200 })
        .then((res) => {
          if (cancelled) return;
          const items = Array.isArray(res?.data) ? res.data : [];
          dispatch(setProjects(items as never));
        })
        .catch(() => {
          /* surfaced elsewhere; the selector simply stays empty */
        });
    }
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Restore the persisted selection (or default to the first project) once the
  // list is available and nothing is selected yet.
  useEffect(() => {
    if (currentProject || projects.length === 0) return;
    const storedId = readStoredJson<number | null>(STORAGE_KEY, null);
    const match =
      (storedId != null && projects.find((p) => p.id === storedId)) || projects[0] || null;
    if (match) dispatch(setCurrentProject(match));
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
  };
}

export default useSelectedProject;
