/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import Link from "next/link";
import { useTranslation } from "@plane/i18n";
import type { TBriefProject, TProjectHealth } from "@plane/types";
import { renderFormattedDate } from "@plane/utils";

const HEALTH_STYLE: Record<TProjectHealth, string> = {
  on_track: "bg-green-500/10 text-green-600",
  at_risk: "bg-yellow-500/10 text-yellow-600",
  off_track: "bg-red-500/10 text-red-600",
};

/** One compact card per project: health, predicted finish against the target, and the latest update. */
export function ProjectsStrip({ workspaceSlug, projects }: { workspaceSlug: string; projects: TBriefProject[] }) {
  const { t } = useTranslation();
  if (!projects || projects.length === 0) return null;
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-body-sm-medium text-primary">{t("supervision.projects")}</h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {projects.map((project) => {
          const finish = renderFormattedDate(project.predicted_finish);
          const target = renderFormattedDate(project.target_date);
          const update = project.latest_update;
          return (
            <Link
              key={project.id}
              href={`/${workspaceSlug}/projects/${project.id}/issues/`}
              className="flex flex-col gap-1 rounded-lg border border-subtle px-4 py-3 hover:bg-layer-transparent-hover"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-body-sm-medium text-primary">
                  {project.identifier} · {project.name}
                </span>
                <span
                  className={`shrink-0 rounded-full px-2 py-0.5 text-caption-md-medium ${HEALTH_STYLE[project.health]}`}
                >
                  {t(`supervision.health_${project.health}`)}
                </span>
              </div>
              <span className="text-caption-md-regular text-secondary">
                {finish ? t("supervision.project_finish", { date: finish }) : t("supervision.project_finish_unknown")}
                {target && ` · ${t("supervision.project_target", { date: target })}`}
              </span>
              <span className="line-clamp-2 text-caption-md-regular text-tertiary">
                {update
                  ? `${update.by.display_name ?? ""} (${update.by.is_agent ? t("supervision.agent") : t("supervision.person")}): ${update.excerpt}`
                  : t("supervision.project_no_update")}
              </span>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
