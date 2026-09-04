import { useCallback, useRef, useState, type Dispatch, type SetStateAction } from 'react';

import {
  getProjectSprints,
  getSprintBurndown,
  getSprintCapacity,
  getSprintQuality,
  getBoardsForProject,
  type Board,
  type Sprint,
  type SprintCapacity,
  type SprintQuality,
  type BurndownResponse,
} from '../../services/api';
import { selectActiveSprint, getCanonicalSprintId } from '../../utils/sprintNormalization';

export type SectionLoading = {
  metrics: boolean;
  tasks: boolean;
  burndown: boolean;
  team: boolean;
  risks: boolean;
  sprints: boolean;
  sprintInsights: boolean;
};

interface SprintInsightsOptions {
  projectId: string | undefined;
  logNonFatal: (label: string, err: unknown) => void;
  setSectionLoading: Dispatch<SetStateAction<SectionLoading>>;
}

/**
 * Sprint-analytics domain for the project page (E6 decomposition).
 *
 * Owns boards/sprints selectors and the per-sprint insights bundle
 * (burndown/quality/capacity), including the clear-before-load semantics
 * that prevent the previous sprint's data mixing with the next one.
 */
export function useSprintInsights({ projectId, logNonFatal, setSectionLoading }: SprintInsightsOptions) {
  const [boards, setBoards] = useState<Board[]>([]);
  const [boardId, setBoardId] = useState<number | ''>('');
  const [sprints, setSprints] = useState<Sprint[]>([]);
  const [selectedSprint, setSelectedSprint] = useState<number | ''>('');
  const [sprintBurndown, setSprintBurndown] = useState<BurndownResponse | null>(null);
  const [sprintQuality, setSprintQuality] = useState<SprintQuality | null>(null);
  const [sprintCapacity, setSprintCapacity] = useState<SprintCapacity | null>(null);
  const boardIdRef = useRef<number | ''>('');

  const clearSprintInsights = useCallback(() => {
    setSprintBurndown(null);
    setSprintQuality(null);
    setSprintCapacity(null);
  }, []);

  const loadSprintInsights = useCallback(
    async (sprintId: number) => {
      setSectionLoading((s) => ({ ...s, sprintInsights: true }));
      // Clear the previous sprint's insights before loading the next so the
      // skeleton shows during the switch instead of mixing sprints.
      clearSprintInsights();
      try {
        try {
          setSprintBurndown(await getSprintBurndown(sprintId));
        } catch (err) {
          logNonFatal('background load', err);
        }
        try {
          setSprintQuality(await getSprintQuality(sprintId));
        } catch (err) {
          logNonFatal('background load', err);
        }
        try {
          setSprintCapacity(await getSprintCapacity(sprintId));
        } catch (err) {
          logNonFatal('background load', err);
        }
      } finally {
        setSectionLoading((s) => ({ ...s, sprintInsights: false }));
      }
    },
    [clearSprintInsights, logNonFatal, setSectionLoading],
  );

  const handleBoardChange = useCallback(
    async (nextBoardId: number) => {
      if (!projectId) return;
      setBoardId(nextBoardId);
      boardIdRef.current = nextBoardId;
      try {
        const sp = await getProjectSprints(Number(projectId), 10, nextBoardId);
        const sprintList = sp.sprints || [];
        setSprints(sprintList);
        const currentSprintStillExists =
          typeof selectedSprint === 'number' &&
          sprintList.some((sprint) => getCanonicalSprintId(sprint) === selectedSprint);
        const preferredSprint = currentSprintStillExists
          ? selectedSprint
          : (getCanonicalSprintId(selectActiveSprint(sprintList)) ??
            getCanonicalSprintId(sprintList[0]) ??
            '');
        setSelectedSprint(preferredSprint);
        if (typeof preferredSprint === 'number') {
          await loadSprintInsights(preferredSprint);
        } else {
          clearSprintInsights();
        }
      } catch (err) {
        logNonFatal('background load', err);
      }
    },
    [projectId, loadSprintInsights, selectedSprint, logNonFatal, clearSprintInsights],
  );

  const handleSprintChange = useCallback(
    async (nextSprintId: number) => {
      setSelectedSprint(nextSprintId);
      await loadSprintInsights(nextSprintId);
    },
    [loadSprintInsights],
  );

  /** Boards -> sprints -> sprint analytics chain used by the initial page load. */
  const loadSprintsSection = useCallback(
    async (jiraKey: string | undefined): Promise<void> => {
      try {
        if (jiraKey) {
          const b = await getBoardsForProject(jiraKey);
          setBoards(b.boards || []);
          if ((b.boards || []).length) {
            const primaryBoard =
              (b.boards || []).find((board) => board.type === 'scrum') || b.boards[0];
            setBoardId(primaryBoard.id);
            boardIdRef.current = primaryBoard.id;
          }
        }
      } catch (err) {
        logNonFatal('background load', err);
      }
      try {
        const sp = await getProjectSprints(
          Number(projectId),
          10,
          typeof boardIdRef.current === 'number' ? boardIdRef.current : undefined,
        );
        const sprintList = sp.sprints || [];
        setSprints(sprintList);
        const activeSprintId =
          getCanonicalSprintId(selectActiveSprint(sprintList)) ??
          getCanonicalSprintId(sprintList[0]);
        setSectionLoading((s) => ({ ...s, sprints: false }));
        if (typeof activeSprintId === 'number') {
          setSelectedSprint(activeSprintId);
          await loadSprintInsights(activeSprintId);
        } else {
          setSelectedSprint('');
          clearSprintInsights();
          setSectionLoading((s) => ({ ...s, sprintInsights: false }));
        }
      } catch (e) {
        console.error(e);
        setSectionLoading((s) => ({ ...s, sprints: false, sprintInsights: false }));
      }
    },
    [projectId, loadSprintInsights, clearSprintInsights, logNonFatal, setSectionLoading],
  );

  /** Reset for a project switch (the page calls this before loading the new project). */
  const resetForProjectSwitch = useCallback(() => {
    setBoards([]);
    setSprints([]);
    setSelectedSprint('');
    setBoardId('');
    boardIdRef.current = '';
    clearSprintInsights();
  }, [clearSprintInsights]);

  return {
    boards,
    boardId,
    sprints,
    selectedSprint,
    sprintBurndown,
    sprintQuality,
    sprintCapacity,
    loadSprintInsights,
    handleBoardChange,
    handleSprintChange,
    loadSprintsSection,
    resetForProjectSwitch,
  };
}
