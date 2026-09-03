import { useCallback, useEffect, useRef, useState } from "react";

import {
  bindRepositoryToProject,
  getIntegrationsStatus,
  getProjectRepositories,
  listGitlabProjects,
  setPrimaryRepository,
  unbindRepositoryFromProject,
  type GitlabProjectSummary,
  type RepositoryProvider,
  type ProjectRepositoryLink,
} from "../../services/api";
import { getErrorMessage } from "../../utils/errorUtils";
import { clearIntegrationStatusCache } from "../../services/api";

export interface RepoManagerToast {
  open: boolean;
  type: "success" | "error" | "info" | "warning";
  msg: string;
}

interface RepoManagerOptions {
  projectId: string | undefined;
  showToast: (toast: RepoManagerToast) => void;
}

/**
 * Repository-binding domain state for the project page (E6 decomposition).
 *
 * Owns bindings list, provider availability, the GitLab project search
 * (pagination + append) and all link/unlink/primary mutations; the page
 * only renders the extracted dialog and passes through the tab props.
 */
export function useProjectRepositories({ projectId, showToast }: RepoManagerOptions) {
  const id = projectId;
  const gitlabHasNextPageRef = useRef<boolean>(false);
  const [repoBindings, setRepoBindings] = useState<ProjectRepositoryLink[]>([]);
  const [repoLoading, setRepoLoading] = useState(false);
  const [repoDialogOpen, setRepoDialogOpen] = useState(false);
  const [repoForm, setRepoForm] = useState<{
    repositoryUrl: string;
    provider: RepositoryProvider;
    repoSlug: string;
    isPrimary: boolean;
  }>({
    repositoryUrl: "",
    provider: 'github',
    repoSlug: "",
    isPrimary: true,
  });
  const [gitlabProjects, setGitlabProjects] = useState<GitlabProjectSummary[]>([]);
  const [gitlabLoading, setGitlabLoading] = useState(false);
  const [gitlabError, setGitlabError] = useState<string | null>(null);
  const [gitlabSearch, setGitlabSearch] = useState('');
  const [gitlabGroupPath, setGitlabGroupPath] = useState('');
  const [gitlabPage, setGitlabPage] = useState(1);
  const [repoProviders, setRepoProviders] = useState<{ github: boolean; gitlab: boolean }>({ github: false, gitlab: false });
  const [repoError, setRepoError] = useState<string | null>(null);
  const [repoSaving, setRepoSaving] = useState(false);
  const [repoAction, setRepoAction] = useState<{ type: "primary" | "remove"; id: number } | null>(null);

  const reloadRepositories = useCallback(
    async (showError = true) => {
      if (!id) return;
      setRepoLoading(true);
      try {
        const updated = await getProjectRepositories(Number(id));
        setRepoBindings(updated);
      } catch (error) {
        if (showError) {
          const message = getErrorMessage(error, "Failed to load repositories");
          showToast({ open: true, type: "error", msg: message });
        }
      } finally {
        setRepoLoading(false);
      }
    },
    [id, showToast],
  );

  const performGitlabSearch = useCallback(
    async (page: number, options: { append?: boolean } = {}) => {
      if (!repoProviders.gitlab) {
        return;
      }

      const append = options.append ?? false;
      if (!append) {
        setGitlabProjects([]);
      }
      setGitlabLoading(true);
      setGitlabError(null);

      try {
        const response = await listGitlabProjects({
          groupPath: gitlabGroupPath || undefined,
          search: gitlabSearch || undefined,
          page,
          includeSubgroups: true,
        });

        const projects = response.projects ?? [];
        setGitlabProjects(prev => (append ? [...prev, ...projects] : projects));

        const nextRaw = response.pagination?.next_page ?? null;
        const hasNext = Boolean(nextRaw && String(nextRaw).trim() && String(nextRaw) !== '0');
        gitlabHasNextPageRef.current = hasNext;
        setGitlabPage(page);
      } catch (error) {
        setGitlabError(getErrorMessage(error, 'Failed to fetch GitLab projects'));
      } finally {
        setGitlabLoading(false);
      }
    },
    [gitlabGroupPath, gitlabSearch, repoProviders.gitlab],
  );

  useEffect(() => {
    if (!repoDialogOpen) {
      setGitlabProjects([]);
      setGitlabError(null);
      setGitlabLoading(false);
      gitlabHasNextPageRef.current = false;
      return;
    }
    setGitlabPage(1);
    void performGitlabSearch(1);
  }, [performGitlabSearch, repoDialogOpen]);

  useEffect(() => {
    if (!repoDialogOpen || repoForm.provider !== 'gitlab' || !repoProviders.gitlab) {
      return;
    }
    setGitlabPage(1);
    void performGitlabSearch(1);
  }, [performGitlabSearch, repoDialogOpen, repoForm.provider, repoProviders.gitlab]);

  const handleOpenRepoDialog = () => {
    setRepoDialogOpen(true);
  };

  const handleRepoDialogClose = () => {
    if (repoSaving) return;
    setRepoDialogOpen(false);
    setRepoError(null);
  };

  const handleRepoSubmit = async () => {
    if (!id) return;
    const url = repoForm.repositoryUrl.trim();
    const slug = repoForm.repoSlug.trim();

    setRepoError(null);

    if (!url && !slug) {
      setRepoError('Provide a repository URL or slug.');
      return;
    }

    const providerConfigured =
      repoForm.provider === 'github' ? repoProviders.github : repoProviders.gitlab;

    if (!url && !providerConfigured) {
      setRepoError(
        `${repoForm.provider === 'gitlab' ? 'GitLab' : 'GitHub'} integration is not configured.`,
      );
      return;
    }

    setRepoSaving(true);
    try {
      await bindRepositoryToProject(Number(id), {
        repositoryUrl: url || undefined,
        repoSlug: url ? undefined : slug || undefined,
        provider: url ? undefined : repoForm.provider,
        isPrimary: repoForm.isPrimary,
      });
      setRepoDialogOpen(false);
      showToast({
        open: true,
        type: 'success',
        msg: 'Repository linked to project.',
      });
      await reloadRepositories();
    } catch (error) {
      setRepoError(getErrorMessage(error, 'Failed to link repository'));
    } finally {
      setRepoSaving(false);
    }
  };

  const handleSetPrimaryRepository = async (binding: ProjectRepositoryLink) => {
    if (!id) return;
    setRepoAction({ type: 'primary', id: binding.repository_id });
    try {
      await setPrimaryRepository(Number(id), binding.repository_id);
      showToast({
        open: true,
        type: 'success',
        msg: 'Primary repository updated.',
      });
      await reloadRepositories();
    } catch (error) {
      showToast({
        open: true,
        type: 'error',
        msg: getErrorMessage(error, 'Failed to update primary repository'),
      });
    } finally {
      setRepoAction(null);
    }
  };

  const handleRemoveRepository = async (binding: ProjectRepositoryLink) => {
    if (!id) return;
    setRepoAction({ type: 'remove', id: binding.repository_id });
    try {
      await unbindRepositoryFromProject(Number(id), binding.repository_id);
      showToast({
        open: true,
        type: 'success',
        msg: 'Repository unlinked from project.',
      });
      await reloadRepositories();
    } catch (error) {
      showToast({
        open: true,
        type: 'error',
        msg: getErrorMessage(error, 'Failed to remove repository'),
      });
    } finally {
      setRepoAction(null);
    }
  };

  // initial bindings load with stale-response guard (review MF-02)
  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    (async () => {
      setRepoLoading(true);
      try {
        const data = await getProjectRepositories(Number(id));
        if (!cancelled) setRepoBindings(data);
      } catch (error) {
        if (!cancelled) {
          showToast({
            open: true,
            type: 'error',
            msg: getErrorMessage(error, 'Failed to load repositories'),
          });
        }
      } finally {
        if (!cancelled) setRepoLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, showToast]);

  // provider availability (moved from the page, E6)
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const integ = await getIntegrationsStatus();
        if (cancelled) return;
        setRepoProviders({
          github: Boolean(integ?.github?.configured && integ?.github?.has_token),
          gitlab: Boolean(integ?.gitlab?.configured && integ?.gitlab?.has_token),
        });
      } catch (error) {
        if (!cancelled) {
          console.error("[ProjectDetail] Failed to load integration status", error);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!id) return;
    void reloadRepositories();
  }, [id, reloadRepositories]);

  useEffect(() => {
    if (!repoDialogOpen) return;
    let cancelled = false;
    (async () => {
      try {
        clearIntegrationStatusCache();
        const integ = await getIntegrationsStatus();
        if (cancelled) return;
        const nextProviders = {
          github: Boolean(integ?.github?.configured && integ?.github?.has_token),
          gitlab: Boolean(integ?.gitlab?.configured && integ?.gitlab?.has_token),
        };
        setRepoProviders(nextProviders);
        const defaultProvider: RepositoryProvider =
          nextProviders.github ? "github" : nextProviders.gitlab ? "gitlab" : "github";
        setRepoForm({
          repositoryUrl: "",
          provider: defaultProvider,
          repoSlug: "",
          isPrimary: repoBindings.length === 0,
        });
        setRepoError(null);
      } catch (error) {
        if (!cancelled) {
          console.error("[ProjectDetail] Failed to refresh integration status", error);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [repoDialogOpen, (repoBindings ?? []).length]);

  const resetGitlabResults = useCallback(() => {
    setGitlabProjects([]);
    gitlabHasNextPageRef.current = false;
  }, []);

  return {
    resetGitlabResults,
    gitlabHasNextPageRef,
    repoBindings,
    repoLoading,
    repoDialogOpen,
    setRepoDialogOpen,
    repoForm,
    setRepoForm,
    gitlabProjects,
    gitlabLoading,
    gitlabError,
    gitlabSearch,
    setGitlabSearch,
    gitlabGroupPath,
    setGitlabGroupPath,
    gitlabPage,
    repoProviders,
    setRepoProviders,
    repoError,
    repoSaving,
    repoAction,
    reloadRepositories,
    handleOpenRepoDialog,
    handleRepoDialogClose,
    handleRepoSubmit,
    handleSetPrimaryRepository,
    handleRemoveRepository,
    performGitlabSearch,
  };
}
