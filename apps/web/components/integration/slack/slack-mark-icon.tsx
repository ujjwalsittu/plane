/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ISvgIcons } from "@plane/blocks/icons";

/** A hash mark in the current text color, standing in for Slack. */
export function SlackMarkIcon({ className, ...rest }: ISvgIcons) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      aria-hidden="true"
      className={className}
      {...rest}
    >
      <path d="M6 2 5 14M11 2l-1 12M2.5 6h11M2 10h11" />
    </svg>
  );
}
