/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { describe, expect, it } from "vitest";
import { formatDuration, parseDuration } from "../duration";

describe("parseDuration", () => {
  it.each([
    ["45", 45],
    ["90m", 90],
    ["1h", 60],
    ["1h 30m", 90],
    ["1h30m", 90],
    ["1.5h", 90],
    ["2 hours", 120],
    ["15 mins", 15],
    [" 2H 5M ", 125],
  ])("%s -> %i minutes", (text, minutes) => {
    expect(parseDuration(text)).toBe(minutes);
  });

  it.each(["", "0", "0m", "abc", "1x", "-5", "h", "1h 30"])("rejects %s", (text) => {
    expect(parseDuration(text)).toBeNull();
  });
});

describe("formatDuration", () => {
  it.each([
    [45, "45m"],
    [60, "1h"],
    [90, "1h 30m"],
    [150, "2h 30m"],
  ])("%i -> %s", (minutes, text) => {
    expect(formatDuration(minutes)).toBe(text);
  });
});
