/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { describe, expect, it, vi } from "vitest";
import type { TIssueType, TMilestone } from "@plane/types";
import { MilestoneStore } from "@/store/milestone.store";
import type { CoreRootStore } from "@/store/root.store";

const milestone = (id: string, sortOrder: number): TMilestone =>
  ({ id, title: id.toUpperCase(), sort_order: sortOrder, target_date: null, created_at: "2026-01-01" }) as TMilestone;

const createStore = () => new MilestoneStore({} as CoreRootStore);

describe("MilestoneStore.ensureMilestones", () => {
  it("shares one request between concurrent callers and skips loaded projects", async () => {
    const store = createStore();
    const list = vi.spyOn(store.service, "list").mockResolvedValue([milestone("m2", 2), milestone("m1", 1)]);

    await Promise.all([store.ensureMilestones("ws", "p1"), store.ensureMilestones("ws", "p1")]);
    await store.ensureMilestones("ws", "p1");

    expect(list).toHaveBeenCalledTimes(1);
    expect(store.getMilestoneById("m1")?.title).toBe("M1");
    expect(store.getProjectMilestones("p1")?.map((m) => m.id)).toEqual(["m1", "m2"]);
  });

  it("retries after a failed load", async () => {
    const store = createStore();
    const list = vi
      .spyOn(store.service, "list")
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce([milestone("m1", 1)]);

    await expect(store.ensureMilestones("ws", "p1")).rejects.toThrow("offline");
    await store.ensureMilestones("ws", "p1");

    expect(list).toHaveBeenCalledTimes(2);
    expect(store.getMilestoneById("m1")).toBeDefined();
  });
});

describe("MilestoneStore.ensureIssueTypes", () => {
  it("loads a project's types once and finds epic types", async () => {
    const store = createStore();
    const types = [
      { id: "t1", name: "Task", is_epic: false },
      { id: "t2", name: "Epic", is_epic: true },
    ] as TIssueType[];
    const listTypes = vi.spyOn(store.service, "listIssueTypes").mockResolvedValue(types);

    await Promise.all([store.ensureIssueTypes("ws", "p1"), store.ensureIssueTypes("ws", "p1")]);

    expect(listTypes).toHaveBeenCalledTimes(1);
    expect(store.getIssueTypeById("t2")?.name).toBe("Epic");
    expect(store.getProjectEpicTypeIds("p1")).toEqual(["t2"]);
  });
});
