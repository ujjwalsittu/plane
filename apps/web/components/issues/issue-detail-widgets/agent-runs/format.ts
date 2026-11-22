/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

/** 95 -> "1m 35s", 3700 -> "1h 1m". */
export const formatDuration = (seconds: number): string => {
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${Math.round(seconds % 60)}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
};

const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled"]);

/** True when a run just moved from live to terminal, so its final steps need one more fetch. */
export const turnedTerminal = (previous: string | undefined, next: string): boolean =>
  previous !== undefined && previous !== next && TERMINAL_STATUSES.has(next);
