/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import { PagesOutline } from "@makeplane/propel/icons";
import { EntityDetailWidgetSection } from "@plane/blocks/entity-detail";
import { useTranslation } from "@plane/i18n";
import { cn } from "@plane/utils";
import { useWorkItemPages } from "./use-work-item-pages";

type Props = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  disabled?: boolean;
};

/** The work item's linked pages; hidden until at least one page is linked. */
export const WorkItemPagesCollapsible = observer(function WorkItemPagesCollapsible(props: Props) {
  const { workspaceSlug, projectId, issueId, disabled = false } = props;
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(true);
  const { links, unlinkPage } = useWorkItemPages({ workspaceSlug, projectId, issueId });

  if (links.length === 0) return null;

  return (
    <EntityDetailWidgetSection
      title={t("work_item_pages.title")}
      count={links.length}
      isOpen={isOpen}
      onToggle={() => setIsOpen((value) => !value)}
    >
      <div className="flex flex-col gap-0.5 py-1">
        {links.map((link) => (
          <div key={link.id} className="group flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-layer-1">
            <PagesOutline className="size-3.5 shrink-0 text-tertiary" />
            <Link
              href={`/${workspaceSlug}/projects/${projectId}/pages/${link.page.id}`}
              className={cn("min-w-0 flex-1 truncate text-body-xs-medium text-primary", {
                "text-tertiary line-through": !!link.page.archived_at,
              })}
            >
              {link.page.name || t("work_item_pages.untitled")}
            </Link>
            {!disabled && (
              <button
                type="button"
                className="text-caption-sm-regular text-tertiary opacity-0 group-hover:opacity-100 hover:text-danger-primary focus-visible:opacity-100"
                onClick={() => void unlinkPage(link.id)}
              >
                {t("work_item_pages.unlink")}
              </button>
            )}
          </div>
        ))}
      </div>
    </EntityDetailWidgetSection>
  );
});
