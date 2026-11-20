/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Badge } from "@makeplane/propel/components/badge";
import { useTranslation } from "@plane/i18n";
import type { TBriefNeedsMe, TDecisionRequest } from "@plane/types";
import { renderFormattedDate } from "@plane/utils";
import { BriefColumn, WorkItemLink } from "./column";
import { DecisionAnswer } from "./decision-answer";

/** Work items waiting on me: decisions to answer, mentions and assignments, most urgent first. */
export function NeedsMeColumn({
  workspaceSlug,
  rows,
  decisions,
  onAnswered,
}: {
  workspaceSlug: string;
  rows: TBriefNeedsMe[];
  decisions: TDecisionRequest[];
  onAnswered: () => void;
}) {
  const { t } = useTranslation();
  const whyLabel = { assigned: "why_assigned", mentioned: "why_mentioned", decision: "why_decision" } as const;
  return (
    <BriefColumn title={t("supervision.needs_me")} count={rows.length} empty={t("supervision.needs_me_empty")}>
      {rows.map((row) => {
        const decision = row.decision_id ? decisions.find((d) => d.id === row.decision_id) : undefined;
        const due = renderFormattedDate(row.due);
        return (
          <div key={row.issue.id} className="flex flex-col gap-2 px-4 py-3">
            <WorkItemLink workspaceSlug={workspaceSlug} issue={row.issue} />
            <div className="flex flex-wrap items-center gap-2">
              <Badge
                variant={row.why === "decision" ? "warning" : "neutral"}
                size="sm"
                label={t(`supervision.${whyLabel[row.why]}`)}
              />
              {row.overdue && <Badge variant="danger" size="sm" label={t("supervision.overdue")} />}
              {due && (
                <span className="text-caption-md-regular text-tertiary">{t("supervision.due", { date: due })}</span>
              )}
            </div>
            {decision && (
              <DecisionAnswer
                workspaceSlug={workspaceSlug}
                projectId={row.issue.project_id}
                issueId={row.issue.id}
                decision={decision}
                onAnswered={onAnswered}
              />
            )}
          </div>
        );
      })}
    </BriefColumn>
  );
}
