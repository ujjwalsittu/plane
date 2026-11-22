/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TWorkspaceAgentPayload } from "@plane/types";

const sameIds = (a: string[], b: string[]) => a.length === b.length && new Set([...a, ...b]).size === a.length;

/**
 * The body for editing an agent. `project_ids` is sent only when the selection changed, so renaming an
 * agent does not touch projects the editor cannot see.
 */
export const buildUpdatePayload = (
  payload: TWorkspaceAgentPayload,
  originalProjectIds: string[]
): Partial<TWorkspaceAgentPayload> => {
  if (sameIds(payload.project_ids, originalProjectIds)) {
    const { project_ids: _unchanged, ...rest } = payload;
    return rest;
  }
  return payload;
};
