/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { Avatar } from "@makeplane/propel/components/avatar";
import type { BadgeVariant } from "@makeplane/propel/components/badge";
import { Badge } from "@makeplane/propel/components/badge";
import { Button } from "@makeplane/propel/components/button";
import { InputField } from "@makeplane/propel/components/input-field";
import { ChevronRightOutline, LinkOutline } from "@makeplane/propel/icons";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { TAgentRun, TAgentRunStatus } from "@plane/types";
import { cn, getFileURL } from "@plane/utils";
import { formatCents } from "@/components/agents/settings/money";
import { agentsErrorMessage, AgentsService } from "@/services/agents.service";
import { formatDuration, turnedTerminal } from "./format";
import { RunSteps } from "./run-steps";
import { AGENT_RUNS_LIVE_REFRESH_MS, getAgentRunKey } from "./use-agent-runs";

const service = new AgentsService();

const STATUS_VARIANT: Record<TAgentRunStatus, BadgeVariant> = {
  queued: "neutral",
  running: "purple",
  waiting: "warning",
  succeeded: "success",
  failed: "danger",
  cancelled: "grey",
};

/** A run on a work item (`issueId`) or a loop's run (`loopId`, no work item): the endpoints differ. */
type Props = {
  workspaceSlug: string;
  projectId: string;
  run: TAgentRun;
  disabled: boolean;
  onChanged: () => void;
} & ({ issueId: string; loopId?: never } | { loopId: string; issueId?: never });

const runApi = (workspaceSlug: string, projectId: string, issueId?: string, loopId?: string) =>
  loopId
    ? {
        get: (runId: string) => service.getLoopRun(workspaceSlug, projectId, loopId, runId),
        followUp: (runId: string, text: string) =>
          service.followUpLoopRun(workspaceSlug, projectId, loopId, runId, text),
        cancel: (runId: string) => service.cancelLoopRun(workspaceSlug, projectId, loopId, runId),
      }
    : {
        get: (runId: string) => service.getRun(workspaceSlug, projectId, issueId ?? "", runId),
        followUp: (runId: string, text: string) =>
          service.followUp(workspaceSlug, projectId, issueId ?? "", runId, text),
        cancel: (runId: string) => service.cancelRun(workspaceSlug, projectId, issueId ?? "", runId),
      };

