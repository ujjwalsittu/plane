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
import type { TAgentApprovalAction, TAgentPermission, TWorkspaceAgent, TWorkspaceAgentPayload } from "@plane/types";
import { useMember } from "@/hooks/store/use-member";
import { useProject } from "@/hooks/store/use-project";
import { AgentsService } from "@/services/agents.service";
import type { TCreatedWorkspaceAgent } from "@/services/agents.service";
import { centsToDollarInput, dollarInputToCents } from "./money";

const service = new AgentsService();

const PERMISSIONS: TAgentPermission[] = ["read", "contribute", "manage"];
const MIN_BUDGET_CENTS = 50;
const MAX_BUDGET_CENTS = 100000;
const DEFAULT_BUDGET_CENTS = 500;

type TFieldErrors = Partial<Record<keyof TWorkspaceAgentPayload, string>>;

type Props = {
  workspaceSlug: string;
  isOpen: boolean;
  /** The agent being edited; none to create one. */
  agent: TWorkspaceAgent | null;
  onClose: () => void;
  onCreated: (agent: TCreatedWorkspaceAgent) => void;
  onUpdated: (agent: TWorkspaceAgent) => void;
};

/** Create or edit an agent. Remount (via `key`) per agent so the fields start from its values. */
export const AgentForm = observer(function AgentForm(props: Props) {
  const { workspaceSlug, isOpen, agent, onClose, onCreated, onUpdated } = props;
  const { t } = useTranslation();
  const {
    getUserDetails,
    workspace: { getWorkspaceMemberIds },
  } = useMember();
  const { workspaceProjectIds, getProjectById } = useProject();
  const [name, setName] = useState(agent?.name ?? "");
  const [description, setDescription] = useState(agent?.description ?? "");
  const [avatarUrl, setAvatarUrl] = useState(agent?.avatar_url ?? "");
  const [owner, setOwner] = useState<string | null>(agent?.owner.id ?? null);
  const [projectIds, setProjectIds] = useState<string[]>(agent?.project_ids ?? []);
  const [permission, setPermission] = useState<TAgentPermission>(agent?.permission ?? "contribute");
  const [approvals, setApprovals] = useState<TAgentApprovalAction[]>(
    agent?.approval_actions ?? ["delete", "change_dates"]
  );
  const [budget, setBudget] = useState(centsToDollarInput(agent?.run_budget_cents ?? DEFAULT_BUDGET_CENTS));
  const [errors, setErrors] = useState<TFieldErrors>({});
  const [saving, setSaving] = useState(false);

  const memberIds = getWorkspaceMemberIds(workspaceSlug);
  const ownerOptions = memberIds.map((id) => ({
    value: id,
    label: getUserDetails(id)?.display_name ?? id,
  }));
  const permissionOptions = PERMISSIONS.map((value) => ({
    value,
    label: t(`agents.permission.${value}`),
    description: t(`agents.permission.${value}_hint`),
  }));

  const toggleApproval = (action: TAgentApprovalAction, on: boolean) =>
    setApprovals((current) => (on ? [...new Set([...current, action])] : current.filter((a) => a !== action)));

  const toggleProject = (projectId: string, on: boolean) =>
    setProjectIds((current) => (on ? [...new Set([...current, projectId])] : current.filter((p) => p !== projectId)));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const budgetCents = dollarInputToCents(budget);
    const next: TFieldErrors = {};
    if (!name.trim()) next.name = t("agents.form.name_required");
    if (!owner) next.owner = t("agents.form.owner_required");
    if (budgetCents === null || budgetCents < MIN_BUDGET_CENTS || budgetCents > MAX_BUDGET_CENTS)
      next.run_budget_cents = t("agents.form.budget_invalid");
    setErrors(next);
    if (Object.keys(next).length > 0 || !owner || budgetCents === null) return;

    const payload: TWorkspaceAgentPayload = {
      name: name.trim(),
      description: description.trim(),
      avatar_url: avatarUrl.trim(),
      owner,
      project_ids: projectIds,
      permission,
      approval_actions: approvals,
      run_budget_cents: budgetCents,
    };
    setSaving(true);
    try {
      if (agent) {
        const updated = await service.updateAgent(workspaceSlug, agent.id, payload);
        setToast({ type: "success", title: t("agents.form.updated") });
        onUpdated(updated);
      } else {
        const created = await service.createAgent(workspaceSlug, payload);
        setToast({ type: "success", title: t("agents.form.created") });
        onCreated(created);
      }
    } catch (error) {
      // Errors are {field: message}; show a known field's message on that field, anything else as a toast.
      const body = (error && typeof error === "object" ? error : {}) as Record<string, unknown>;
      const fieldErrors: TFieldErrors = {};
      let general: string | undefined;
      for (const [key, value] of Object.entries(body)) {
        if (typeof value !== "string") continue;
        if (key in payload) fieldErrors[key as keyof TWorkspaceAgentPayload] = value;
        else general ??= value;
      }
      setErrors(fieldErrors);
      if (Object.keys(fieldErrors).length === 0)
        setToast({ type: "error", title: general ?? t("agents.form.save_error") });
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
                <DialogTitle>{agent ? t("agents.form.edit_title") : t("agents.form.create_title")}</DialogTitle>
              </DialogHeading>
            </DialogHeader>
            <DialogBody>
              <div className="flex flex-col gap-4">
                <InputField
                  size="md"
                  orientation="vertical"
                  label={t("agents.form.name")}
                  required
                  value={name}
                  maxLength={255}
                  onChange={(e) => setName(e.target.value)}
                  error={errors.name}
                />
                <TextAreaField
                  size="xl"
                  label={t("agents.form.description")}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  error={errors.description}
                />
                <InputField
                  size="md"
                  orientation="vertical"
                  label={t("agents.form.avatar_url")}
                  type="url"
                  value={avatarUrl}
                  onChange={(e) => setAvatarUrl(e.target.value)}
                  error={errors.avatar_url}
                />
                <SelectField<string>
                  size="md"
                  label={t("agents.form.owner")}
                  hint={t("agents.form.owner_hint")}
                  placeholder={t("agents.form.owner_placeholder")}
                  required
                  options={ownerOptions}
                  value={owner}
                  onValueChange={(value) => setOwner(value)}
                  error={errors.owner}
                />
                <SelectField<TAgentPermission>
                  size="md"
                  label={t("agents.form.permission")}
                  options={permissionOptions}
                  value={permission}
                  onValueChange={(value) => {
                    if (value !== null) setPermission(value);
                  }}
                  error={errors.permission}
                />
                <fieldset className="flex flex-col gap-2">
                  <legend className="text-body-xs-medium text-primary">{t("agents.form.projects")}</legend>
                  <p className="text-body-xs-regular text-tertiary">{t("agents.form.projects_hint")}</p>
                  <div className="flex max-h-40 flex-col gap-1 overflow-y-auto">
                    {(workspaceProjectIds ?? []).map((projectId) => (
                      <CheckboxField
                        key={projectId}
                        size="md"
                        label={getProjectById(projectId)?.name ?? projectId}
                        checked={projectIds.includes(projectId)}
                        onCheckedChange={(checked) => toggleProject(projectId, checked)}
                      />
                    ))}
                  </div>
                  {errors.project_ids && (
                    <p className="text-body-xs-regular text-danger-primary">{errors.project_ids}</p>
                  )}
                </fieldset>
                <fieldset className="flex flex-col gap-2">
                  <legend className="text-body-xs-medium text-primary">{t("agents.form.approvals")}</legend>
                  <CheckboxField
                    size="md"
                    label={t("agents.form.approval_delete")}
                    checked={approvals.includes("delete")}
                    onCheckedChange={(checked) => toggleApproval("delete", checked)}
                  />
                  <CheckboxField
                    size="md"
                    label={t("agents.form.approval_change_dates")}
                    checked={approvals.includes("change_dates")}
                    onCheckedChange={(checked) => toggleApproval("change_dates", checked)}
                  />
                  {errors.approval_actions && (
                    <p className="text-body-xs-regular text-danger-primary">{errors.approval_actions}</p>
                  )}
                </fieldset>
                <InputField
                  size="md"
                  orientation="vertical"
                  type="text"
                  inputMode="decimal"
                  label={t("agents.form.budget")}
                  hint={t("agents.form.budget_hint")}
                  value={budget}
                  onChange={(e) => setBudget(e.target.value)}
                  error={errors.run_budget_cents}
                />
              </div>
            </DialogBody>
          </DialogMain>
          <DialogActions>
            <Button variant="secondary" size="md" stretch="auto" label={t("agents.form.cancel")} onClick={onClose} />
            <Button
              variant="primary"
              size="md"
              stretch="auto"
              type="submit"
              loading={saving}
              label={agent ? t("agents.form.save") : t("agents.form.create")}
            />
          </DialogActions>
        </form>
      </DialogContent>
    </Dialog>
  );
});
