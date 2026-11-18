/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TProjectPriority, TProjectStatus } from "@plane/types";

export const PROJECT_STATUS_OPTIONS: { key: TProjectStatus; color: string }[] = [
  { key: "backlog", color: "#95999f" },
  { key: "planned", color: "#6d7b8a" },
  { key: "in_progress", color: "#f59e0b" },
  { key: "paused", color: "#e57a00" },
  { key: "completed", color: "#46a758" },
  { key: "cancelled", color: "#9aa4bc" },
];

export const PROJECT_PRIORITY_OPTIONS: TProjectPriority[] = ["urgent", "high", "medium", "low", "none"];

export const getProjectStatusColor = (status: TProjectStatus | undefined) =>
  PROJECT_STATUS_OPTIONS.find((option) => option.key === status)?.color ?? PROJECT_STATUS_OPTIONS[0].color;
