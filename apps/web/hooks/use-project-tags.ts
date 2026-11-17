/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useMemo } from "react";
import useSWR from "swr";
import type { TProjectTag } from "@plane/types";
import { MilestoneService } from "@/services/milestone.service";

const milestoneService = new MilestoneService();

/** SWR key shared with the project overview, so tag edits there refresh the projects page. */
export const getProjectTagsKey = (workspaceSlug: string) => `PROJECT_TAGS_${workspaceSlug}`;

/** The workspace's project tags, and a lookup from project to its tags. */
export const useProjectTags = (workspaceSlug: string | undefined) => {
  const { data: tags } = useSWR(workspaceSlug ? getProjectTagsKey(workspaceSlug) : null, () =>
    milestoneService.listProjectTags(workspaceSlug ?? "")
  );

  const tagsByProject = useMemo(() => {
    const map = new Map<string, TProjectTag[]>();
    for (const tag of tags ?? []) {
      for (const projectId of tag.project_ids ?? []) {
        map.set(projectId, [...(map.get(projectId) ?? []), tag]);
      }
    }
    return map;
  }, [tags]);

  const getProjectTags = useCallback((projectId: string) => tagsByProject.get(projectId) ?? [], [tagsByProject]);

  return { tags: tags ?? [], getProjectTags };
};
