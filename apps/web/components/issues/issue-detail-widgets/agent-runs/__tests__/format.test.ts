/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { describe, expect, it } from "vitest";
import { formatDuration } from "../format";

describe("formatDuration", () => {
  it.each([
    [0, "0s"],
    [42, "42s"],
    [95, "1m 35s"],
    [3600, "1h 0m"],
    [3700, "1h 1m"],
  ])("%s seconds is %s", (seconds, expected) => {
    expect(formatDuration(seconds)).toBe(expected);
  });
});
