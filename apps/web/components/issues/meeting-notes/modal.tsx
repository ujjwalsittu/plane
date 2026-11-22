/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { Button } from "@makeplane/propel/components/button";
import {
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogHeading,
  DialogMain,
  DialogTitle,
} from "@makeplane/propel/components/dialog";
import { InputField } from "@makeplane/propel/components/input-field";
import { TextAreaField } from "@makeplane/propel/components/text-area-field";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { TMeetingNotesExtract } from "@plane/types";
import { SupervisionService } from "@/services/supervision.service";
import { MeetingProposalRow } from "./proposal-row";
import type { TProposalDraft } from "./proposal-row";

const service = new SupervisionService();

const MIN_TEXT = 20;
const MAX_TEXT = 50000;
/** Propel's toast shows at most three actions. */
const MAX_TOAST_LINKS = 3;

const pad = (value: number) => String(value).padStart(2, "0");

const today = () => {
  const now = new Date();
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
};

const errorText = (error: unknown, fallback: string) => (error as { error?: string } | undefined)?.error ?? fallback;

type Props = {
  isOpen: boolean;
  workspaceSlug: string;
  projectId: string;
  onClose: () => void;
  /** Called after the work items were created, to refresh the list. */
  onCreated: () => void;
};

/** Paste meeting notes, let Claude propose action items, edit them and accept which become work items. */
export function MeetingNotesModal(props: Props) {
  const { isOpen, workspaceSlug, projectId, onClose, onCreated } = props;
  const { t } = useTranslation();
  const [title, setTitle] = useState("");
  const [meetingDate, setMeetingDate] = useState(today);
  const [text, setText] = useState("");
  const [proposals, setProposals] = useState<TProposalDraft[] | null>(null);
  const [members, setMembers] = useState<TMeetingNotesExtract["members"]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setTitle("");
    setMeetingDate(today());
    setText("");
    setProposals(null);
    setMembers([]);
    setError(null);
  };

  const close = () => {
    if (busy) return;
    reset();
    onClose();
  };

  const accepted = (proposals ?? []).filter((proposal) => proposal.include);
  const canCreate = accepted.length > 0 && accepted.every((proposal) => proposal.name.trim().length > 0);
  const textLength = text.trim().length;

  const find = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await service.extractMeetingNotes(workspaceSlug, projectId, {
        text,
        title,
        meeting_date: meetingDate || null,
      });
      setMembers(result.members);
      setProposals(result.items.map((item, index) => Object.assign(item, { include: true, rowId: `row-${index}` })));
    } catch (e) {
      setError(errorText(e, t("agents.meeting_notes.error")));
    } finally {
      setBusy(false);
    }
  };

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const created = await service.createFromMeetingNotes(workspaceSlug, projectId, {
        items: accepted.map(({ include: _include, rowId: _rowId, ...item }) => ({ ...item, name: item.name.trim() })),
        title,
        meeting_date: meetingDate || null,
      });
      const identifiers = created.map((item) => `${item.project_identifier}-${item.sequence_id}`);
      setToast({
        type: "success",
        title: t("agents.meeting_notes.created", { count: created.length }),
        message: identifiers.join(", "),
        actionItems: identifiers.slice(0, MAX_TOAST_LINKS).map((identifier) => ({
          label: identifier,
          href: `/${workspaceSlug}/browse/${identifier}/`,
        })),
      });
      setBusy(false);
      reset();
      onCreated();
      onClose();
    } catch (e) {
      setError(errorText(e, t("agents.meeting_notes.create_error")));
      setBusy(false);
    }
  };

  const updateProposal = (index: number, proposal: TProposalDraft) =>
    setProposals((current) => (current ?? []).map((row, position) => (position === index ? proposal : row)));

  return (
    <Dialog
      open={isOpen}
      disablePointerDismissal
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <DialogContent size="lg">
        <DialogMain>
          <DialogHeader>
            <DialogHeading>
              <DialogTitle>{t("agents.meeting_notes.title")}</DialogTitle>
              <DialogDescription>{t("agents.meeting_notes.description")}</DialogDescription>
            </DialogHeading>
          </DialogHeader>
          <DialogBody>
            <div className="flex flex-col gap-4">
              {proposals === null ? (
                <>
                  <div className="flex flex-wrap gap-3">
                    <div className="min-w-60 flex-1">
                      <InputField
                        size="md"
                        orientation="vertical"
                        label={t("agents.meeting_notes.meeting_title")}
                        value={title}
                        maxLength={255}
                        disabled={busy}
                        onChange={(e) => setTitle(e.target.value)}
                      />
                    </div>
                    <div className="min-w-40">
                      <InputField
                        size="md"
                        orientation="vertical"
                        type="date"
                        label={t("agents.meeting_notes.meeting_date")}
                        value={meetingDate}
                        disabled={busy}
                        onChange={(e) => setMeetingDate(e.target.value)}
                      />
                    </div>
                  </div>
                  <TextAreaField
                    size="xl"
                    label={t("agents.meeting_notes.notes")}
                    placeholder={t("agents.meeting_notes.notes_placeholder")}
                    value={text}
                    maxLength={MAX_TEXT}
                    rows={14}
                    disabled={busy}
                    onChange={(e) => setText(e.target.value)}
                  />
                </>
              ) : proposals.length === 0 ? (
                <p className="text-body-sm-regular text-tertiary">{t("agents.meeting_notes.none")}</p>
              ) : (
                proposals.map((proposal, index) => (
                  <MeetingProposalRow
                    key={proposal.rowId}
                    proposal={proposal}
                    members={members}
                    disabled={busy}
                    onChange={(next) => updateProposal(index, next)}
                  />
                ))
              )}
              {error && <p className="text-body-xs-regular text-danger-primary">{error}</p>}
            </div>
          </DialogBody>
        </DialogMain>
        <DialogActions>
          {proposals === null ? (
            <>
              <Button
                variant="secondary"
                size="md"
                stretch="auto"
                label={t("agents.meeting_notes.cancel")}
                disabled={busy}
                onClick={close}
              />
              <Button
                variant="primary"
                size="md"
                stretch="auto"
                loading={busy}
                disabled={textLength < MIN_TEXT}
                label={t("agents.meeting_notes.find")}
                onClick={() => void find()}
              />
            </>
          ) : (
            <>
              <Button
                variant="secondary"
                size="md"
                stretch="auto"
                label={t("agents.meeting_notes.back")}
                disabled={busy}
                onClick={() => {
                  setProposals(null);
                  setError(null);
                }}
              />
              <Button
                variant="primary"
                size="md"
                stretch="auto"
                loading={busy}
                disabled={!canCreate}
                label={t("agents.meeting_notes.create", { count: accepted.length })}
                onClick={() => void create()}
              />
            </>
          )}
        </DialogActions>
      </DialogContent>
    </Dialog>
  );
}
