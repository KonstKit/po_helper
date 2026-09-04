
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

const mocks = vi.hoisted(() => ({
  updateProject: vi.fn(),
  listPullRequests: vi.fn(),
  evaluateQualityGateAndCheck: vi.fn(),
  getQualityHistory: vi.fn(),
}));

vi.mock("../../../services/api", () => ({
  updateProject: mocks.updateProject,
  listPullRequests: mocks.listPullRequests,
  evaluateQualityGateAndCheck: mocks.evaluateQualityGateAndCheck,
  getQualityHistory: mocks.getQualityHistory,
}));

import { useQualityControl } from "../useQualityControl";

describe("useQualityControl", () => {
  const showToast = vi.fn();
  const logNonFatal = vi.fn();

  const render = (projectId: string | undefined = "1") =>
    renderHook(
      (props: { projectId: string | undefined }) =>
        useQualityControl({ projectId: props.projectId, showToast, logNonFatal }),
      { initialProps: { projectId } },
    );

  beforeEach(() => {
    vi.resetAllMocks();
    mocks.updateProject.mockResolvedValue({});
    mocks.evaluateQualityGateAndCheck.mockResolvedValue({});
    mocks.getQualityHistory.mockResolvedValue({ history: [{ id: 1 }] });
  });

  it("applyThresholds maps numeric thresholds and blanks the rest", () => {
    const hook = render();
    act(() => {
      hook.result.current.applyThresholds({ min_line: 60, min_branch: undefined });
    });
    expect(hook.result.current.thresholds).toEqual({ min_line: 60, min_branch: "" });
    act(() => {
      hook.result.current.applyThresholds({});
    });
    expect(hook.result.current.thresholds).toEqual({ min_line: "", min_branch: "" });
  });

  it("handleSaveThresholds sends undefined for blank fields", async () => {
    const hook = render();
    act(() => {
      hook.result.current.applyThresholds({ min_line: 60 });
    });
    await act(async () => {
      await hook.result.current.handleSaveThresholds();
    });
    expect(mocks.updateProject).toHaveBeenCalledWith(1, {
      quality_thresholds: { min_line: 60, min_branch: undefined },
    });
    expect(showToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: "success", msg: "Thresholds saved" }),
    );
    expect(hook.result.current.qualityLoading).toBe(false);
  });

  it("handleSaveThresholds reports failures", async () => {
    mocks.updateProject.mockRejectedValue(new Error("nope"));
    const hook = render();
    await act(async () => {
      await hook.result.current.handleSaveThresholds();
    });
    expect(showToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: "error" }),
    );
  });

  it("handleBulkQualityCheck evaluates every PR and refreshes history", async () => {
    mocks.listPullRequests.mockResolvedValue({
      pull_requests: [
        { number: 10, provider: "github" },
        { number: 11, provider: null },
      ],
    });
    const hook = render();
    await act(async () => {
      await hook.result.current.handleBulkQualityCheck();
    });
    expect(mocks.evaluateQualityGateAndCheck).toHaveBeenCalledTimes(2);
    expect(mocks.evaluateQualityGateAndCheck).toHaveBeenCalledWith(
      expect.objectContaining({ prNumber: 10, projectId: 1 }),
    );
    expect(mocks.getQualityHistory).toHaveBeenCalledWith({ projectId: 1, limit: 20 });
    expect(hook.result.current.hist).toEqual([{ id: 1 }]);
    expect(hook.result.current.bulkProgress).toEqual({
      active: false,
      percent: 100,
      step: "Done",
    });
  });

  it("handleBulkQualityCheck continues past per-PR failures", async () => {
    mocks.listPullRequests.mockResolvedValue({
      pull_requests: [{ number: 10, provider: "github" }],
    });
    mocks.evaluateQualityGateAndCheck.mockRejectedValue(new Error("pr down"));
    const hook = render();
    await act(async () => {
      await hook.result.current.handleBulkQualityCheck();
    });
    expect(logNonFatal).toHaveBeenCalled();
    expect(hook.result.current.bulkProgress.step).toBe("Done");
  });

  it("loadQualityHistory stores the history", async () => {
    const hook = render();
    await act(async () => {
      await hook.result.current.loadQualityHistory();
    });
    expect(hook.result.current.hist).toEqual([{ id: 1 }]);
  });
});
