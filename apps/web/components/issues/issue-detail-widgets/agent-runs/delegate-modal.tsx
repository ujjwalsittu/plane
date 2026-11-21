/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import useSWR from "swr";
import { Button } from "@makeplane/propel/components/button";
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
import { SelectField } from "@makeplane/propel/components/select-field";
import { TextAreaField } from "@makeplane/propel/components/text-area-field";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import { agentsErrorMessage, AgentsService } from "@/services/agents.service";

const service = new AgentsService();

export const getAgentsKey = (workspaceSlug: string) => `WORKSPACE_AGENTS_${workspaceSlug}`;

type Props = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  isOpen: boolean;
  onClose: () => void;
  onStarted: () => void;
};

/** Pick an active agent of this project and hand it the work item. Mounted only while open, so it starts fresh. */
export function DelegateModal({ workspaceSlug, projectId, issueId, isOpen, onClose, onStarted }: Props) {
  const { t } = useTranslation();
  const [agentId, setAgentId] = useState<string | null>(null);
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);

  const { data: agents, error: agentsError } = useSWR(getAgentsKey(workspaceSlug), () =>
    service.getAgents(workspaceSlug)
  );
  const options = (agents ?? [])
    .filter((agent) => agent.is_active && agent.project_ids.includes(projectId))
    .map((agent) => ({ value: agent.id, label: agent.name }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!agentId) return;
    setBusy(true);
    setRefusal(null);
    try {
      await service.delegate(workspaceSlug, projectId, issueId, {
        agent_id: agentId,
        instructions: instructions.trim(),
      });
      setToast({ type: "success", title: t("agents.runs.modal.started") });
      onStarted();
      onClose();
    } catch (error) {
      // Refusals (no key, agent not in the project, a run already live) come back as {field: message}.
      setRefusal(agentsErrorMessage(error) ?? t("agents.runs.modal.error"));
    } finally {
      setBusy(false);
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
        <form className="flex min-h-0 flex-1 flex-col" onSubmit={(e) => void submit(e)}>
          <DialogMain>
            <DialogHeader>
              <DialogHeading>
                <DialogTitle>{t("agents.runs.modal.title")}</DialogTitle>
              </DialogHeading>
            </DialogHeader>
            <DialogBody>
              <div className="flex flex-col gap-4">
                <p className="text-body-xs-regular text-secondary">{t("agents.runs.modal.description")}</p>
                {agentsError ? (
                  <p className="text-body-xs-regular text-danger-primary">{t("agents.runs.modal.agents_error")}</p>
                ) : agents && options.length === 0 ? (
                  <p className="text-body-xs-regular text-tertiary">{t("agents.runs.modal.no_agents")}</p>
                ) : (
                  <SelectField<string>
                    size="md"
                    label={t("agents.runs.modal.agent")}
                    placeholder={t("agents.runs.modal.agent_placeholder")}
                    required
                    options={options}
                    value={agentId}
                    onValueChange={(value) => setAgentId(value)}
                  />
                )}
                <TextAreaField
                  size="xl"
                  label={t("agents.runs.modal.instructions")}
                  placeholder={t("agents.runs.modal.instructions_placeholder")}
                  value={instructions}
                  onChange={(e) => setInstructions(e.target.value)}
                />
                {refusal && (
                  <p role="alert" className="text-body-xs-regular text-danger-primary">
                    {refusal}
                  </p>
                )}
              </div>
            </DialogBody>
          </DialogMain>
          <DialogActions>
            <Button
              type="button"
              variant="secondary"
              size="md"
              stretch="auto"
              disabled={busy}
              label={t("agents.runs.modal.cancel")}
              onClick={onClose}
            />
            <Button
              type="submit"
              variant="primary"
              size="md"
              stretch="auto"
              loading={busy}
              disabled={!agentId}
              label={t("agents.runs.modal.submit")}
            />
          </DialogActions>
        </form>
      </DialogContent>
    </Dialog>
  );
}
