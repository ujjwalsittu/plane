/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useTranslation } from "@plane/i18n";
import type { TBlockedItem } from "@plane/types";
import { BriefColumn, WorkItemLink } from "./column";

/** Open work items that are blocked, waiting on someone or gone stale, with the reasons. */
export function BlockedColumn({ workspaceSlug, rows }: { workspaceSlug: string; rows: TBlockedItem[] }) {
  const { t } = useTranslation();
  return (
    <BriefColumn title={t("supervision.blocked")} count={rows.length} empty={t("supervision.blocked_empty")}>
      {rows.map((row) => (
        <div key={row.issue.id} className="flex flex-col gap-1 px-4 py-3">
          <WorkItemLink workspaceSlug={workspaceSlug} issue={row.issue} />
          <ul className="flex flex-col gap-0.5">
            {row.reasons.map((reason) => (
              <li
                key={`${reason.kind}-${reason.detail}-${reason.since}`}
                className="text-caption-md-regular text-tertiary"
              >
                {t(`supervision.reason_${reason.kind}`, { detail: reason.detail })}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </BriefColumn>
  );
}
