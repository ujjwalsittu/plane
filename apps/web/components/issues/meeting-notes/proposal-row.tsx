/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Checkbox } from "@makeplane/propel/components/checkbox";
import { InputField } from "@makeplane/propel/components/input-field";
import { SelectField } from "@makeplane/propel/components/select-field";
import { useTranslation } from "@plane/i18n";
import type { TMeetingNotesExtract, TMeetingProposal } from "@plane/types";

export type TProposalDraft = TMeetingProposal & { include: boolean; rowId: string };

const PRIORITIES: TMeetingProposal["priority"][] = ["urgent", "high", "medium", "low", "none"];
const UNASSIGNED = "";

type Props = {
  proposal: TProposalDraft;
  members: TMeetingNotesExtract["members"];
  disabled: boolean;
  onChange: (proposal: TProposalDraft) => void;
};

/** One proposed action item: include it or not, and edit its name, assignee, due date and priority. */
export function MeetingProposalRow(props: Props) {
  const { proposal, members, disabled, onChange } = props;
  const { t } = useTranslation();
  const update = (fields: Partial<TProposalDraft>) => onChange({ ...proposal, ...fields });

  const assigneeOptions = [
    { value: UNASSIGNED, label: t("agents.meeting_notes.unassigned") },
    ...members.map((member) => ({ value: member.id, label: member.display_name })),
  ];
  const priorityOptions = PRIORITIES.map((priority) => ({ value: priority, label: t(priority) }));
  const unmatchedHint =
    !proposal.assignee_id && proposal.owner_hint
      ? t("agents.meeting_notes.owner_hint", { name: proposal.owner_hint })
      : undefined;

  return (
    <div className="flex items-start gap-3 rounded-md border border-subtle p-3">
      <div className="pt-2">
        <Checkbox
          aria-label={t("agents.meeting_notes.include")}
          checked={proposal.include}
          disabled={disabled}
          onCheckedChange={(checked) => update({ include: checked === true })}
        />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <InputField
          size="md"
          orientation="vertical"
          aria-label={t("agents.meeting_notes.name")}
          value={proposal.name}
          maxLength={255}
          disabled={disabled || !proposal.include}
          onChange={(e) => update({ name: e.target.value })}
        />
        {proposal.description && (
          <p className="line-clamp-2 text-body-xs-regular text-tertiary">{proposal.description}</p>
        )}
        <div className="flex flex-wrap gap-2">
          <div className="min-w-40 flex-1">
            <SelectField<string>
              size="md"
              aria-label={t("agents.meeting_notes.assignee")}
              options={assigneeOptions}
              value={proposal.assignee_id ?? UNASSIGNED}
              disabled={disabled || !proposal.include}
              hint={unmatchedHint}
              onValueChange={(value) => update({ assignee_id: value ? value : null })}
            />
          </div>
          <div className="min-w-36">
            <InputField
              size="md"
              orientation="vertical"
              type="date"
              aria-label={t("agents.meeting_notes.due")}
              value={proposal.target_date ?? ""}
              disabled={disabled || !proposal.include}
              onChange={(e) => update({ target_date: e.target.value || null })}
            />
          </div>
          <div className="min-w-32">
            <SelectField<TMeetingProposal["priority"]>
              size="md"
              aria-label={t("agents.meeting_notes.priority")}
              options={priorityOptions}
              value={proposal.priority}
              disabled={disabled || !proposal.include}
              onValueChange={(value) => {
                if (value !== null) update({ priority: value });
              }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
