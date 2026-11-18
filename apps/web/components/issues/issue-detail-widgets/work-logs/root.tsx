/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { EntityDetailWidgetSection } from "@plane/blocks/entity-detail";
import { useTranslation } from "@plane/i18n";
import { renderFormattedDate } from "@plane/utils";
import { useMember } from "@/hooks/store/use-member";
import { useUser } from "@/hooks/store/user";
import { formatDuration } from "./duration";
import { useWorkLogs } from "./use-work-logs";

type Props = { workspaceSlug: string; projectId: string; issueId: string; disabled?: boolean };

/** Time logged on the work item: the total, then each entry (newest first). */
export const WorkLogsCollapsible = observer(function WorkLogsCollapsible(props: Props) {
  const { workspaceSlug, projectId, issueId, disabled = false } = props;
  const { t } = useTranslation();
  const { getUserDetails } = useMember();
  const { data: currentUser } = useUser();
  const [isOpen, setIsOpen] = useState(false);
  const { enabled, logs, total, remove } = useWorkLogs(workspaceSlug, projectId, issueId);

  if (!enabled || logs.length === 0) return null;

  return (
    <EntityDetailWidgetSection
      title={`${t("work_logs.title")} · ${formatDuration(total)}`}
      count={logs.length}
      isOpen={isOpen}
      onToggle={() => setIsOpen((value) => !value)}
    >
      <div className="flex flex-col gap-0.5 py-1">
        {logs.map((entry) => (
          <div key={entry.id} className="group flex items-center gap-3 rounded-md px-2 py-1.5 hover:bg-layer-1">
            <span className="w-16 shrink-0 text-body-xs-medium text-primary">{formatDuration(entry.duration)}</span>
            <span className="min-w-0 flex-1 truncate text-body-xs-regular text-secondary">
              {entry.description || "—"}
            </span>
            <span className="shrink-0 text-caption-md-regular text-tertiary">
              {getUserDetails(entry.logged_by)?.display_name ?? ""} · {renderFormattedDate(entry.created_at ?? "")}
            </span>
            {!disabled && entry.logged_by === currentUser?.id && (
              <button
                type="button"
                className="text-caption-sm-regular text-tertiary opacity-0 group-hover:opacity-100 hover:text-danger-primary focus-visible:opacity-100"
                onClick={() => void remove(entry.id)}
              >
                {t("delete")}
              </button>
            )}
          </div>
        ))}
      </div>
    </EntityDetailWidgetSection>
  );
});
