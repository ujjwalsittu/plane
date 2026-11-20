/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
import { Button } from "@makeplane/propel/components/button";
import { InputField } from "@makeplane/propel/components/input-field";
import { TextAreaField } from "@makeplane/propel/components/text-area-field";
import { EntityDetailWidgetSection } from "@plane/blocks/entity-detail";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { TDecisionRequest, TWorkItemWaiting } from "@plane/types";
import { renderFormattedDate } from "@plane/utils";
import { DecisionAnswer } from "@/components/brief/decision-answer";
import { MemberSelect } from "@/components/dropdowns/member/member-select";
import { useUser } from "@/hooks/store/user";
import { SupervisionService } from "@/services/supervision.service";

const service = new SupervisionService();

type Props = { workspaceSlug: string; projectId: string; issueId: string; disabled?: boolean };

export const getWorkItemWaitingKey = (issueId: string) => `WORK_ITEM_WAITING_${issueId}`;
export const getWorkItemDecisionsKey = (issueId: string) => `WORK_ITEM_DECISIONS_${issueId}`;

const errorMessage = (error: unknown, fallback: string) => {
  const body = error as Record<string, unknown> | undefined;
  const first = body && typeof body === "object" ? Object.values(body).find((v) => typeof v === "string") : undefined;
  return (first as string | undefined) ?? fallback;
};

