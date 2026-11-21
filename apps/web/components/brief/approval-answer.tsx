/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { Avatar } from "@makeplane/propel/components/avatar";
import { Button } from "@makeplane/propel/components/button";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { TAgentApproval } from "@plane/types";
import { getFileURL } from "@plane/utils";
import { SupervisionService } from "@/services/supervision.service";

const service = new SupervisionService();

/** An agent's held action: who wants to do what, with Approve and Reject. */
export function ApprovalAnswer({
  workspaceSlug,
  approval,
  onDecided,
}: {
  workspaceSlug: string;
  approval: TAgentApproval;
  onDecided: () => void;
}) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);

  const decide = async (approve: boolean) => {
    setBusy(true);
    try {
      await service.decideApproval(workspaceSlug, approval.id, approve);
      onDecided();
    } catch (error) {
      const failure = error as { error?: string; conflict?: boolean };
      setToast({
        type: "error",
        title: failure?.conflict ? t("agents.approval.already") : (failure?.error ?? t("agents.approval.error")),
      });
      // Someone else may have decided first; refresh so the row reflects it.
      onDecided();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex min-w-0 items-center gap-2">
        <Avatar
          alt={approval.agent.name}
          fallback={approval.agent.name[0]?.toUpperCase()}
          src={getFileURL(approval.agent.avatar_url ?? "")}
          size="sm"
        />
        <p className="min-w-0 text-body-xs-regular text-secondary">
          {t("agents.approval.wants_to", { agent: approval.agent.name, summary: approval.summary })}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button
          variant="primary"
          size="sm"
          stretch="auto"
          disabled={busy}
          label={t("agents.approval.approve")}
          onClick={() => void decide(true)}
        />
        <Button
          variant="secondary"
          size="sm"
          stretch="auto"
          disabled={busy}
          label={t("agents.approval.reject")}
          onClick={() => void decide(false)}
        />
      </div>
    </div>
  );
}