export function RunRow({ workspaceSlug, projectId, issueId, loopId, run, disabled, onChanged }: Props) {
  const { t } = useTranslation();
  const api = runApi(workspaceSlug, projectId, issueId, loopId);
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);

  // The steps come with the single-run response, so they are fetched only for an expanded row.
  const {
    data: detail,
    error: stepsError,
    mutate,
  } = useSWR(open ? getAgentRunKey(run.id) : null, () => api.get(run.id), {
    refreshInterval: run.is_live ? AGENT_RUNS_LIVE_REFRESH_MS : 0,
  });

  // When the run ends, fetch once more so the final steps show without waiting for a focus change.
  const previousStatus = useRef(run.status);
  useEffect(() => {
    if (turnedTerminal(previousStatus.current, run.status) && open) void mutate();
    previousStatus.current = run.status;
  }, [run.status, open, mutate]);

  const name = run.agent?.name ?? run.actor.display_name;
  const isManaged = run.kind === "managed";
  const canFollowUp = isManaged && !disabled && (run.status === "succeeded" || run.status === "waiting");
  const canCancel =
    isManaged && !disabled && (run.status === "queued" || run.status === "running" || run.status === "waiting");

  const sendFollowUp = async () => {
    if (!text.trim()) return;
    setSending(true);
    try {
      await api.followUp(run.id, text.trim());
      setText("");
      void mutate();
      onChanged();
    } catch (error) {
      setToast({ type: "error", title: agentsErrorMessage(error) ?? t("agents.runs.follow_up_error") });
    } finally {
      setSending(false);
    }
  };

  const cancel = async () => {
    setCancelling(true);
    setConfirmCancel(false);
    try {
      await api.cancel(run.id);
      setToast({ type: "success", title: t("agents.runs.cancelled") });
      void mutate();
      onChanged();
    } catch (error) {
      setToast({ type: "error", title: agentsErrorMessage(error) ?? t("agents.runs.cancel_error") });
    } finally {
      setCancelling(false);
    }
  };

  return (
    <li className="flex flex-col rounded-md border border-subtle">
      <button
        type="button"
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-2 py-1.5 text-left"
        aria-expanded={open}
        aria-label={t(open ? "agents.runs.collapse" : "agents.runs.expand")}
        onClick={() => setOpen((value) => !value)}
      >
        <ChevronRightOutline
          className={cn("size-3.5 shrink-0 text-tertiary transition-transform", { "rotate-90": open })}
        />
        <Avatar
          size="sm"
          alt={name}
          src={run.agent?.avatar_url ? getFileURL(run.agent.avatar_url) : undefined}
          fallback={name[0]?.toUpperCase()}
        />
        <span className="min-w-0 flex-1 truncate text-body-xs-medium text-primary">
          {name}
          {run.delegated_by && (
            <span className="text-body-xs-regular text-tertiary">
              {" "}
              {t("agents.runs.for_person", { name: run.delegated_by.display_name })}
            </span>
          )}
        </span>
        <Badge variant={STATUS_VARIANT[run.status]} size="sm" label={t(`agents.runs.status.${run.status}`)} />
        {run.duration_seconds !== null && (
          <span className="text-caption-md-regular text-tertiary" title={t("agents.runs.duration")}>
            {formatDuration(run.duration_seconds)}
          </span>
        )}
        {run.cost_cents > 0 && (
          <span className="text-caption-md-regular text-tertiary" title={t("agents.runs.cost")}>
            {formatCents(run.cost_cents)}
          </span>
        )}
      </button>

      {run.links.length > 0 && (
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 px-2 pb-1.5 pl-9">
          {run.links.map((link) => (
            <a
              key={`${link.kind}-${link.ref}-${link.url}`}
              href={link.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex max-w-full items-center gap-1 text-caption-md-regular text-accent-primary hover:underline"
            >
              <LinkOutline className="size-3 shrink-0" aria-hidden />
              <span className="truncate">{link.title || link.ref}</span>
            </a>
          ))}
        </div>
      )}

      {open && (
        <div className="flex flex-col gap-3 border-t border-subtle px-3 py-2">
          {run.summary && <p className="text-body-xs-regular text-secondary">{run.summary}</p>}
          {run.error && <p className="text-body-xs-regular text-danger-primary">{run.error}</p>}
          {detail ? (
            <RunSteps steps={detail.steps ?? []} links={run.links} />
          ) : stepsError ? (
            <div className="flex items-center gap-2">
              <p className="text-body-xs-regular text-danger-primary">{t("agents.runs.steps_error")}</p>
              <Button
                variant="ghost"
                size="sm"
                stretch="auto"
                label={t("common.retry")}
                onClick={() => void mutate()}
              />
            </div>
          ) : (
            <p className="text-body-xs-regular text-tertiary">…</p>
          )}
          {(isManaged ? run.external_url : "") && (
            <a
              href={run.external_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-body-xs-medium text-accent-primary hover:underline"
            >
              <LinkOutline className="size-3 shrink-0" aria-hidden />
              {t("agents.runs.open_session")}
            </a>
          )}
          {canFollowUp && (
            <form
              className="flex items-center gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                void sendFollowUp();
              }}
            >
              <div className="min-w-0 flex-1">
                <InputField
                  size="md"
                  orientation="vertical"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  aria-label={t("agents.runs.follow_up")}
                  placeholder={t("agents.runs.follow_up_placeholder")}
                />
              </div>
              <Button
                type="submit"
                variant="secondary"
                size="md"
                stretch="auto"
                loading={sending}
                disabled={!text.trim()}
                label={t("agents.runs.follow_up_send")}
              />
            </form>
          )}
          {canCancel && (
            <div>
              <Button
                variant="ghost"
                size="sm"
                stretch="auto"
                loading={cancelling}
                label={t("agents.runs.cancel")}
                onClick={() => setConfirmCancel(true)}
              />
            </div>
          )}
        </div>
      )}
      <ConfirmDialog
        isOpen={confirmCancel}
        handleClose={() => setConfirmCancel(false)}
        handleSubmit={cancel}
        isSubmitting={false}
        title={t("agents.runs.cancel_confirm_title")}
        content={t("agents.runs.cancel_confirm_body")}
        primaryButtonText={{ default: t("agents.runs.cancel_confirm") }}
        secondaryButtonText={t("agents.runs.keep_running")}
      />
    </li>
  );
}
