/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ReactNode } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import { StateGroupIcon } from "@plane/blocks/icons";
import type { TIssue } from "@plane/types";
import { useProject } from "@/hooks/store/use-project";
import { useProjectState } from "@/hooks/store/use-project-state";

type Props = {
  workspaceSlug: string;
  projectId: string;
  issues: TIssue[];
  /** Extra content at the end of a row, e.g. child progress for an epic. */
  renderTrailing?: (issue: TIssue) => ReactNode;
};

/** A compact list of work items linking to their detail pages. */
export const WorkItemRows = observer(function WorkItemRows(props: Props) {
  const { workspaceSlug, projectId, issues, renderTrailing } = props;
  const { getProjectById } = useProject();
  const { getStateById } = useProjectState();
  const identifier = getProjectById(projectId)?.identifier;

  return (
    <ul className="divide-y divide-subtle">
      {issues.map((issue) => {
        const state = getStateById(issue.state_id);
        return (
          <li key={issue.id} className="flex items-center gap-3 px-page-x py-3">
            <StateGroupIcon stateGroup={state?.group ?? "backlog"} color={state?.color} className="size-4 shrink-0" />
            <Link
              href={`/${workspaceSlug}/projects/${projectId}/issues/${issue.id}`}
              className="flex min-w-0 flex-1 items-center gap-3"
            >
              <span className="shrink-0 text-body-xs-medium text-tertiary">
                {identifier}-{issue.sequence_id}
              </span>
              <span className="truncate text-body-sm-regular text-primary">{issue.name}</span>
            </Link>
            {state && (
              <span className="hidden shrink-0 text-caption-sm-regular text-tertiary sm:inline">{state.name}</span>
            )}
            {renderTrailing?.(issue)}
          </li>
        );
      })}
    </ul>
  );
});
