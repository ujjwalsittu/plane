/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// types
import type { TIssue } from "@plane/types";
// components
import { MilestoneSelect } from "@/components/dropdowns/milestone/milestone-select";

type Props = {
  issue: TIssue;
  onClose: () => void;
  onChange: (issue: TIssue, data: Partial<TIssue>, updates: any) => void;
  disabled: boolean;
};

export const SpreadsheetMilestoneColumn = observer(function SpreadsheetMilestoneColumn(props: Props) {
  const { issue, onChange, disabled, onClose } = props;

  return (
    <div className="h-11 border-b-[0.5px] border-subtle">
      <MilestoneSelect
        projectId={issue.project_id ?? undefined}
        value={issue.milestone_id}
        onChange={(milestoneId) => {
          if (milestoneId === (issue.milestone_id ?? null)) return;
          onChange(
            issue,
            { milestone_id: milestoneId },
            { changed_property: "milestone", change_details: milestoneId }
          );
        }}
        disabled={disabled}
        // `.clickable` is what the table's keyboard navigation clicks on Enter / Space in a focused cell.
        className="clickable"
        variant="table-cell"
        onClose={onClose}
        tooltip
      />
    </div>
  );
});
