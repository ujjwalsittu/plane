/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { describe, expect, it, vi } from "vitest";
import type { TIssue } from "@plane/types";
import { EIssueServiceType } from "@plane/types";
import { IssueStore } from "@/store/issue/issue-details/issue.store";
import type { IIssueDetail } from "@/store/issue/issue-details/root.store";

describe("IssueStore.addIssueToStore", () => {
  it("keeps the milestone and type from the detail response", () => {
    const addIssue = vi.fn();
    const root = { rootIssueStore: { issues: { addIssue } } } as unknown as IIssueDetail;
    const store = new IssueStore(root, EIssueServiceType.ISSUES);

    const payload = store.addIssueToStore({
      id: "i1",
      name: "Migrate",
      project_id: "p1",
      milestone_id: "m3",
      type_id: "epic",
    } as TIssue);

    expect(payload.milestone_id).toBe("m3");
    expect(payload.type_id).toBe("epic");
    expect(addIssue).toHaveBeenCalledWith([expect.objectContaining({ milestone_id: "m3", type_id: "epic" })]);
  });
});
