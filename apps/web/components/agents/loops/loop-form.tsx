/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { Button } from "@makeplane/propel/components/button";
import { CheckboxField } from "@makeplane/propel/components/checkbox-field";
import {
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogHeading,
  DialogMain,
  DialogTitle,
} from "@makeplane/propel/components/dialog";
import { InputField } from "@makeplane/propel/components/input-field";
import { SelectField } from "@makeplane/propel/components/select-field";
import { TextAreaField } from "@makeplane/propel/components/text-area-field";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type {
  TAgentLoop,
  TAgentLoopEventType,
  TAgentLoopEvery,
  TAgentLoopPayload,
  TAgentLoopSchedule,
  TAgentLoopTrigger,
  TWorkspaceAgent,
} from "@plane/types";
import { useMember } from "@/hooks/store/use-member";
import { AgentsService } from "@/services/agents.service";

const service = new AgentsService();

const EVERY: TAgentLoopEvery[] = ["hour", "day", "week"];
const EVENT_TYPES: TAgentLoopEventType[] = ["issue", "issue_comment", "decision", "approval", "milestone"];
const WEEKDAYS = ["0", "1", "2", "3", "4", "5", "6"];
const COOLDOWN_MIN = 15;
const COOLDOWN_MAX = 10080;
const AT = /^([01]\d|2[0-3]):([0-5]\d)$/;

type TPreset = { key: "weekly_update" | "daily_triage" | "stale_nudges"; schedule: TAgentLoopSchedule };

/** Presets prefill name, trigger and instructions; everything stays editable. */
const PRESETS: TPreset[] = [
  { key: "weekly_update", schedule: { every: "week", at: "09:00", weekday: 0 } },
  { key: "daily_triage", schedule: { every: "day", at: "08:00" } },
  { key: "stale_nudges", schedule: { every: "day", at: "10:00" } },
];

type TField = "name" | "agent_id" | "owner_id" | "instructions" | "trigger" | "schedule" | "event_types" | "cooldown";
type TFieldErrors = Partial<Record<TField, string>>;
const SERVER_FIELDS: Record<string, TField> = {
  name: "name",
  agent_id: "agent_id",
  owner_id: "owner_id",
  instructions: "instructions",
  trigger: "trigger",
  schedule: "schedule",
  event_types: "event_types",
  cooldown_minutes: "cooldown",
};

type Props = {
  workspaceSlug: string;
  projectId: string;
  isOpen: boolean;
  /** The loop being edited; none to create one. */
  loop: TAgentLoop | null;
  /** Active agents that are members of this project. */
  agents: TWorkspaceAgent[];
  onClose: () => void;
  onSaved: (loop: TAgentLoop) => void;
};

