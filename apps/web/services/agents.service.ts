/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type {
  TAgentAuditEntry,
  TAgentLoop,
  TAgentLoopPayload,
  TAgentRun,
  TAISettings,
  TWorkspaceAgent,
  TWorkspaceAgentPayload,
} from "@plane/types";
import { APIService } from "@/services/api.service";

/** A new agent comes back with its token, which is never returned again. */
export type TCreatedWorkspaceAgent = TWorkspaceAgent & { token: string };

/** The workspace's agents and Claude (AI) settings. The server never returns the key or an existing token. */
export class AgentsService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private url(workspaceSlug: string, path = "") {
    return `/api/workspaces/${workspaceSlug}/${path}`;
  }

  private async call<T>(promise: Promise<{ data: T } | undefined>): Promise<T> {
    try {
      const response = await promise;
      return response?.data as T;
    } catch (error) {
      throw (error as { response?: { data?: unknown } })?.response?.data;
    }
  }

  getAgents(workspaceSlug: string): Promise<TWorkspaceAgent[]> {
    return this.call(this.get(this.url(workspaceSlug, "agents/")));
  }

  createAgent(workspaceSlug: string, data: TWorkspaceAgentPayload): Promise<TCreatedWorkspaceAgent> {
    return this.call(this.post(this.url(workspaceSlug, "agents/"), data));
  }

  updateAgent(workspaceSlug: string, agentId: string, data: Partial<TWorkspaceAgentPayload>): Promise<TWorkspaceAgent> {
    return this.call(this.patch(this.url(workspaceSlug, `agents/${agentId}/`), data));
  }

  deactivateAgent(workspaceSlug: string, agentId: string): Promise<void> {
    return this.call(this.delete(this.url(workspaceSlug, `agents/${agentId}/`)));
  }

  rotateToken(workspaceSlug: string, agentId: string): Promise<{ token: string }> {
    return this.call(this.post(this.url(workspaceSlug, `agents/${agentId}/rotate-token/`)));
  }

  getAudit(workspaceSlug: string, agentId: string): Promise<TAgentAuditEntry[]> {
    return this.call(this.get(this.url(workspaceSlug, `agents/${agentId}/audit/`)));
  }

  getAISettings(workspaceSlug: string): Promise<TAISettings> {
    return this.call(this.get(this.url(workspaceSlug, "ai-settings/")));
  }

  updateAISettings(
    workspaceSlug: string,
    data: { api_key?: string; model?: string; monthly_limit_cents?: number | null }
  ): Promise<TAISettings> {
    return this.call(this.put(this.url(workspaceSlug, "ai-settings/"), data));
  }

  clearAIKey(workspaceSlug: string): Promise<TAISettings> {
    return this.call(this.delete(this.url(workspaceSlug, "ai-settings/")));
  }

  private runsUrl(workspaceSlug: string, projectId: string, issueId: string, path = "") {
    return this.url(workspaceSlug, `projects/${projectId}/issues/${issueId}/agent-runs/${path}`);
  }

  getRuns(workspaceSlug: string, projectId: string, issueId: string): Promise<TAgentRun[]> {
    return this.call(this.get(this.runsUrl(workspaceSlug, projectId, issueId)));
  }

  getRun(workspaceSlug: string, projectId: string, issueId: string, runId: string): Promise<TAgentRun> {
    return this.call(this.get(this.runsUrl(workspaceSlug, projectId, issueId, `${runId}/`)));
  }

  delegate(
    workspaceSlug: string,
    projectId: string,
    issueId: string,
    data: { agent_id: string; instructions: string }
  ): Promise<TAgentRun> {
    return this.call(this.post(this.runsUrl(workspaceSlug, projectId, issueId, "delegate/"), data));
  }

  followUp(workspaceSlug: string, projectId: string, issueId: string, runId: string, text: string): Promise<TAgentRun> {
    return this.call(this.post(this.runsUrl(workspaceSlug, projectId, issueId, `${runId}/follow-up/`), { text }));
  }

  cancelRun(workspaceSlug: string, projectId: string, issueId: string, runId: string): Promise<TAgentRun> {
    return this.call(this.post(this.runsUrl(workspaceSlug, projectId, issueId, `${runId}/cancel/`)));
  }

  /** The live run per work item id, for up to 200 ids in one request, and whether anything in the workspace can be live. */
  getLiveRuns(workspaceSlug: string, issueIds: string[]): Promise<{ runs: Record<string, TAgentRun>; poll: boolean }> {
    return this.call(
      this.get(this.url(workspaceSlug, "agent-runs/live/"), { params: { issue_ids: issueIds.join(","), meta: 1 } })
    );
  }

  setupCloudAgents(workspaceSlug: string): Promise<TAISettings> {
    return this.call(this.post(this.url(workspaceSlug, "ai-settings/cloud-agents/")));
  }

  private loopsUrl(workspaceSlug: string, projectId: string, path = "") {
    return this.url(workspaceSlug, `projects/${projectId}/loops/${path}`);
  }

  getLoops(workspaceSlug: string, projectId: string): Promise<TAgentLoop[]> {
    return this.call(this.get(this.loopsUrl(workspaceSlug, projectId)));
  }

  createLoop(workspaceSlug: string, projectId: string, data: TAgentLoopPayload): Promise<TAgentLoop> {
    return this.call(this.post(this.loopsUrl(workspaceSlug, projectId), data));
  }

  updateLoop(
    workspaceSlug: string,
    projectId: string,
    loopId: string,
    data: Partial<TAgentLoopPayload>
  ): Promise<TAgentLoop> {
    return this.call(this.patch(this.loopsUrl(workspaceSlug, projectId, `${loopId}/`), data));
  }

  deleteLoop(workspaceSlug: string, projectId: string, loopId: string): Promise<void> {
    return this.call(this.delete(this.loopsUrl(workspaceSlug, projectId, `${loopId}/`)));
  }

  /** Start the loop now; refused (409) while one of its runs is still open. */
  runLoopNow(workspaceSlug: string, projectId: string, loopId: string): Promise<TAgentRun> {
    return this.call(this.post(this.loopsUrl(workspaceSlug, projectId, `${loopId}/run/`)));
  }

  /** The loop's runs, newest first (50). */
  getLoopRuns(workspaceSlug: string, projectId: string, loopId: string): Promise<TAgentRun[]> {
    return this.call(this.get(this.loopsUrl(workspaceSlug, projectId, `${loopId}/runs/`)));
  }

  getLoopRun(workspaceSlug: string, projectId: string, loopId: string, runId: string): Promise<TAgentRun> {
    return this.call(this.get(this.loopsUrl(workspaceSlug, projectId, `${loopId}/runs/${runId}/`)));
  }

  followUpLoopRun(
    workspaceSlug: string,
    projectId: string,
    loopId: string,
    runId: string,
    text: string
  ): Promise<TAgentRun> {
    return this.call(
      this.post(this.loopsUrl(workspaceSlug, projectId, `${loopId}/runs/${runId}/follow-up/`), { text })
    );
  }

  cancelLoopRun(workspaceSlug: string, projectId: string, loopId: string, runId: string): Promise<TAgentRun> {
    return this.call(this.post(this.loopsUrl(workspaceSlug, projectId, `${loopId}/runs/${runId}/cancel/`)));
  }
}

/** The first message in a `{field: message}` or `{error: message}` error body. */
export const agentsErrorMessage = (error: unknown): string | undefined => {
  if (!error || typeof error !== "object") return undefined;
  const values = Object.values(error as Record<string, unknown>);
  const first = values.find((v) => typeof v === "string");
  return first as string | undefined;
};
