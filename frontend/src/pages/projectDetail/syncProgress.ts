export type JiraSyncTaskStatus = {
  id?: number;
  task_type?: string;
  status?: string;
  started_at?: string | null;
  finished_at?: string | null;
  item_counts?: Record<string, unknown> | null;
  error_code?: string | null;
  error_message?: string | null;
  trigger?: string | null;
};

const RELEVANT_TASK_SKEW_MS = 15_000;
const BACKGROUND_PROGRESS_CAP = 92;

const toTimestamp = (value?: string | null): number | null => {
  if (!value) {
    return null;
  }
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const hasNumericField = (counts: Record<string, unknown> | null | undefined, key: string): boolean =>
  typeof counts?.[key] === "number";

export const selectRelevantJiraSyncTask = (
  tasks: JiraSyncTaskStatus[],
  notBeforeMs?: number,
): JiraSyncTaskStatus | null => {
  const jiraTasks = tasks.filter((task) => task?.task_type === "jira_sync");
  if (jiraTasks.length === 0) {
    return null;
  }
  if (typeof notBeforeMs !== "number" || !Number.isFinite(notBeforeMs)) {
    return jiraTasks[0] ?? null;
  }

  const thresholdMs = notBeforeMs - RELEVANT_TASK_SKEW_MS;
  const relevantTask =
    jiraTasks.find((task) => {
      const startedAtMs = toTimestamp(task?.started_at);
      return startedAtMs !== null && startedAtMs >= thresholdMs;
    }) ?? null;

  return relevantTask;
};

export const getSyncProgressFromTask = (
  task: JiraSyncTaskStatus | null | undefined,
): { percent: number; step: string } | null => {
  if (!task) {
    return null;
  }

  const counts = task.item_counts ?? null;
  if (
    hasNumericField(counts, "tasks_linked") ||
    hasNumericField(counts, "boards_processed") ||
    hasNumericField(counts, "sprints_synced")
  ) {
    return { percent: 88, step: "Linking Jira boards and sprint tasks..." };
  }
  if (hasNumericField(counts, "snapshots_created") || hasNumericField(counts, "sprints_processed")) {
    return { percent: 76, step: "Building sprint snapshots..." };
  }
  if (
    hasNumericField(counts, "worklogs_imported") ||
    hasNumericField(counts, "worklog_issues_processed")
  ) {
    return { percent: 62, step: "Importing Jira worklogs..." };
  }
  if (
    hasNumericField(counts, "issues_processed") ||
    hasNumericField(counts, "issues_added") ||
    hasNumericField(counts, "issues_updated")
  ) {
    return { percent: 42, step: "Saving Jira issues..." };
  }
  if (task.status === "running") {
    return { percent: 20, step: "Fetching Jira issues..." };
  }
  return null;
};

export const getNextSyncProgress = (currentPercent: number): number => {
  const current = Number.isFinite(currentPercent) ? currentPercent : 0;
  if (current >= BACKGROUND_PROGRESS_CAP) {
    return BACKGROUND_PROGRESS_CAP;
  }

  const remaining = BACKGROUND_PROGRESS_CAP - current;
  const step = Math.max(1, Math.ceil(remaining * 0.12));
  return Math.min(BACKGROUND_PROGRESS_CAP, current + step);
};
