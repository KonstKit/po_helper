import { useCallback, useState } from 'react';

import {
  updateProject,
  listPullRequests,
  evaluateQualityGateAndCheck,
  getQualityHistory,
  type QualityHistoryItem,
} from '../../services/api';
import { normalizeQualityGateProvider } from '../../utils/qualityGate';
import { getErrorMessage } from '../../utils/errorUtils';

export type QualityThresholds = {
  min_line?: number | "";
  min_branch?: number | "";
};

interface QualityControlOptions {
  projectId: string | undefined;
  showToast: (t: { open: boolean; type: 'success' | 'error' | 'info' | 'warning'; msg: string }) => void;
  logNonFatal: (label: string, err: unknown) => void;
}

/**
 * Quality-gate domain for the project page (E6 decomposition).
 *
 * Owns threshold editing/saving, the bulk PR quality check with progress,
 * and the quality history that drives the Quality tab chart.
 */
export function useQualityControl({ projectId, showToast, logNonFatal }: QualityControlOptions) {
  const [thresholds, setThresholds] = useState<QualityThresholds>({});

  const applyThresholds = useCallback(
    (qt: { min_line?: unknown; min_branch?: unknown }) => {
      setThresholds({
        min_line: typeof qt.min_line === "number" ? qt.min_line : "",
        min_branch: typeof qt.min_branch === "number" ? qt.min_branch : "",
      });
    },
    [],
  );
  const [hist, setHist] = useState<QualityHistoryItem[]>([]);
  const [qualityLoading, setQualityLoading] = useState(false);
  const [bulkProgress, setBulkProgress] = useState<{
    active: boolean;
    percent: number;
    step: string;
  }>({ active: false, percent: 0, step: '' });

  const loadQualityHistory = useCallback(async () => {
    if (!projectId) return;
    try {
      const h = await getQualityHistory({ projectId: Number(projectId), limit: 20 });
      setHist(h.history || []);
    } catch (err) {
      logNonFatal('background load', err);
    }
  }, [projectId, logNonFatal]);

  const handleSaveThresholds = useCallback(async () => {
    if (!projectId) return;
    try {
      setQualityLoading(true);
      await updateProject(Number(projectId), {
        quality_thresholds: {
          min_line:
            thresholds.min_line === '' ? undefined : thresholds.min_line,
          min_branch:
            thresholds.min_branch === '' ? undefined : thresholds.min_branch,
        },
      });
      showToast({
        open: true,
        type: 'success',
        msg: 'Thresholds saved',
      });
    } catch (e) {
      showToast({
        open: true,
        type: 'error',
        msg: getErrorMessage(e, 'Save failed'),
      });
    } finally {
      setQualityLoading(false);
    }
  }, [projectId, thresholds.min_branch, thresholds.min_line, showToast]);

  const handleBulkQualityCheck = useCallback(async () => {
    if (!projectId) return;
    try {
      setBulkProgress({
        active: true,
        percent: 0,
        step: 'Fetching PRs...',
      });
      const prs = await listPullRequests({
        projectId: Number(projectId),
        limit: 500,
      });
      const list = prs.pull_requests || [];
      for (let i = 0; i < list.length; i++) {
        setBulkProgress({
          active: true,
          percent: Math.round((i / list.length) * 100),
          step: `Checking ${i + 1}/${list.length}`,
        });
        try {
          await evaluateQualityGateAndCheck({
            prNumber: list[i].number,
            projectId: Number(projectId),
            provider: normalizeQualityGateProvider(list[i].provider),
          });
        } catch (err) {
          logNonFatal('background load', err);
        }
      }
      setBulkProgress({
        active: false,
        percent: 100,
        step: 'Done',
      });
      const h = await getQualityHistory({
        projectId: Number(projectId),
        limit: 20,
      });
      setHist(h.history || []);
    } catch (e) {
      setBulkProgress({ active: false, percent: 0, step: '' });
      showToast({
        open: true,
        type: 'error',
        msg: getErrorMessage(e, 'Bulk check failed'),
      });
    }
  }, [projectId, logNonFatal, showToast]);

  return {
    thresholds,
    setThresholds,
    applyThresholds,
    hist,
    qualityLoading,
    bulkProgress,
    loadQualityHistory,
    handleSaveThresholds,
    handleBulkQualityCheck,
  };
}
