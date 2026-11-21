/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import useSWR from "swr";
import type { TAgentRun } from "@plane/types";
import { AgentsService } from "@/services/agents.service";

const service = new AgentsService();

/** Poll quickly while an agent is working on the work item, otherwise refresh on focus only. */
export const AGENT_RUNS_LIVE_REFRESH_MS = 5000;

export const getAgentRunsKey = (issueId: string) => `WORK_ITEM_AGENT_RUNS_${issueId}`;
export const getAgentRunKey = (runId: string) => `WORK_ITEM_AGENT_RUN_${runId}`;

export const hasLiveRun = (runs: TAgentRun[] | undefined) => !!runs?.some((run) => run.is_live);

/** A work item's runs, newest first. Every caller shares one request per work item. */
export const useAgentRuns = (workspaceSlug: string, projectId: string, issueId: string) =>
  useSWR(getAgentRunsKey(issueId), () => service.getRuns(workspaceSlug, projectId, issueId), {
    refreshInterval: (runs) => (hasLiveRun(runs) ? AGENT_RUNS_LIVE_REFRESH_MS : 0),
    revalidateOnFocus: true,
  });
