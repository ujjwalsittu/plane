/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TInitiative, TIssue } from "@plane/types";
import { APIService } from "@/services/api.service";

/** Initiatives: workspace-level goals grouping projects and work items. */
export class InitiativeService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private base(workspaceSlug: string) {
    return `/api/workspaces/${workspaceSlug}/initiatives`;
  }

  private async call<T>(promise: Promise<{ data: T } | undefined>): Promise<T> {
    try {
      const response = await promise;
      return response?.data as T;
    } catch (error) {
      throw (error as { response?: { data?: unknown } })?.response?.data;
    }
  }

  async list(workspaceSlug: string): Promise<TInitiative[]> {
    const data = await this.call<{ results: TInitiative[] }>(this.get(`${this.base(workspaceSlug)}/`));
    return data?.results ?? [];
  }

  retrieve(workspaceSlug: string, initiativeId: string): Promise<TInitiative> {
    return this.call(this.get(`${this.base(workspaceSlug)}/${initiativeId}/`));
  }

  create(workspaceSlug: string, data: Partial<TInitiative>): Promise<TInitiative> {
    return this.call(this.post(`${this.base(workspaceSlug)}/`, data));
  }

  update(workspaceSlug: string, initiativeId: string, data: Partial<TInitiative>): Promise<TInitiative> {
    return this.call(this.patch(`${this.base(workspaceSlug)}/${initiativeId}/`, data));
  }

  remove(workspaceSlug: string, initiativeId: string): Promise<void> {
    return this.call(this.delete(`${this.base(workspaceSlug)}/${initiativeId}/`));
  }

  addProjects(workspaceSlug: string, initiativeId: string, projectIds: string[]): Promise<unknown> {
    return this.call(this.post(`${this.base(workspaceSlug)}/${initiativeId}/projects/`, { project_ids: projectIds }));
  }

  removeProjects(workspaceSlug: string, initiativeId: string, projectIds: string[]): Promise<void> {
    return this.call(this.delete(`${this.base(workspaceSlug)}/${initiativeId}/projects/`, { project_ids: projectIds }));
  }

  async listWorkItems(workspaceSlug: string, initiativeId: string): Promise<TIssue[]> {
    const data = await this.call<{ results: TIssue[] }>(
      this.get(`${this.base(workspaceSlug)}/${initiativeId}/work-items/`, { params: { per_page: 100 } })
    );
    return data?.results ?? [];
  }

  addWorkItems(workspaceSlug: string, initiativeId: string, workItemIds: string[]): Promise<unknown> {
    return this.call(
      this.post(`${this.base(workspaceSlug)}/${initiativeId}/work-items/`, { work_item_ids: workItemIds })
    );
  }

  removeWorkItems(workspaceSlug: string, initiativeId: string, workItemIds: string[]): Promise<void> {
    return this.call(
      this.delete(`${this.base(workspaceSlug)}/${initiativeId}/work-items/`, { work_item_ids: workItemIds })
    );
  }
}
