import { describe, expect, it } from "vitest";

import {
  getNextSyncProgress,
  getSyncProgressFromTask,
  selectRelevantJiraSyncTask,
  type JiraSyncTaskStatus,
} from "../syncProgress";

describe("syncProgress", () => {
  it("ignores older running sync tasks when selecting the relevant task", () => {
    const tasks: JiraSyncTaskStatus[] = [
      {
        id: 31,
        task_type: "jira_sync",
        status: "running",
        started_at: "2026-03-06T11:57:25Z",
      },
      {
        id: 32,
        task_type: "jira_sync",
        status: "success",
        started_at: "2026-03-06T12:17:30Z",
      },
    ];

    const selected = selectRelevantJiraSyncTask(tasks, Date.parse("2026-03-06T12:17:20Z"));

    expect(selected?.id).toBe(32);
  });

  it("returns null when only unrelated historical tasks exist before the current sync", () => {
    const tasks: JiraSyncTaskStatus[] = [
      {
        id: 31,
        task_type: "jira_sync",
        status: "running",
        started_at: "2026-03-06T11:57:25Z",
      },
    ];

    const selected = selectRelevantJiraSyncTask(tasks, Date.parse("2026-03-06T12:17:20Z"));

    expect(selected).toBeNull();
  });

  it("maps sync task item_counts to a meaningful progress step", () => {
    const task: JiraSyncTaskStatus = {
      task_type: "jira_sync",
      status: "running",
      item_counts: {
        worklogs_imported: 911,
        worklog_issues_processed: 200,
      },
    };

    expect(getSyncProgressFromTask(task)).toEqual({
      percent: 62,
      step: "Importing Jira worklogs...",
    });
  });

  it("advances background progress without jumping straight to completion", () => {
    expect(getNextSyncProgress(15)).toBeGreaterThan(15);
    expect(getNextSyncProgress(15)).toBeLessThanOrEqual(92);
    expect(getNextSyncProgress(95)).toBe(92);
  });
});
