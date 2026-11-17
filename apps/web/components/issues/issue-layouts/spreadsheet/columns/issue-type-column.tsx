/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// types
import type { TIssue } from "@plane/types";
// components
import { IssueTypeSelect } from "@/components/dropdowns/issue-type/issue-type-select";

type Props = {
  issue: TIssue;
  onClose: () => void;
  onChange: (issue: TIssue, data: Partial<TIssue>, updates: any) => void;
  disabled: boolean;
};

export const SpreadsheetIssueTypeColumn = observer(function SpreadsheetIssueTypeColumn(props: Props) {
  const { issue, onChange, disabled, onClose } = props;

  return (
    <div className="h-11 border-b-[0.5px] border-subtle">
      <IssueTypeSelect
        projectId={issue.project_id ?? undefined}
        value={issue.type_id}
        onChange={(typeId) => {
          if (typeId === issue.type_id) return;
          onChange(issue, { type_id: typeId }, { changed_property: "type", change_details: typeId });
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
