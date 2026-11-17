/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import useSWR from "swr";
import { Button } from "@makeplane/propel/components/button";
import { LinearProgress } from "@makeplane/propel/components/linear-progress";
import { MilestoneDone, MilestoneInProgress, MilestoneNotStarted } from "@makeplane/propel/icons";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { EmptyStateCompact } from "@plane/blocks/empty-state";
import { setToast } from "@plane/blocks/toast";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import type { TMilestone } from "@plane/types";
import { cn, renderFormattedDate } from "@plane/utils";
import { useMilestone } from "@/hooks/store/use-milestone";
import { useUserPermissions } from "@/hooks/store/user";
import { MilestoneModal } from "./milestone-modal";

/** Done = everything finished; in progress = anything started or finished. */
export const getMilestoneProgress = (milestone: TMilestone) => {
  const total = Math.max(milestone.total_issues - milestone.cancelled_issues, 0);
  const completed = milestone.completed_issues;
  const percent = total > 0 ? Math.round((completed / total) * 100) : 0;
  const status: "done" | "in_progress" | "not_started" =
    total > 0 && completed >= total
      ? "done"
      : completed > 0 || milestone.started_issues > 0
        ? "in_progress"
        : "not_started";
  return { total, completed, percent, status };
};

export function MilestoneStatusIcon({ status, className }: { status: string; className?: string }) {
  if (status === "done") return <MilestoneDone className={className} />;
  if (status === "in_progress") return <MilestoneInProgress className={className} />;
  return <MilestoneNotStarted className={className} />;
}

export const isMilestoneOverdue = (milestone: TMilestone) => {
  if (!milestone.target_date) return false;
  const today = new Date().toISOString().slice(0, 10);
  return milestone.target_date < today && getMilestoneProgress(milestone).status !== "done";
};

type Props = {
  workspaceSlug: string;
  projectId: string;
  isCreateOpen: boolean;
  onCreateClose: () => void;
};

export const MilestonesList = observer(function MilestonesList(props: Props) {
  const { workspaceSlug, projectId, isCreateOpen, onCreateClose } = props;
  const { t } = useTranslation();
  const { getProjectMilestones, fetchMilestones, deleteMilestone } = useMilestone();
  const { allowPermissions } = useUserPermissions();
  // state
  const [editing, setEditing] = useState<TMilestone | undefined>();
  const [toDelete, setToDelete] = useState<TMilestone | undefined>();
  const [isDeleting, setIsDeleting] = useState(false);

  // Refetch on visit so progress counts reflect recent work item changes.
  const { isLoading } = useSWR(`PROJECT_MILESTONES_PAGE_${projectId}`, () => fetchMilestones(workspaceSlug, projectId));
  const milestones = getProjectMilestones(projectId);
  const canEdit = allowPermissions([EUserPermissions.ADMIN, EUserPermissions.MEMBER], EUserPermissionsLevel.PROJECT);

  const handleDelete = async () => {
    if (!toDelete) return;
    setIsDeleting(true);
    try {
      await deleteMilestone(workspaceSlug, projectId, toDelete.id);
      setToast({ type: "success", title: t("milestones_feature.toast.deleted") });
      setToDelete(undefined);
    } catch {
      setToast({ type: "error", title: t("milestones_feature.toast.error") });
    } finally {
      setIsDeleting(false);
    }
  };

  const modals = (
    <>
      <MilestoneModal
        isOpen={isCreateOpen || !!editing}
        onClose={() => {
          setEditing(undefined);
          onCreateClose();
        }}
        workspaceSlug={workspaceSlug}
        projectId={projectId}
        milestone={editing}
      />
      <ConfirmDialog
        isOpen={!!toDelete}
        handleClose={() => setToDelete(undefined)}
        handleSubmit={handleDelete}
        isSubmitting={isDeleting}
        title={t("milestones_feature.delete.title")}
        content={t("milestones_feature.delete.description", { title: toDelete?.title ?? "" })}
      />
    </>
  );

  if (!milestones && isLoading) return null;

  if (!milestones || milestones.length === 0)
    return (
      <>
        <EmptyStateCompact
          assetKey="milestone"
          title={t("milestones_feature.empty.title")}
          description={t("milestones_feature.empty.description")}
          rootClassName="h-auto py-16"
        />
        {modals}
      </>
    );

  return (
    <>
      <ul className="divide-y divide-subtle">
        {milestones.map((milestone) => {
          const progress = getMilestoneProgress(milestone);
          const overdue = isMilestoneOverdue(milestone);
          return (
            <li key={milestone.id} className="flex flex-wrap items-center gap-x-6 gap-y-2 px-page-x py-4">
              <Link
                href={`/${workspaceSlug}/projects/${projectId}/milestones/${milestone.id}`}
                className="flex min-w-0 flex-1 items-center gap-3"
              >
                <MilestoneStatusIcon status={progress.status} className="size-5 shrink-0" />
                <div className="min-w-0">
                  <p className="truncate text-body-sm-medium text-primary">{milestone.title}</p>
                  <p className={cn("text-caption-sm-regular text-tertiary", { "text-danger-primary": overdue })}>
                    {milestone.target_date
                      ? `${renderFormattedDate(milestone.target_date)}${overdue ? ` · ${t("milestones_feature.overdue")}` : ""}`
                      : t("milestones_feature.fields.no_target_date")}
                  </p>
                </div>
              </Link>
              <div className="flex w-56 shrink-0 flex-col gap-1">
                <LinearProgress
                  value={progress.percent}
                  size="sm"
                  variant={progress.status === "done" ? "success" : "brand"}
                  aria-label={t("milestones_feature.progress", {
                    completed: progress.completed,
                    total: progress.total,
                  })}
                />
                <span className="text-caption-sm-regular text-tertiary">
                  {t("milestones_feature.progress", { completed: progress.completed, total: progress.total })}
                </span>
              </div>
              {canEdit && (
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    stretch="auto"
                    label={t("common.edit")}
                    onClick={() => setEditing(milestone)}
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    stretch="auto"
                    label={t("common.delete")}
                    onClick={() => setToDelete(milestone)}
                  />
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {modals}
    </>
  );
});
