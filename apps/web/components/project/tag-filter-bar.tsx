/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useTranslation } from "@plane/i18n";
import type { TProjectTag } from "@plane/types";
import { cn } from "@plane/utils";

type Props = {
  tags: TProjectTag[];
  activeTagId: string | null;
  /** Projects shown before the tag filter, for the per-tag counts. */
  projectIds: string[];
  onChange: (tagId: string | null) => void;
};

const chipClass = (active: boolean) =>
  cn(
    "flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-caption-md-medium transition-colors",
    active
      ? "border-accent-strong bg-accent-subtle text-accent-primary"
      : "border-subtle text-secondary hover:bg-layer-transparent-hover hover:text-primary"
  );

/** One-tap filter for the projects page by project tag. */
export function ProjectTagFilterBar({ tags, activeTagId, projectIds, onChange }: Props) {
  const { t } = useTranslation();
  const visible = new Set(projectIds);

  return (
    <div
      role="toolbar"
      aria-label={t("project_overview.filter_by_tag")}
      className="horizontal-scrollbar mb-6 scrollbar-sm flex items-center gap-2 overflow-x-auto pb-1"
    >
      <button
        type="button"
        aria-pressed={!activeTagId}
        className={chipClass(!activeTagId)}
        onClick={() => onChange(null)}
      >
        {t("project_overview.all_projects")}
      </button>
      {tags.map((tag) => {
        const count = (tag.project_ids ?? []).filter((id) => visible.has(id)).length;
        const active = tag.id === activeTagId;
        return (
          <button
            key={tag.id}
            type="button"
            aria-pressed={active}
            className={chipClass(active)}
            onClick={() => onChange(active ? null : tag.id)}
          >
            {tag.color && <span className="size-2 rounded-full" style={{ backgroundColor: tag.color }} />}
            {tag.name}
            <span className="text-tertiary">{count}</span>
          </button>
        );
      })}
    </div>
  );
}
