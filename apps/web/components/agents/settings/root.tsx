/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
import { Button } from "@makeplane/propel/components/button";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { TWorkspaceAgent } from "@plane/types";
import { AgentsService, agentsErrorMessage } from "@/services/agents.service";
import { AgentForm } from "./agent-form";
import { AgentList } from "./agent-list";
import { AISettingsCard } from "./ai-settings";
import { AgentAuditDrawer } from "./audit";
import { AgentTokenReveal } from "./token-reveal";

const service = new AgentsService();

type TFormState = { open: boolean; agent: TWorkspaceAgent | null };

/** Workspace settings for agents: the Claude (AI) settings card, the agent list and its dialogs. */
export const AgentsSettingsRoot = observer(function AgentsSettingsRoot({ workspaceSlug }: { workspaceSlug: string }) {
  const { t } = useTranslation();
  const {
    data: settings,
    error: settingsError,
    mutate: mutateSettings,
  } = useSWR(`AI_SETTINGS_${workspaceSlug}`, () => service.getAISettings(workspaceSlug));
  const {
    data: agents,
    error: agentsError,
    mutate: mutateAgents,
  } = useSWR(`WORKSPACE_AGENTS_${workspaceSlug}`, () => service.getAgents(workspaceSlug));
  const [form, setForm] = useState<TFormState>({ open: false, agent: null });
  const [reveal, setReveal] = useState<{ token: string; agentName: string } | null>(null);
  const [auditAgent, setAuditAgent] = useState<TWorkspaceAgent | null>(null);
  const [rotateAgent, setRotateAgent] = useState<TWorkspaceAgent | null>(null);
  const [deactivateAgent, setDeactivateAgent] = useState<TWorkspaceAgent | null>(null);

  const handleRotate = async () => {
    if (!rotateAgent) return;
    try {
      const { token } = await service.rotateToken(workspaceSlug, rotateAgent.id);
      setReveal({ token, agentName: rotateAgent.name });
      await mutateAgents();
    } catch (e) {
      setToast({ type: "error", title: agentsErrorMessage(e) ?? t("agents.list.rotate_error") });
    } finally {
      setRotateAgent(null);
    }
  };

  const handleDeactivate = async () => {
    if (!deactivateAgent) return;
    try {
      await service.deactivateAgent(workspaceSlug, deactivateAgent.id);
      await mutateAgents();
      setToast({ type: "success", title: t("agents.list.deactivated") });
    } catch (e) {
      setToast({ type: "error", title: agentsErrorMessage(e) ?? t("agents.list.deactivate_error") });
    } finally {
      setDeactivateAgent(null);
    }
  };

  if (settingsError || agentsError)
    return <div className="text-body-sm-regular text-danger-primary">{t("agents.load_error")}</div>;
  if (!settings || !agents) return <div className="text-body-sm-regular text-tertiary">{t("loading")}</div>;

  return (
    <div className="flex flex-col gap-6">
      <AISettingsCard workspaceSlug={workspaceSlug} settings={settings} mutate={mutateSettings} />

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-3">
          <h4 className="text-h6-medium text-primary">{t("agents.list.title")}</h4>
          <Button
            variant="primary"
            size="md"
            stretch="auto"
            label={t("agents.list.add")}
            onClick={() => setForm({ open: true, agent: null })}
          />
        </div>
        <AgentList
          agents={agents}
          onEdit={(agent) => setForm({ open: true, agent })}
          onAudit={setAuditAgent}
          onRotate={setRotateAgent}
          onDeactivate={setDeactivateAgent}
        />
      </section>

      <AgentForm
        key={form.agent?.id ?? "new"}
        workspaceSlug={workspaceSlug}
        isOpen={form.open}
        agent={form.agent}
        onClose={() => setForm((current) => ({ ...current, open: false }))}
        onCreated={(created) => {
          const { token, ...agent } = created;
          setForm({ open: false, agent: null });
          setReveal({ token, agentName: agent.name });
          void mutateAgents();
          // a new agent changes whether cloud agents are ready
          void mutateSettings();
        }}
        onUpdated={() => {
          setForm({ open: false, agent: null });
          void mutateAgents();
        }}
      />
      <AgentTokenReveal
        token={reveal?.token ?? null}
        agentName={reveal?.agentName ?? ""}
        onClose={() => setReveal(null)}
      />
      <AgentAuditDrawer workspaceSlug={workspaceSlug} agent={auditAgent} onClose={() => setAuditAgent(null)} />
      <ConfirmDialog
        isOpen={!!rotateAgent}
        handleClose={() => setRotateAgent(null)}
        handleSubmit={handleRotate}
        isSubmitting={false}
        title={t("agents.list.rotate_title")}
        content={t("agents.list.rotate_description")}
      />
      <ConfirmDialog
        isOpen={!!deactivateAgent}
        handleClose={() => setDeactivateAgent(null)}
        handleSubmit={handleDeactivate}
        isSubmitting={false}
        title={t("agents.list.deactivate_title")}
        content={t("agents.list.deactivate_description")}
      />
    </div>
  );
});
