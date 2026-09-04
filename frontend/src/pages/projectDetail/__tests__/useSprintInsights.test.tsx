
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

const mocks = vi.hoisted(() => ({
  getProjectSprints: vi.fn(),
  getSprintBurndown: vi.fn(),
  getSprintQuality: vi.fn(),
  getSprintCapacity: vi.fn(),
  getBoardsForProject: vi.fn(),
}));

vi.mock("../../../services/api", () => ({
  getProjectSprints: mocks.getProjectSprints,
  getSprintBurndown: mocks.getSprintBurndown,
  getSprintQuality: mocks.getSprintQuality,
  getSprintCapacity: mocks.getSprintCapacity,
  getBoardsForProject: mocks.getBoardsForProject,
}));

import { useSprintInsights, type SectionLoading } from "../useSprintInsights";

const initialLoading: SectionLoading = {
  metrics: false,
  tasks: false,
  burndown: false,
  team: false,
  risks: false,
  sprints: true,
  sprintInsights: true,
};

const makeSprint = (id: number, state: string) => ({ id, name: "S" + id, state });

describe("useSprintInsights", () => {
  const logNonFatal = vi.fn();
  const loadingUpdates: Array<Partial<SectionLoading>> = [];
  const setSectionLoading = vi.fn(
    (action: React.SetStateAction<SectionLoading>) => {
      if (typeof action === "function") {
        loadingUpdates.push(action(initialLoading));
      }
    },
  );

  beforeEach(() => {
    vi.resetAllMocks();
    loadingUpdates.length = 0;
    mocks.getSprintBurndown.mockResolvedValue({ points: [] });
    mocks.getSprintQuality.mockResolvedValue({ score: 1 });
    mocks.getSprintCapacity.mockResolvedValue({ capacity: 1 });
  });

  const render = (projectId: string | undefined = "1") =>
    renderHook(
      (props: { projectId: string | undefined }) =>
        useSprintInsights({ projectId: props.projectId, logNonFatal, setSectionLoading }),
      { initialProps: { projectId } },
    );

  it("loadSprintsSection picks the scrum board and the active sprint", async () => {
    mocks.getBoardsForProject.mockResolvedValue({
      boards: [
        { id: 11, type: "kanban", name: "K" },
        { id: 22, type: "scrum", name: "S" },
      ],
    });
    mocks.getProjectSprints.mockResolvedValue({
      sprints: [makeSprint(101, "closed"), makeSprint(102, "active")],
    });
    const hook = render();
    await act(async () => {
      await hook.result.current.loadSprintsSection("KEY");
    });
    expect(hook.result.current.boards).toHaveLength(2);
    expect(hook.result.current.boardId).toBe(22);
    expect(hook.result.current.selectedSprint).toBe(102);
    expect(mocks.getSprintBurndown).toHaveBeenCalledWith(102);
    expect(mocks.getSprintQuality).toHaveBeenCalledWith(102);
    expect(mocks.getSprintCapacity).toHaveBeenCalledWith(102);
    expect(hook.result.current.sprintBurndown).toEqual({ points: [] });
  });

  it("loadSprintsSection clears insights when there are no sprints", async () => {
    mocks.getBoardsForProject.mockResolvedValue({ boards: [] });
    mocks.getProjectSprints.mockResolvedValue({ sprints: [] });
    const hook = render();
    await act(async () => {
      await hook.result.current.loadSprintsSection("KEY");
    });
    expect(hook.result.current.selectedSprint).toBe("");
    expect(hook.result.current.sprintBurndown).toBeNull();
    expect(hook.result.current.sprintQuality).toBeNull();
    expect(hook.result.current.sprintCapacity).toBeNull();
  });

  it("handleBoardChange keeps the selected sprint when it still exists", async () => {
    mocks.getProjectSprints.mockResolvedValue({
      sprints: [makeSprint(201, "active"), makeSprint(202, "closed")],
    });
    const hook = render();
    await act(async () => {
      await hook.result.current.handleSprintChange(202);
    });
    await act(async () => {
      await hook.result.current.handleBoardChange(9);
    });
    expect(mocks.getProjectSprints).toHaveBeenCalledWith(1, 10, 9);
    expect(hook.result.current.selectedSprint).toBe(202);
    expect(mocks.getSprintBurndown).toHaveBeenCalledWith(202);
  });

  it("handleBoardChange falls back to the active sprint when the current one is gone", async () => {
    mocks.getProjectSprints.mockResolvedValue({
      sprints: [makeSprint(301, "active"), makeSprint(302, "closed")],
    });
    const hook = render();
    await act(async () => {
      await hook.result.current.handleSprintChange(999);
    });
    await act(async () => {
      await hook.result.current.handleBoardChange(9);
    });
    expect(hook.result.current.selectedSprint).toBe(301);
  });

  it("handleSprintChange clears the previous insights before loading the next", async () => {
    const hook = render();
    await act(async () => {
      await hook.result.current.handleSprintChange(401);
    });
    // First load landed
    expect(hook.result.current.sprintQuality).toEqual({ score: 1 });
    mocks.getSprintQuality.mockResolvedValue({ score: 2 });
    await act(async () => {
      await hook.result.current.handleSprintChange(402);
    });
    expect(mocks.getSprintQuality).toHaveBeenCalledWith(402);
    expect(hook.result.current.sprintQuality).toEqual({ score: 2 });
  });

  it("resetForProjectSwitch clears selectors and insights", async () => {
    mocks.getBoardsForProject.mockResolvedValue({
      boards: [{ id: 22, type: "scrum", name: "S" }],
    });
    mocks.getProjectSprints.mockResolvedValue({ sprints: [makeSprint(501, "active")] });
    const hook = render();
    await act(async () => {
      await hook.result.current.loadSprintsSection("KEY");
    });
    act(() => {
      hook.result.current.resetForProjectSwitch();
    });
    expect(hook.result.current.boards).toEqual([]);
    expect(hook.result.current.sprints).toEqual([]);
    expect(hook.result.current.boardId).toBe("");
    expect(hook.result.current.selectedSprint).toBe("");
    expect(hook.result.current.sprintBurndown).toBeNull();
  });
});
