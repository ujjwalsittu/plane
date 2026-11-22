/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import useSWR from "swr";
import { Button } from "@makeplane/propel/components/button";
import { useTranslation } from "@plane/i18n";
import type { TAgentLoop } from "@plane/types";
import { RunRow } from "@/components/issues/issue-detail-widgets/agent-runs/run-row";
import { AGENT_RUNS_LIVE_REFRESH_MS } from "@/components/issues/issue-detail-widgets/agent-runs/use-agent-runs";
import { AgentsService } from "@/services/agents.service";

const service = new AgentsService();

export const getLoopRunsKey = (loopId: string) => `AGENT_LOOP_RUNS_${loopId}`;

type Props = {
  workspaceSlug: string;
  projectId: string;
  loop: TAgentLoop;
  onClose: () => void;
  /** A run changed (follow-up, cancel), so the loop's last run status may have too. */
  onChanged: () => void;
};

/** A loop's run history, newest first, with the same rows (steps, follow-up, cancel) as a work item's runs. */
export function LoopRuns({ workspaceSlug, projectId, loop, onClose, onChanged }: Props) {
  const { t } = useTranslation();
  const {
    data: runs,
    error,
    mutate,
  } = useSWR(getLoopRunsKey(loop.id), () => service.getLoopRuns(workspaceSlug, projectId, loop.id), {
    refreshInterval: (latest) =>
      latest?.some((run) => ["queued", "running", "waiting"].includes(run.status)) ? AGENT_RUNS_LIVE_REFRESH_MS : 0,
  });

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h4 className="text-h6-medium text-primary">{t("agents.loops.runs.title", { name: loop.name })}</h4>
        <Button variant="ghost" size="sm" stretch="auto" label={t("agents.loops.runs.close")} onClick={onClose} />
      </div>
      {error ? (
        <p className="text-body-xs-regular text-danger-primary">{t("agents.loops.runs.load_error")}</p>
      ) : !runs ? (
        <p className="text-body-xs-regular text-tertiary">{t("loading")}</p>
      ) : runs.length === 0 ? (
        <p className="text-body-xs-regular text-tertiary">{t("agents.loops.runs.empty")}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {runs.map((run) => (
            <RunRow
              key={run.id}
              workspaceSlug={workspaceSlug}
              projectId={projectId}
              loopId={loop.id}
              run={run}
              disabled={false}
              onChanged={() => {
                void mutate();
                onChanged();
              }}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
