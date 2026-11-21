/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Tooltip } from "@makeplane/propel/components/tooltip";
import { useTranslation } from "@plane/i18n";
import { cn } from "@plane/utils";
import { useLiveAgentRun } from "./live-runs";
import { useAgentRuns } from "./use-agent-runs";

function PulseDot({ className }: { className?: string }) {
  return (
    <span className={cn("relative flex size-2 shrink-0", className)} aria-hidden>
      <span className="absolute inline-flex size-full animate-ping rounded-full bg-accent-primary opacity-60" />
      <span className="relative inline-flex size-2 rounded-full bg-accent-primary" />
    </span>
  );
}

/** "Agent working" in the work item header while one of its runs is live. */
export function AgentWorkingPill({
  workspaceSlug,
  projectId,
  issueId,
}: {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
}) {
  const { t } = useTranslation();
  const { data: runs } = useAgentRuns(workspaceSlug, projectId, issueId);
  const run = runs?.find((r) => r.is_live);
  if (!run) return null;
  return (
    <Tooltip label={run.agent ? t("agents.runs.working_named", { agent: run.agent.name }) : t("agents.runs.working")}>
      <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-accent-primary/10 px-2 py-0.5 text-caption-md-medium text-accent-primary">
        <PulseDot />
        {t("agents.runs.working")}
      </span>
    </Tooltip>
  );
}

/** A small pulsing dot on a list row or board card while an agent works on it. Batched, see `live-runs.ts`. */
export function AgentLiveDot({
  workspaceSlug,
  issueId,
  className,
}: {
  workspaceSlug: string | undefined;
  issueId: string;
  className?: string;
}) {
  const { t } = useTranslation();
  const run = useLiveAgentRun(workspaceSlug, issueId);
  if (!run) return null;
  return (
    <Tooltip label={run.agent ? t("agents.runs.working_named", { agent: run.agent.name }) : t("agents.runs.working")}>
      <span className={cn("inline-flex shrink-0 items-center", className)} aria-label={t("agents.runs.working")}>
        <PulseDot />
      </span>
    </Tooltip>
  );
}
