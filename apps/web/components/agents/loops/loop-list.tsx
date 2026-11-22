/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { BadgeVariant } from "@makeplane/propel/components/badge";
import { Badge } from "@makeplane/propel/components/badge";
import { Button } from "@makeplane/propel/components/button";
import { Switch } from "@makeplane/propel/components/switch";
import { useTranslation } from "@plane/i18n";
import type { TAgentLoop, TAgentRunStatus } from "@plane/types";

const STATUS_VARIANT: Record<TAgentRunStatus, BadgeVariant> = {
  queued: "neutral",
  running: "purple",
  waiting: "warning",
  succeeded: "success",
  failed: "danger",
  cancelled: "grey",
};

type TTranslate = ReturnType<typeof useTranslation>["t"];

/** "Every Monday at 09:00 UTC", "On work items and comments, at most every 60 min" and so on. */
export const loopTriggerSummary = (loop: TAgentLoop, t: TTranslate): string => {
  if (loop.trigger === "event") {
    const types = loop.event_types.map((type) => t(`agents.loops.event_types.${type}`)).join(", ");
    return t("agents.loops.summary.event", { types, minutes: loop.cooldown_minutes });
  }
  const { every, at = "", weekday = 0 } = loop.schedule as { every?: string; at?: string; weekday?: number };
  if (every === "week")
    return t("agents.loops.summary.week", { weekday: t(`agents.loops.weekdays.${weekday}`), time: at });
  if (every === "day") return t("agents.loops.summary.day", { time: at });
  return t("agents.loops.summary.hour");
};

const formatDate = (value: string | null, fallback: string) => (value ? new Date(value).toLocaleString() : fallback);

type Props = {
  loops: TAgentLoop[];
  canManage: boolean;
  onEdit: (loop: TAgentLoop) => void;
  onToggle: (loop: TAgentLoop, active: boolean) => void;
  onRunNow: (loop: TAgentLoop) => void;
  onHistory: (loop: TAgentLoop) => void;
  onDelete: (loop: TAgentLoop) => void;
};

/** The project's loops: name, agent, trigger, next run, last run status and whether each is active. */
export function LoopList({ loops, canManage, onEdit, onToggle, onRunNow, onHistory, onDelete }: Props) {
  const { t } = useTranslation();

  if (loops.length === 0)
    return (
      <p className="rounded-lg border border-subtle px-4 py-3 text-body-xs-regular text-tertiary">
        {t("agents.loops.empty")}
      </p>
    );

  return (
    <ul className="flex flex-col divide-y divide-subtle rounded-lg border border-subtle">
      {loops.map((loop) => (
        <li key={loop.id} className="flex flex-col gap-2 px-4 py-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <div className="flex min-w-48 flex-1 flex-col">
              <span className="truncate text-body-sm-medium text-primary">{loop.name}</span>
              <span className="truncate text-body-xs-regular text-tertiary">{loopTriggerSummary(loop, t)}</span>
            </div>
            <div className="flex min-w-28 flex-col text-body-xs-regular">
              <span className="text-tertiary">{t("agents.loops.agent")}</span>
              <span className="truncate text-primary">{loop.agent.name}</span>
            </div>
            <div className="flex min-w-28 flex-col text-body-xs-regular">
              <span className="text-tertiary">{t("agents.loops.owner")}</span>
              <span className="truncate text-primary">{loop.owner.display_name}</span>
            </div>
            <div className="flex min-w-32 flex-col text-body-xs-regular">
              <span className="text-tertiary">{t("agents.loops.next_run")}</span>
              <span className="text-primary">
                {loop.trigger === "schedule" && loop.is_active ? formatDate(loop.next_run_at, "—") : "—"}
              </span>
            </div>
            <div className="flex min-w-32 flex-col items-start gap-0.5 text-body-xs-regular">
              <span className="text-tertiary">{t("agents.loops.last_run")}</span>
              {loop.last_run ? (
                <Badge
                  variant={STATUS_VARIANT[loop.last_run.status]}
                  size="sm"
                  label={t(`agents.runs.status.${loop.last_run.status}`)}
                />
              ) : (
                <span className="text-primary">{t("agents.loops.never")}</span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Switch
                size="md"
                checked={loop.is_active}
                disabled={!canManage}
                aria-label={loop.is_active ? t("agents.loops.active") : t("agents.loops.paused")}
                onCheckedChange={(checked) => onToggle(loop, checked)}
              />
              <Badge
                variant={loop.is_active ? "success" : "neutral"}
                size="sm"
                label={loop.is_active ? t("agents.loops.active") : t("agents.loops.paused")}
              />
            </div>
          </div>
          {loop.last_error && <p className="text-body-xs-regular text-danger-primary">{loop.last_error}</p>}
          <div className="flex flex-wrap items-center gap-2">
            {canManage && (
              <>
                <Button
                  variant="secondary"
                  size="sm"
                  stretch="auto"
                  label={t("agents.loops.edit")}
                  onClick={() => onEdit(loop)}
                />
                <Button
                  variant="secondary"
                  size="sm"
                  stretch="auto"
                  label={t("agents.loops.run_now")}
                  onClick={() => onRunNow(loop)}
                />
              </>
            )}
            <Button
              variant="ghost"
              size="sm"
              stretch="auto"
              label={t("agents.loops.history")}
              onClick={() => onHistory(loop)}
            />
            {canManage && (
              <Button
                variant="ghost"
                size="sm"
                stretch="auto"
                label={t("agents.loops.delete")}
                onClick={() => onDelete(loop)}
              />
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
