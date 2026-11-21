/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { Avatar } from "@makeplane/propel/components/avatar";
import { Badge } from "@makeplane/propel/components/badge";
import { Button } from "@makeplane/propel/components/button";
import { Switch } from "@makeplane/propel/components/switch";
import { useTranslation } from "@plane/i18n";
import type { TWorkspaceAgent } from "@plane/types";
import { getFileURL } from "@plane/utils";
import { useProject } from "@/hooks/store/use-project";
import { formatCents } from "./money";

type Props = {
  agents: TWorkspaceAgent[];
  onEdit: (agent: TWorkspaceAgent) => void;
  onAudit: (agent: TWorkspaceAgent) => void;
  onRotate: (agent: TWorkspaceAgent) => void;
  /** Turning the toggle off asks to deactivate; there is no way to turn an agent back on. */
  onDeactivate: (agent: TWorkspaceAgent) => void;
};

/** The workspace's agents: who they are, who owns them, what they reach and when they last acted. */
export const AgentList = observer(function AgentList({ agents, onEdit, onAudit, onRotate, onDeactivate }: Props) {
  const { t } = useTranslation();
  const { getProjectById } = useProject();

  if (agents.length === 0)
    return (
      <p className="rounded-lg border border-subtle px-4 py-3 text-body-xs-regular text-tertiary">
        {t("agents.list.empty")}
      </p>
    );

  return (
    <ul className="flex flex-col divide-y divide-subtle rounded-lg border border-subtle">
      {agents.map((agent) => {
        const projectNames = agent.project_ids.map((id) => getProjectById(id)?.name).filter(Boolean) as string[];
        return (
          <li key={agent.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
            <div className="flex min-w-48 flex-1 items-center gap-3">
              <Avatar
                size="md"
                alt={agent.name}
                src={agent.avatar_url ? getFileURL(agent.avatar_url) : undefined}
                fallback={agent.name[0]?.toUpperCase()}
              />
              <div className="flex min-w-0 flex-col">
                <span className="truncate text-body-sm-medium text-primary">{agent.name}</span>
                {agent.description && (
                  <span className="truncate text-body-xs-regular text-tertiary">{agent.description}</span>
                )}
              </div>
            </div>
            <div className="flex min-w-32 flex-col text-body-xs-regular">
              <span className="text-tertiary">{t("agents.list.owner")}</span>
              <span className="truncate text-primary">{agent.owner.display_name}</span>
            </div>
            <div className="flex min-w-28 flex-col gap-0.5 text-body-xs-regular">
              <span className="text-tertiary">{t("agents.list.permission")}</span>
              <span className="text-primary">{t(`agents.permission.${agent.permission}`)}</span>
              <span className="text-tertiary">{formatCents(agent.run_budget_cents)}</span>
            </div>
            <div className="flex min-w-32 flex-col text-body-xs-regular" title={projectNames.join(", ")}>
              <span className="text-tertiary">{t("agents.list.projects")}</span>
              <span className="text-primary">
                {agent.project_ids.length === 0
                  ? t("agents.list.no_projects")
                  : t("agents.list.projects_count", { count: agent.project_ids.length })}
              </span>
            </div>
            <div className="flex min-w-32 flex-col text-body-xs-regular">
              <span className="text-tertiary">{t("agents.list.last_active")}</span>
              <span className="text-primary">
                {agent.last_active_at ? new Date(agent.last_active_at).toLocaleString() : t("agents.list.never")}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Switch
                size="md"
                checked={agent.is_active}
                disabled={!agent.is_active}
                aria-label={agent.is_active ? t("agents.list.active") : t("agents.list.inactive")}
                onCheckedChange={(checked) => {
                  if (!checked) onDeactivate(agent);
                }}
              />
              <Badge
                variant={agent.is_active ? "success" : "neutral"}
                size="sm"
                label={agent.is_active ? t("agents.list.active") : t("agents.list.inactive")}
              />
            </div>
            <div className="flex items-center gap-2">
              {agent.is_active && (
                <>
                  <Button
                    variant="secondary"
                    size="sm"
                    stretch="auto"
                    label={t("agents.list.edit")}
                    onClick={() => onEdit(agent)}
                  />
                  <Button
                    variant="secondary"
                    size="sm"
                    stretch="auto"
                    label={t("agents.list.rotate_token")}
                    onClick={() => onRotate(agent)}
                  />
                </>
              )}
              <Button
                variant="ghost"
                size="sm"
                stretch="auto"
                label={t("agents.list.audit")}
                onClick={() => onAudit(agent)}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
});
