/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
import { LinearProgress } from "@makeplane/propel/components/linear-progress";
import { EmptyStateCompact } from "@plane/blocks/empty-state";
import { useTranslation } from "@plane/i18n";
import type { TIssue } from "@plane/types";
import { useMilestone } from "@/hooks/store/use-milestone";
import { useProjectState } from "@/hooks/store/use-project-state";
import { MilestoneService } from "@/services/milestone.service";
import { WorkItemRows } from "./work-item-rows";

const milestoneService = new MilestoneService();

type Props = {
  workspaceSlug: string;
  projectId: string;
};

export const EpicsView = observer(function EpicsView(props: Props) {
  const { workspaceSlug, projectId } = props;
  const { t } = useTranslation();
  const { getProjectEpicTypeIds, getProjectIssueTypes } = useMilestone();
  const { getStateById } = useProjectState();

  const epicTypeIds = getProjectEpicTypeIds(projectId);
  const typesLoaded = getProjectIssueTypes(projectId) !== undefined;
  const epicKey = epicTypeIds.join(",");

  const { data: epics } = useSWR(epicKey ? `PROJECT_EPICS_${projectId}_${epicKey}` : null, () =>
    milestoneService.listIssues(workspaceSlug, projectId, { issue_type: epicKey })
  );
  const epicIds = (epics ?? []).map((epic) => epic.id).join(",");
  const { data: children } = useSWR(epicIds ? `PROJECT_EPIC_CHILDREN_${projectId}_${epicIds}` : null, () =>
    milestoneService.listIssues(workspaceSlug, projectId, { parent: epicIds })
  );

  // completed / (total - cancelled), per epic
  const rollUp = useMemo(() => {
    const byParent: Record<string, { total: number; completed: number }> = {};
    (children ?? []).forEach((child: TIssue) => {
      if (!child.parent_id) return;
      const group = getStateById(child.state_id)?.group;
      if (group === "cancelled") return;
      const entry = (byParent[child.parent_id] ??= { total: 0, completed: 0 });
      entry.total += 1;
      if (group === "completed") entry.completed += 1;
    });
    return byParent;
  }, [children, getStateById]);

  if (typesLoaded && epicTypeIds.length === 0)
    return (
      <EmptyStateCompact
        assetKey="epic"
        title={t("epics_feature.no_epic_type.title")}
        description={t("epics_feature.no_epic_type.description")}
        rootClassName="h-auto py-16"
      />
    );

  if (epics && epics.length === 0)
    return (
      <EmptyStateCompact
        assetKey="epic"
        title={t("epics_feature.empty.title")}
        description={t("epics_feature.empty.description")}
        rootClassName="h-auto py-16"
      />
    );

  return (
    <WorkItemRows
      workspaceSlug={workspaceSlug}
      projectId={projectId}
      issues={epics ?? []}
      renderTrailing={(epic) => {
        const entry = rollUp[epic.id];
        if (!entry || entry.total === 0)
          return (
            <span className="w-48 shrink-0 text-caption-sm-regular text-tertiary">
              {t("epics_feature.no_children")}
            </span>
          );
        const percent = Math.round((entry.completed / entry.total) * 100);
        const label = t("epics_feature.children_progress", { completed: entry.completed, total: entry.total });
        return (
          <div className="flex w-48 shrink-0 flex-col gap-1">
            <LinearProgress
              value={percent}
              size="sm"
              variant={percent === 100 ? "success" : "brand"}
              aria-label={label}
            />
            <span className="text-caption-sm-regular text-tertiary">{label}</span>
          </div>
        );
      }}
    />
  );
});
