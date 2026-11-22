/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import useSWR, { mutate as globalMutate } from "swr";
import { Button } from "@makeplane/propel/components/button";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { TAgentLoop } from "@plane/types";
import { AgentsService, agentsErrorMessage } from "@/services/agents.service";
import { LoopForm } from "./loop-form";
import { LoopList } from "./loop-list";
import { LoopRuns, getLoopRunsKey } from "./loop-runs";

const service = new AgentsService();

type Props = { workspaceSlug: string; projectId: string; canManage: boolean };

type TFormState = { open: boolean; loop: TAgentLoop | null };

/** A project's loops: the list, the create and edit dialog, and the run history of one loop. */
export const LoopsRoot = observer(function LoopsRoot({ workspaceSlug, projectId, canManage }: Props) {
  const { t } = useTranslation();
  const {
    data: loops,
    error,
    mutate,
  } = useSWR(`AGENT_LOOPS_${projectId}`, () => service.getLoops(workspaceSlug, projectId));
  const { data: agents } = useSWR(canManage ? `WORKSPACE_AGENTS_${workspaceSlug}` : null, () =>
    service.getAgents(workspaceSlug)
  );
  const [form, setForm] = useState<TFormState>({ open: false, loop: null });
  const [historyId, setHistoryId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<TAgentLoop | null>(null);

  const projectAgents = (agents ?? []).filter((agent) => agent.is_active && agent.project_ids.includes(projectId));
  const historyLoop = loops?.find((loop) => loop.id === historyId) ?? null;

  const handleToggle = async (loop: TAgentLoop, active: boolean) => {
    try {
      await service.updateLoop(workspaceSlug, projectId, loop.id, { is_active: active });
      await mutate();
    } catch (e) {
      setToast({ type: "error", title: agentsErrorMessage(e) ?? t("agents.loops.toggle_error") });
    }
  };

  const handleRunNow = async (loop: TAgentLoop) => {
    try {
      await service.runLoopNow(workspaceSlug, projectId, loop.id);
      setToast({ type: "success", title: t("agents.loops.started") });
      setHistoryId(loop.id);
      void globalMutate(getLoopRunsKey(loop.id));
    } catch (e) {
      setToast({ type: "error", title: agentsErrorMessage(e) ?? t("agents.loops.run_error") });
    } finally {
      // A refused start is recorded on the loop
      void mutate();
    }
  };

  const handleDelete = async () => {
    if (!deleting) return;
    try {
      await service.deleteLoop(workspaceSlug, projectId, deleting.id);
      if (historyId === deleting.id) setHistoryId(null);
      await mutate();
      setToast({ type: "success", title: t("agents.loops.deleted") });
    } catch (e) {
      setToast({ type: "error", title: agentsErrorMessage(e) ?? t("agents.loops.delete_error") });
    } finally {
      setDeleting(null);
    }
  };

  if (error) return <div className="text-body-sm-regular text-danger-primary">{t("agents.loops.load_error")}</div>;
  if (!loops) return <div className="text-body-sm-regular text-tertiary">{t("loading")}</div>;

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-3">
        {canManage && (
          <div className="flex justify-end">
            <Button
              variant="primary"
              size="md"
              stretch="auto"
              label={t("agents.loops.add")}
              onClick={() => setForm({ open: true, loop: null })}
            />
          </div>
        )}
        <LoopList
          loops={loops}
          canManage={canManage}
          onEdit={(loop) => setForm({ open: true, loop })}
          onToggle={(loop, active) => void handleToggle(loop, active)}
          onRunNow={(loop) => void handleRunNow(loop)}
          onHistory={(loop) => setHistoryId(loop.id)}
          onDelete={setDeleting}
        />
      </section>

      {historyLoop && (
        <LoopRuns
          key={historyLoop.id}
          workspaceSlug={workspaceSlug}
          projectId={projectId}
          loop={historyLoop}
          onClose={() => setHistoryId(null)}
          onChanged={() => void mutate()}
        />
      )}

      {form.open && (
        <LoopForm
          key={form.loop?.id ?? "new"}
          workspaceSlug={workspaceSlug}
          projectId={projectId}
          isOpen={form.open}
          loop={form.loop}
          agents={projectAgents}
          onClose={() => setForm((current) => ({ ...current, open: false }))}
          onSaved={() => {
            setForm({ open: false, loop: null });
            void mutate();
          }}
        />
      )}
      <ConfirmDialog
        isOpen={!!deleting}
        handleClose={() => setDeleting(null)}
        handleSubmit={handleDelete}
        isSubmitting={false}
        title={t("agents.loops.delete_title")}
        content={t("agents.loops.delete_description")}
      />
    </div>
  );
});
