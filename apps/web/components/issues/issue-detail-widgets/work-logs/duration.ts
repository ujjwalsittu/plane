/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

/**
 * Minutes from text like "1h 30m", "90m", "1.5h", "2h" or a bare number of minutes ("45").
 * Returns null when the text isn't a positive duration.
 */
export function parseDuration(text: string): number | null {
  const value = text.trim().toLowerCase();
  if (!value) return null;
  if (/^\d+$/.test(value)) {
    const minutes = Number(value);
    return minutes > 0 ? minutes : null;
  }
  const match = /^(?:(\d+(?:\.\d+)?)\s*h(?:ours?|rs?)?)?\s*(?:(\d+)\s*m(?:in(?:utes?|s)?)?)?$/.exec(value);
  if (!match || (!match[1] && !match[2])) return null;
  const minutes = Math.round(Number(match[1] ?? 0) * 60) + Number(match[2] ?? 0);
  return minutes > 0 ? minutes : null;
}

/** "1h 30m", "45m", "2h". */
export function formatDuration(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours && rest) return `${hours}h ${rest}m`;
  return hours ? `${hours}h` : `${rest}m`;
}
