/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TBrief, TDecisionRequest, TWorkItemWaiting } from "@plane/types";
import { APIService } from "@/services/api.service";

/** The Brief, decision requests and "waiting on" markers. */
export class SupervisionService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private base(workspaceSlug: string) {
    return `/api/workspaces/${workspaceSlug}`;
  }

  private waitingUrl(workspaceSlug: string, projectId: string, issueId: string) {
    return `${this.base(workspaceSlug)}/projects/${projectId}/issues/${issueId}/waiting/`;
  }

  private async call<T>(promise: Promise<{ data: T } | undefined>): Promise<T> {
    try {
      const response = await promise;
      return response?.data as T;
    } catch (error) {
      throw (error as { response?: { data?: unknown } })?.response?.data;
    }
  }

  getBrief(workspaceSlug: string): Promise<TBrief> {
    return this.call(this.get(`${this.base(workspaceSlug)}/brief/`));
  }

  markSeen(workspaceSlug: string): Promise<unknown> {
    return this.call(this.post(`${this.base(workspaceSlug)}/brief/seen/`));
  }

  listOpenDecisions(workspaceSlug: string): Promise<TDecisionRequest[]> {
    return this.call(this.get(`${this.base(workspaceSlug)}/decisions/`, { params: { status: "open" } }));
  }

  /** Rejects with the error body; `conflict: true` is added when the decision was already answered (409). */
  async answerDecision(
    workspaceSlug: string,
    projectId: string,
    issueId: string,
    decisionId: string,
    answer: string
  ): Promise<TDecisionRequest> {
    try {
      const response = await this.post(
        `${this.base(workspaceSlug)}/projects/${projectId}/issues/${issueId}/decisions/${decisionId}/answer/`,
        { answer }
      );
      return response?.data as TDecisionRequest;
    } catch (error) {
      const response = (error as { response?: { status?: number; data?: object } })?.response;
      throw response?.status === 409 ? { ...response.data, conflict: true } : response?.data;
    }
  }

  getWaiting(workspaceSlug: string, projectId: string, issueId: string): Promise<TWorkItemWaiting | null> {
    return this.call(this.get(this.waitingUrl(workspaceSlug, projectId, issueId)));
  }

  setWaiting(
    workspaceSlug: string,
    projectId: string,
    issueId: string,
    data: { waiting_on_user?: string | null; waiting_on_text?: string; note?: string }
  ): Promise<TWorkItemWaiting> {
    return this.call(this.put(this.waitingUrl(workspaceSlug, projectId, issueId), data));
  }

  clearWaiting(workspaceSlug: string, projectId: string, issueId: string): Promise<void> {
    return this.call(this.delete(this.waitingUrl(workspaceSlug, projectId, issueId)));
  }
}
