/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useTranslation } from "@plane/i18n";
import type { TBriefMilestone } from "@plane/types";
import { renderFormattedDate } from "@plane/utils";

/** Milestones due within the week (or already overdue) that still have open work. */
export function MilestonesDue({ milestones }: { milestones: TBriefMilestone[] }) {
  const { t } = useTranslation();
  if (milestones.length === 0) return null;
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-body-sm-medium text-primary">{t("supervision.milestones_due")}</h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {milestones.map((milestone) => (
          <div key={milestone.id} className="flex flex-col gap-1 rounded-lg border border-subtle px-4 py-3">
            <span className="truncate text-body-sm-medium text-primary">{milestone.title}</span>
            <span className="text-caption-md-regular text-tertiary">
              {milestone.project_identifier} · {renderFormattedDate(milestone.target_date)}
            </span>
            <span className="text-caption-md-regular text-secondary">
              {t("supervision.milestone_open", { count: milestone.open })}
              {milestone.assigned_to_me_open > 0 &&
                ` · ${t("supervision.milestone_mine", { count: milestone.assigned_to_me_open })}`}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
