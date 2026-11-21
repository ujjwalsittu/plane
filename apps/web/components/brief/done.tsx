/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Avatar } from "@makeplane/propel/components/avatar";
import { Badge } from "@makeplane/propel/components/badge";
import { useTranslation } from "@plane/i18n";
import type { TBriefDone } from "@plane/types";
import { getFileURL, renderFormattedDate } from "@plane/utils";
import { useMember } from "@/hooks/store/use-member";
import { BriefColumn, WorkItemLink } from "./column";

/** Work items finished since the last visit, grouped by project, marked as done by an agent or a person. */
export function DoneColumn({ workspaceSlug, groups }: { workspaceSlug: string; groups: TBriefDone[] }) {
  const { t } = useTranslation();
  const { getUserDetails } = useMember();
  const total = groups.reduce((sum, group) => sum + group.items.length, 0);
  return (
    <BriefColumn title={t("supervision.done")} count={total} empty={t("supervision.done_empty")}>
      {groups.map((group) => (
        <div key={group.project_id} className="flex flex-col">
          <div className="flex items-center justify-between bg-layer-1 px-4 py-1.5 text-caption-md-medium text-secondary">
            <span>{group.project_identifier}</span>
            <span className="text-tertiary">{t("supervision.item_count", { count: group.items.length })}</span>
          </div>
          <div className="divide-y divide-subtle">
            {group.items.map((item) => (
              <div key={item.issue.id} className="flex flex-col gap-1 px-4 py-3">
                <WorkItemLink workspaceSlug={workspaceSlug} issue={item.issue} />
                <div className="flex flex-wrap items-center gap-2">
                  <Badge
                    variant={item.by.is_agent ? "purple" : "neutral"}
                    size="sm"
                    label={t(item.by.is_agent ? "supervision.agent" : "supervision.person")}
                  />
                  {item.by.is_agent && item.by.display_name && (
                    <span className="flex items-center gap-1.5 text-caption-md-regular text-secondary">
                      <Avatar
                        size="sm"
                        alt={item.by.display_name}
                        src={getFileURL(getUserDetails(item.by.id ?? "")?.avatar_url ?? "") || undefined}
                        fallback={item.by.display_name[0]?.toUpperCase()}
                      />
                      {item.by.display_name}
                    </span>
                  )}
                  {!item.by.is_agent && item.by.display_name && (
                    <span className="text-caption-md-regular text-tertiary">
                      {t("supervision.done_by", { name: item.by.display_name })}
                    </span>
                  )}
                  <span className="text-caption-md-regular text-tertiary">
                    {renderFormattedDate(item.completed_at)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </BriefColumn>
  );
}
