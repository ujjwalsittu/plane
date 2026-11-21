/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import useSWR from "swr";
import { Badge } from "@makeplane/propel/components/badge";
import { Button } from "@makeplane/propel/components/button";
import {
  Drawer,
  DrawerBody,
  DrawerHeader,
  DrawerHeaderContent,
  DrawerPanel,
} from "@makeplane/propel/components/drawer";
import { useTranslation } from "@plane/i18n";
import type { TAgentAuditEntry, TWorkspaceAgent } from "@plane/types";
import { AgentsService } from "@/services/agents.service";

const service = new AgentsService();

const entryText = (entry: TAgentAuditEntry) => {
  if (entry.kind === "request") return `${entry.method} ${entry.path}`;
  if (entry.kind === "approval") return entry.summary;
  return entry.title;
};

const entryStatus = (entry: TAgentAuditEntry) => (entry.kind === "request" ? String(entry.status) : entry.status);

const entryTone = (entry: TAgentAuditEntry) => {
  if (entry.kind === "request") return entry.status >= 400 ? "danger" : "neutral";
  if (["failed", "rejected", "expired", "cancelled"].includes(entry.status)) return "danger";
  if (["succeeded", "approved"].includes(entry.status)) return "success";
  return "neutral";
};

type Props = {
  workspaceSlug: string;
  /** The agent whose trail is open; the drawer is closed while it is null. */
  agent: TWorkspaceAgent | null;
  onClose: () => void;
};

/** An agent's audit trail: its API requests, approvals and runs, newest first. */
export const AgentAuditDrawer = observer(function AgentAuditDrawer({ workspaceSlug, agent, onClose }: Props) {
  const { t } = useTranslation();
  const { data, error, isLoading } = useSWR(agent ? `AGENT_AUDIT_${workspaceSlug}_${agent.id}` : null, () =>
    service.getAudit(workspaceSlug, (agent as TWorkspaceAgent).id)
  );

  return (
    <Drawer
      open={!!agent}
      modal
      swipeDirection="right"
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DrawerPanel variant="overlay" side="end" size="sm" backdrop aria-label={t("agents.audit.title")}>
        <DrawerHeader>
          <DrawerHeaderContent>
            <div className="flex flex-col gap-0.5">
              <span className="text-h6-medium text-primary">{t("agents.audit.title")}</span>
              {agent && (
                <span className="text-body-xs-regular text-tertiary">
                  {t("agents.audit.description", { agent: agent.name })}
                </span>
              )}
            </div>
          </DrawerHeaderContent>
        </DrawerHeader>
        <DrawerBody>
          {error ? (
            <p className="text-body-sm-regular text-danger-primary">{t("agents.audit.load_error")}</p>
          ) : isLoading || !data ? (
            <p className="text-body-sm-regular text-tertiary">{t("loading")}</p>
          ) : data.length === 0 ? (
            <p className="text-body-sm-regular text-tertiary">{t("agents.audit.empty")}</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {data.map((entry) => (
                <li
                  key={
                    entry.kind === "request"
                      ? `request-${entry.at}-${entry.method}-${entry.path}`
                      : `${entry.kind}-${entry.id}`
                  }
                  className="flex flex-col gap-1 border-b border-subtle pb-3"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="neutral" size="sm" label={t(`agents.audit.${entry.kind}`)} />
                    <Badge variant={entryTone(entry)} size="sm" label={entryStatus(entry)} />
                    <time className="ml-auto text-body-xs-regular text-tertiary" dateTime={entry.at}>
                      {new Date(entry.at).toLocaleString()}
                    </time>
                  </div>
                  <p className="text-body-xs-regular break-all text-primary">{entryText(entry)}</p>
                  {entry.kind === "approval" && entry.decided_by && (
                    <p className="text-body-xs-regular text-tertiary">{entry.decided_by}</p>
                  )}
                </li>
              ))}
            </ul>
          )}
          <div className="pt-4">
            <Button variant="secondary" size="md" stretch="auto" label={t("agents.audit.close")} onClick={onClose} />
          </div>
        </DrawerBody>
      </DrawerPanel>
    </Drawer>
  );
});