/** Who or what the work item is waiting on, plus the decisions asked of people on it. */
export const SupervisionCollapsible = observer(function SupervisionCollapsible(props: Props) {
  const { workspaceSlug, projectId, issueId, disabled = false } = props;
  const { t } = useTranslation();
  const { data: currentUser } = useUser();
  const [isOpen, setIsOpen] = useState(true);
  const [editingWaiting, setEditingWaiting] = useState(false);
  const [asking, setAsking] = useState(false);

  const { data: waiting, mutate: refreshWaiting } = useSWR(getWorkItemWaitingKey(issueId), () =>
    service.getWaiting(workspaceSlug, projectId, issueId)
  );
  const { data: decisions, mutate: refreshDecisions } = useSWR(getWorkItemDecisionsKey(issueId), () =>
    service.listWorkItemDecisions(workspaceSlug, projectId, issueId)
  );

  const open = decisions ?? [];
  const count = open.length + (waiting ? 1 : 0);

  // Read-only viewers with nothing to see get no empty section.
  if (disabled && count === 0) return null;

  const clearWaiting = async () => {
    try {
      await service.clearWaiting(workspaceSlug, projectId, issueId);
    } catch (error) {
      setToast({ type: "error", title: errorMessage(error, t("supervision.waiting_clear_error")) });
    }
    await refreshWaiting();
  };

  const withdraw = async (decision: TDecisionRequest) => {
    try {
      await service.withdrawDecision(workspaceSlug, projectId, issueId, decision.id);
    } catch (error) {
      setToast({ type: "error", title: errorMessage(error, t("supervision.decision_withdraw_error")) });
    }
    await refreshDecisions();
  };

  return (
    <EntityDetailWidgetSection
      title={t("supervision.waiting_title")}
      count={count}
      isOpen={isOpen}
      onToggle={() => setIsOpen((value) => !value)}
    >
      <div className="flex flex-col gap-3 py-1">
        <div className="flex flex-col gap-1.5 px-2">
          {editingWaiting ? (
            <WaitingForm
              workspaceSlug={workspaceSlug}
              projectId={projectId}
              issueId={issueId}
              initial={waiting ?? null}
              onDone={() => {
                setEditingWaiting(false);
                void refreshWaiting();
              }}
            />
          ) : waiting ? (
            <div className="flex items-start gap-2">
              <div className="flex min-w-0 flex-1 flex-col">
                <span className="text-body-xs-medium text-primary">
                  {[waiting.waiting_on_name, waiting.waiting_on_text].filter(Boolean).join(" · ")}
                </span>
                {waiting.note && <span className="text-body-xs-regular text-secondary">{waiting.note}</span>}
                {waiting.since && (
                  <span className="text-caption-md-regular text-tertiary">
                    {t("supervision.waiting_since", { date: renderFormattedDate(waiting.since) ?? "" })}
                  </span>
                )}
              </div>
              {!disabled && (
                <>
                  <Button
                    variant="ghost"
                    size="sm"
                    stretch="auto"
                    label={t("supervision.waiting_edit")}
                    onClick={() => setEditingWaiting(true)}
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    stretch="auto"
                    label={t("supervision.waiting_clear")}
                    onClick={() => void clearWaiting()}
                  />
                </>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <span className="flex-1 text-body-xs-regular text-tertiary">{t("supervision.waiting_none")}</span>
              {!disabled && (
                <Button
                  variant="ghost"
                  size="sm"
                  stretch="auto"
                  label={t("supervision.waiting_set")}
                  onClick={() => setEditingWaiting(true)}
                />
              )}
            </div>
          )}
        </div>

        <div className="flex flex-col gap-2 px-2">
          <div className="flex items-center gap-2">
            <span className="flex-1 text-caption-md-medium text-tertiary">{t("supervision.decisions_title")}</span>
            {!disabled && !asking && (
              <Button
                variant="ghost"
                size="sm"
                stretch="auto"
                label={t("supervision.decision_ask")}
                onClick={() => setAsking(true)}
              />
            )}
          </div>
          {asking && (
            <AskForm
              workspaceSlug={workspaceSlug}
              projectId={projectId}
              issueId={issueId}
              onDone={() => {
                setAsking(false);
                void refreshDecisions();
              }}
              onCancel={() => setAsking(false)}
            />
          )}
          {open.length === 0 && !asking && (
            <p className="text-body-xs-regular text-tertiary">{t("supervision.decision_none")}</p>
          )}
          {open.map((decision) => {
            const isAsked = !!currentUser && decision.asked_user?.id === currentUser.id;
            const isRequester = !!currentUser && decision.requested_by?.id === currentUser.id;
            return (
              <div key={decision.id} className="flex flex-col gap-1.5 rounded-md border border-subtle p-2">
                {isAsked ? (
                  <DecisionAnswer
                    workspaceSlug={workspaceSlug}
                    projectId={projectId}
                    issueId={issueId}
                    decision={decision}
                    onAnswered={() => void refreshDecisions()}
                  />
                ) : (
                  <p className="text-body-xs-regular text-secondary">{decision.question}</p>
                )}
                <div className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-caption-md-regular text-tertiary">
                    {t("supervision.decision_asked_of", { name: decision.asked_user?.display_name ?? "" })}
                    {decision.requested_by && !isRequester
                      ? ` · ${t("supervision.decision_requested_by", { name: decision.requested_by.display_name })}`
                      : ""}
                  </span>
                  {(isRequester || isAsked) && (
                    <Button
                      variant="ghost"
                      size="sm"
                      stretch="auto"
                      label={t("supervision.decision_withdraw")}
                      onClick={() => void withdraw(decision)}
                    />
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </EntityDetailWidgetSection>
  );
});

function WaitingForm({
  workspaceSlug,
  projectId,
  issueId,
  initial,
  onDone,
}: {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  initial: TWorkItemWaiting | null;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [user, setUser] = useState<string | null>(initial?.waiting_on_user ?? null);
  const [text, setText] = useState(initial?.waiting_on_text ?? "");
  const [note, setNote] = useState(initial?.note ?? "");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      await service.setWaiting(workspaceSlug, projectId, issueId, {
        waiting_on_user: user,
        waiting_on_text: text.trim(),
        note: note.trim(),
      });
      onDone();
    } catch (error) {
      setToast({ type: "error", title: errorMessage(error, t("supervision.waiting_save_error")) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <MemberSelect
        value={user}
        onChange={setUser}
        projectId={projectId}
        clearable
        variant="select-ghost-md"
        placeholder={t("supervision.waiting_person_placeholder")}
      />
      <InputField
        size="md"
        orientation="vertical"
        value={text}
        maxLength={255}
        onChange={(e) => setText(e.target.value)}
        aria-label={t("supervision.waiting_text_placeholder")}
        placeholder={t("supervision.waiting_text_placeholder")}
      />
      <InputField
        size="md"
        orientation="vertical"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        aria-label={t("supervision.waiting_note_placeholder")}
        placeholder={t("supervision.waiting_note_placeholder")}
      />
      <div className="flex items-center gap-2">
        <Button
          type="submit"
          variant="primary"
          size="sm"
          stretch="auto"
          loading={busy}
          disabled={!user && !text.trim()}
          label={t("supervision.waiting_save")}
        />
        <Button
          type="button"
          variant="ghost"
          size="sm"
          stretch="auto"
          disabled={busy}
          label={t("supervision.waiting_cancel")}
          onClick={onDone}
        />
      </div>
    </form>
  );
}

function AskForm({
  workspaceSlug,
  projectId,
  issueId,
  onDone,
  onCancel,
}: {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  onDone: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [asked, setAsked] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [options, setOptions] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!asked) return;
    setBusy(true);
    try {
      await service.createDecision(workspaceSlug, projectId, issueId, {
        asked_user: asked,
        question: question.trim(),
        options: options
          .split("\n")
          .map((o) => o.trim())
          .filter(Boolean),
      });
      onDone();
    } catch (error) {
      setToast({ type: "error", title: errorMessage(error, t("supervision.decision_create_error")) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <MemberSelect
        value={asked}
        onChange={setAsked}
        projectId={projectId}
        variant="select-ghost-md"
        placeholder={t("supervision.decision_person_placeholder")}
      />
      <InputField
        size="md"
        orientation="vertical"
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        aria-label={t("supervision.decision_question_placeholder")}
        placeholder={t("supervision.decision_question_placeholder")}
      />
      <TextAreaField
        size="lg"
        value={options}
        onChange={(e) => setOptions(e.target.value)}
        aria-label={t("supervision.decision_options_placeholder")}
        placeholder={t("supervision.decision_options_placeholder")}
      />
      <div className="flex items-center gap-2">
        <Button
          type="submit"
          variant="primary"
          size="sm"
          stretch="auto"
          loading={busy}
          disabled={!asked || !question.trim()}
          label={t("supervision.decision_submit")}
        />
        <Button
          type="button"
          variant="ghost"
          size="sm"
          stretch="auto"
          disabled={busy}
          label={t("supervision.waiting_cancel")}
          onClick={onCancel}
        />
      </div>
    </form>
  );
}
