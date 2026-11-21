/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TAgentAuditEntry, TAISettings, TWorkspaceAgent, TWorkspaceAgentPayload } from "@plane/types";
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

  setupCloudAgents(workspaceSlug: string): Promise<TAISettings> {
    return this.call(this.post(this.url(workspaceSlug, "ai-settings/cloud-agents/")));
  }
}

/** The first message in a `{field: message}` or `{error: message}` error body. */
export const agentsErrorMessage = (error: unknown): string | undefined => {
  if (!error || typeof error !== "object") return undefined;
  const values = Object.values(error as Record<string, unknown>);
  const first = values.find((v) => typeof v === "string");
  return first as string | undefined;
};
