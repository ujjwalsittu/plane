/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { describe, expect, it } from "vitest";
import type { TWorkspaceAgentPayload } from "@plane/types";
import { buildUpdatePayload } from "../agent-payload";

const payload: TWorkspaceAgentPayload = {
  name: "Bot",
  description: "",
  avatar_url: "",
  owner: "u1",
  project_ids: ["a", "b"],
  permission: "contribute",
  approval_actions: [],
  run_budget_cents: 500,
};

describe("buildUpdatePayload", () => {
  it("omits project_ids when the selection is unchanged, in any order", () => {
    const body = buildUpdatePayload(payload, ["b", "a"]);
    expect("project_ids" in body).toBe(false);
    expect(body.name).toBe("Bot");
  });

  it("includes project_ids when a project was added or removed", () => {
    expect(buildUpdatePayload(payload, ["a"]).project_ids).toEqual(["a", "b"]);
    expect(buildUpdatePayload(payload, ["a", "b", "c"]).project_ids).toEqual(["a", "b"]);
  });
});
