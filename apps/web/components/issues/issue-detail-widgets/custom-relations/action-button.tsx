/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@makeplane/propel/components/menu";
import { Tooltip } from "@makeplane/propel/components/tooltip";
import { ExistingIssuesListModal } from "@/components/core/modals/existing-issues-list-modal";
import { useCustomRelations } from "./use-custom-relations";

type Props = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  customButton: React.ReactElement;
  tooltip?: string;
};

/** Pick a custom relation (e.g. "implements"), then the work items it points to. */
export function CustomRelationActionButton({ workspaceSlug, projectId, issueId, customButton, tooltip }: Props) {
  const { labels, add } = useCustomRelations(workspaceSlug, projectId, issueId);
  const [pending, setPending] = useState<{ definitionId: string; label: string } | null>(null);

  if (labels.length === 0) return null;

  const trigger = <MenuTrigger render={customButton} />;
  return (
    <>
      <Menu>
        {tooltip ? <Tooltip label={tooltip}>{trigger}</Tooltip> : trigger}
        <MenuContent side="bottom" align="start">
          {labels.map((entry) => (
            <MenuItem
              key={`${entry.definitionId}-${entry.label}`}
              label={entry.label}
              onClick={() => setPending(entry)}
            />
          ))}
        </MenuContent>
      </Menu>
      <ExistingIssuesListModal
        workspaceSlug={workspaceSlug}
        projectId={projectId}
        isOpen={!!pending}
        handleClose={() => setPending(null)}
        searchParams={{ issue_id: issueId }}
        workspaceLevelToggle
        shouldHideIssue={(issue) => issue.id === issueId}
        handleOnSubmit={async (issues) => {
          if (pending)
            await add(
              pending.definitionId,
              pending.label,
              issues.map((issue) => issue.id)
            );
          setPending(null);
        }}
      />
    </>
  );
}
