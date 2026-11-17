/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import useSWR from "swr";
import { LinearProgress } from "@makeplane/propel/components/linear-progress";
import { EmptyStateCompact } from "@plane/blocks/empty-state";
import { useTranslation } from "@plane/i18n";
import { cn, renderFormattedDate } from "@plane/utils";
import { useMilestone } from "@/hooks/store/use-milestone";
import { MilestoneService } from "@/services/milestone.service";
import { getMilestoneProgress, isMilestoneOverdue, MilestoneStatusIcon } from "./milestones-list";
import { WorkItemRows } from "./work-item-rows";

const milestoneService = new MilestoneService();

type Props = {
  workspaceSlug: string;
  projectId: string;
  milestoneId: string;
};

export const MilestoneDetail = observer(function MilestoneDetail(props: Props) {
  const { workspaceSlug, projectId, milestoneId } = props;
  const { t } = useTranslation();
  const { getMilestoneById, fetchMilestone } = useMilestone();

  useSWR(`MILESTONE_${milestoneId}`, () => fetchMilestone(workspaceSlug, projectId, milestoneId));
  const { data: issues } = useSWR(`MILESTONE_ISSUES_${milestoneId}`, () =>
    milestoneService.listIssues(workspaceSlug, projectId, { milestone: milestoneId })
  );
  const milestone = getMilestoneById(milestoneId);
  if (!milestone) return null;

  const progress = getMilestoneProgress(milestone);
  const overdue = isMilestoneOverdue(milestone);

  return (
    <div className="flex flex-col">
      <section className="flex flex-col gap-4 border-b border-subtle px-page-x py-6">
        <div className="flex items-start gap-3">
          <MilestoneStatusIcon status={progress.status} className="mt-0.5 size-6 shrink-0" />
          <div className="min-w-0">
            <h1 className="text-h4-semibold text-primary">{milestone.title}</h1>
            <p className={cn("text-body-xs-regular text-tertiary", { "text-danger-primary": overdue })}>
              {milestone.target_date
                ? `${t("milestones_feature.fields.target_date")}: ${renderFormattedDate(milestone.target_date)}${overdue ? ` · ${t("milestones_feature.overdue")}` : ""}`
                : t("milestones_feature.fields.no_target_date")}
            </p>
          </div>
        </div>
        {milestone.description && (
          <p className="max-w-3xl text-body-sm-regular whitespace-pre-line text-secondary">{milestone.description}</p>
        )}
        <div className="flex max-w-md flex-col gap-1">
          <LinearProgress
            value={progress.percent}
            size="md"
            variant={progress.status === "done" ? "success" : "brand"}
            aria-label={t("milestones_feature.progress", { completed: progress.completed, total: progress.total })}
          />
          <span className="text-caption-sm-regular text-tertiary">
            {t("milestones_feature.progress", { completed: progress.completed, total: progress.total })}
          </span>
        </div>
      </section>
      {issues && issues.length === 0 ? (
        <EmptyStateCompact
          assetKey="work-item"
          title={t("milestones_feature.detail.no_items")}
          rootClassName="h-auto py-12"
        />
      ) : (
        <WorkItemRows workspaceSlug={workspaceSlug} projectId={projectId} issues={issues ?? []} />
      )}
    </div>
  );
});