/** Create or edit a loop. Remount (via `key`) per loop so the fields start from its values. */
export const LoopForm = observer(function LoopForm(props: Props) {
  const { workspaceSlug, projectId, isOpen, loop, agents, onClose, onSaved } = props;
  const { t } = useTranslation();
  const {
    getUserDetails,
    project: { getProjectMemberIds },
  } = useMember();
  const schedule = (loop?.trigger === "schedule" ? loop.schedule : {}) as Partial<TAgentLoopSchedule>;
  const [name, setName] = useState(loop?.name ?? "");
  const [agentId, setAgentId] = useState<string | null>(loop?.agent.id ?? null);
  const [ownerId, setOwnerId] = useState<string | null>(loop?.owner.id ?? null);
  const [trigger, setTrigger] = useState<TAgentLoopTrigger>(loop?.trigger ?? "schedule");
  const [every, setEvery] = useState<TAgentLoopEvery>(schedule.every ?? "day");
  const [at, setAt] = useState(schedule.at ?? "09:00");
  const [weekday, setWeekday] = useState(String(schedule.weekday ?? 0));
  const [eventTypes, setEventTypes] = useState<TAgentLoopEventType[]>(loop?.event_types ?? ["issue"]);
  const [cooldown, setCooldown] = useState(String(loop?.cooldown_minutes ?? 60));
  const [instructions, setInstructions] = useState(loop?.instructions ?? "");
  const [errors, setErrors] = useState<TFieldErrors>({});
  const [saving, setSaving] = useState(false);

  const agentOptions = agents.map((agent) => ({ value: agent.id, label: agent.name }));
  const ownerOptions = (getProjectMemberIds(projectId, false) ?? []).map((id) => ({
    value: id,
    label: getUserDetails(id)?.display_name ?? id,
  }));
  const triggerOptions = (["schedule", "event"] as TAgentLoopTrigger[]).map((value) => ({
    value,
    label: t(`agents.loops.form.trigger_${value}`),
  }));
  const everyOptions = EVERY.map((value) => ({ value, label: t(`agents.loops.every.${value}`) }));
  const weekdayOptions = WEEKDAYS.map((value) => ({ value, label: t(`agents.loops.weekdays.${value}`) }));

  const applyPreset = (preset: TPreset) => {
    setName(t(`agents.loops.presets.${preset.key}.name`));
    setInstructions(t(`agents.loops.presets.${preset.key}.instructions`));
    setTrigger("schedule");
    setEvery(preset.schedule.every);
    setAt(preset.schedule.at ?? "09:00");
    setWeekday(String(preset.schedule.weekday ?? 0));
    setErrors({});
  };

  const toggleEventType = (type: TAgentLoopEventType, on: boolean) =>
    setEventTypes((current) => (on ? [...new Set([...current, type])] : current.filter((v) => v !== type)));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const cooldownMinutes = Number(cooldown);
    const next: TFieldErrors = {};
    if (!name.trim()) next.name = t("agents.loops.form.name_required");
    if (!agentId) next.agent_id = t("agents.loops.form.agent_required");
    if (trigger === "schedule" && every !== "hour" && !AT.test(at)) next.schedule = t("agents.loops.form.at_invalid");
    if (trigger === "event" && eventTypes.length === 0) next.event_types = t("agents.loops.form.event_types_required");
    if (
      trigger === "event" &&
      (!Number.isInteger(cooldownMinutes) || cooldownMinutes < COOLDOWN_MIN || cooldownMinutes > COOLDOWN_MAX)
    )
      next.cooldown = t("agents.loops.form.cooldown_invalid");
    setErrors(next);
    if (Object.keys(next).length > 0 || !agentId) return;

    const payload: TAgentLoopPayload = {
      name: name.trim(),
      agent_id: agentId,
      instructions: instructions.trim(),
      trigger,
    };
    if (trigger === "schedule") {
      payload.schedule =
        every === "hour" ? { every } : every === "day" ? { every, at } : { every, at, weekday: Number(weekday) };
    } else {
      payload.event_types = eventTypes;
      payload.cooldown_minutes = cooldownMinutes;
    }
    // Without an owner the server makes the creator the owner
    if (ownerId && ownerId !== loop?.owner.id) payload.owner_id = ownerId;

    setSaving(true);
    try {
      const saved = loop
        ? await service.updateLoop(workspaceSlug, projectId, loop.id, payload)
        : await service.createLoop(workspaceSlug, projectId, payload);
      setToast({ type: "success", title: t(loop ? "agents.loops.form.updated" : "agents.loops.form.created") });
      onSaved(saved);
    } catch (error) {
      // Errors are {field: message}; show a known field's message on that field, anything else as a toast.
      const body = (error && typeof error === "object" ? error : {}) as Record<string, unknown>;
      const fieldErrors: TFieldErrors = {};
      let general: string | undefined;
      for (const [key, value] of Object.entries(body)) {
        if (typeof value !== "string") continue;
        if (key in SERVER_FIELDS) fieldErrors[SERVER_FIELDS[key]] = value;
        else general ??= value;
      }
      setErrors(fieldErrors);
      if (Object.keys(fieldErrors).length === 0)
        setToast({ type: "error", title: general ?? t("agents.loops.form.save_error") });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open={isOpen}
      disablePointerDismissal
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent size="md">
        <form className="flex min-h-0 flex-1 flex-col" onSubmit={(e) => void handleSubmit(e)}>
          <DialogMain>
            <DialogHeader>
              <DialogHeading>
                <DialogTitle>
                  {loop ? t("agents.loops.form.edit_title") : t("agents.loops.form.create_title")}
                </DialogTitle>
              </DialogHeading>
            </DialogHeader>
            <DialogBody>
              <div className="flex flex-col gap-4">
                {!loop && (
                  <div className="flex flex-col gap-2">
                    <span className="text-body-xs-medium text-primary">{t("agents.loops.presets.title")}</span>
                    <div className="flex flex-wrap gap-2">
                      {PRESETS.map((preset) => (
                        <Button
                          key={preset.key}
                          variant="secondary"
                          size="sm"
                          stretch="auto"
                          label={t(`agents.loops.presets.${preset.key}.name`)}
                          onClick={() => applyPreset(preset)}
                        />
                      ))}
                    </div>
                  </div>
                )}
                <InputField
                  size="md"
                  orientation="vertical"
                  label={t("agents.loops.form.name")}
                  required
                  value={name}
                  maxLength={255}
                  onChange={(e) => setName(e.target.value)}
                  error={errors.name}
                />
                <SelectField<string>
                  size="md"
                  label={t("agents.loops.form.agent")}
                  placeholder={t("agents.loops.form.agent_placeholder")}
                  hint={agents.length === 0 ? t("agents.loops.form.no_agents") : undefined}
                  required
                  options={agentOptions}
                  value={agentId}
                  onValueChange={(value) => setAgentId(value)}
                  error={errors.agent_id}
                />
                <SelectField<string>
                  size="md"
                  label={t("agents.loops.form.owner")}
                  hint={t("agents.loops.form.owner_hint")}
                  placeholder={t("agents.loops.form.owner_placeholder")}
                  options={ownerOptions}
                  value={ownerId}
                  onValueChange={(value) => setOwnerId(value)}
                  error={errors.owner_id}
                />
                <SelectField<TAgentLoopTrigger>
                  size="md"
                  label={t("agents.loops.form.trigger")}
                  options={triggerOptions}
                  value={trigger}
                  onValueChange={(value) => {
                    if (value !== null) setTrigger(value);
                  }}
                  error={errors.trigger}
                />
                {trigger === "schedule" ? (
                  <div className="flex flex-wrap gap-3">
                    <div className="min-w-32 flex-1">
                      <SelectField<TAgentLoopEvery>
                        size="md"
                        label={t("agents.loops.form.every")}
                        options={everyOptions}
                        value={every}
                        onValueChange={(value) => {
                          if (value !== null) setEvery(value);
                        }}
                      />
                    </div>
                    {every === "week" && (
                      <div className="min-w-32 flex-1">
                        <SelectField<string>
                          size="md"
                          label={t("agents.loops.form.weekday")}
                          options={weekdayOptions}
                          value={weekday}
                          onValueChange={(value) => {
                            if (value !== null) setWeekday(value);
                          }}
                        />
                      </div>
                    )}
                    {every !== "hour" && (
                      <div className="min-w-32 flex-1">
                        <InputField
                          size="md"
                          orientation="vertical"
                          type="time"
                          label={t("agents.loops.form.at")}
                          value={at}
                          onChange={(e) => setAt(e.target.value)}
                          error={errors.schedule}
                        />
                      </div>
                    )}
                  </div>
                ) : (
                  <>
                    <fieldset className="flex flex-col gap-2">
                      <legend className="text-body-xs-medium text-primary">{t("agents.loops.form.event_types")}</legend>
                      {EVENT_TYPES.map((type) => (
                        <CheckboxField
                          key={type}
                          size="md"
                          label={t(`agents.loops.event_types.${type}`)}
                          checked={eventTypes.includes(type)}
                          onCheckedChange={(checked) => toggleEventType(type, checked)}
                        />
                      ))}
                      {errors.event_types && (
                        <p className="text-body-xs-regular text-danger-primary">{errors.event_types}</p>
                      )}
                    </fieldset>
                    <InputField
                      size="md"
                      orientation="vertical"
                      type="text"
                      inputMode="numeric"
                      label={t("agents.loops.form.cooldown")}
                      hint={t("agents.loops.form.cooldown_hint")}
                      value={cooldown}
                      onChange={(e) => setCooldown(e.target.value)}
                      error={errors.cooldown}
                    />
                  </>
                )}
                <TextAreaField
                  size="xl"
                  label={t("agents.loops.form.instructions")}
                  placeholder={t("agents.loops.form.instructions_placeholder")}
                  value={instructions}
                  onChange={(e) => setInstructions(e.target.value)}
                  error={errors.instructions}
                />
              </div>
            </DialogBody>
          </DialogMain>
          <DialogActions>
            <Button
              variant="secondary"
              size="md"
              stretch="auto"
              label={t("agents.loops.form.cancel")}
              onClick={onClose}
            />
            <Button
              variant="primary"
              size="md"
              stretch="auto"
              type="submit"
              loading={saving}
              label={loop ? t("agents.loops.form.save") : t("agents.loops.form.create")}
            />
          </DialogActions>
        </form>
      </DialogContent>
    </Dialog>
  );
});
