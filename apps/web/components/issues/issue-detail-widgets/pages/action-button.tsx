/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@makeplane/propel/components/menu";
import { Tooltip } from "@makeplane/propel/components/tooltip";
import { useTranslation } from "@plane/i18n";
import { useWorkItemPages } from "./use-work-item-pages";

type Props = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  /** The trigger, e.g. a toolbar icon button. */
  customButton: React.ReactElement;
  tooltip?: string;
  disabled?: boolean;
};

/** Menu of the project's pages; picking one links it to the work item. */
export const WorkItemPagesActionButton = observer(function WorkItemPagesActionButton(props: Props) {
  const { workspaceSlug, projectId, issueId, customButton, tooltip, disabled = false } = props;
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const { linkablePages, linkPage } = useWorkItemPages({ workspaceSlug, projectId, issueId, loadLinkable: isOpen });

  if (disabled) return null;

  const trigger = <MenuTrigger render={customButton} />;

  return (
    <Menu open={isOpen} onOpenChange={setIsOpen}>
      {tooltip ? <Tooltip label={tooltip}>{trigger}</Tooltip> : trigger}
      <MenuContent side="bottom" align="start">
        {linkablePages.length === 0 && (
          <MenuItem label={t("work_item_pages.no_pages_to_link")} disabled onClick={() => undefined} />
        )}
        {linkablePages.map((page) => (
          <MenuItem
            key={page.id}
            label={page.name || t("work_item_pages.untitled")}
            onClick={() => void linkPage(page.id!)}
          />
        ))}
      </MenuContent>
    </Menu>
  );
});
