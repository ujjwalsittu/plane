/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TTeam, TTeamWorkItem, TTeamWorkload } from "@plane/types";
import { APIService } from "@/services/api.service";

type TPage<T> = { results: T[] };

export type TTeamWorkFilters = {
  view?: "assigned" | "unassigned";
  state_group?: string;
  member_id?: string;
  project_id?: string;
};

/** Teams: groups of workspace members, their projects and their work. */
export class TeamspaceService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private base(workspaceSlug: string) {
    return `/api/workspaces/${workspaceSlug}/teamspaces`;
  }

  private async call<T>(promise: Promise<{ data: T } | undefined>): Promise<T> {
    try {
      const response = await promise;
      return response?.data as T;
    } catch (error) {
      throw (error as { response?: { data?: unknown } })?.response?.data;
    }
  }

  private async page<T>(url: string, params: Record<string, unknown> = {}): Promise<T[]> {
    const data = await this.call<TPage<T>>(this.get(url, { params: { per_page: 100, ...params } }));
    return data?.results ?? [];
  }

  list(workspaceSlug: string): Promise<TTeam[]> {
    return this.page(`${this.base(workspaceSlug)}/`);
  }

  retrieve(workspaceSlug: string, teamId: string): Promise<TTeam> {
    return this.call(this.get(`${this.base(workspaceSlug)}/${teamId}/`));
  }

  create(workspaceSlug: string, data: Partial<TTeam>): Promise<TTeam> {
    return this.call(this.post(`${this.base(workspaceSlug)}/`, data));
  }

  update(workspaceSlug: string, teamId: string, data: Partial<TTeam>): Promise<TTeam> {
    return this.call(this.patch(`${this.base(workspaceSlug)}/${teamId}/`, data));
  }

  remove(workspaceSlug: string, teamId: string): Promise<void> {
    return this.call(this.delete(`${this.base(workspaceSlug)}/${teamId}/`));
  }

  addMembers(workspaceSlug: string, teamId: string, memberIds: string[]) {
    return this.call(this.post(`${this.base(workspaceSlug)}/${teamId}/members/`, { member_ids: memberIds }));
  }

  removeMembers(workspaceSlug: string, teamId: string, memberIds: string[]) {
    return this.call(this.delete(`${this.base(workspaceSlug)}/${teamId}/members/`, { member_ids: memberIds }));
  }

  addProjects(workspaceSlug: string, teamId: string, projectIds: string[]) {
    return this.call(this.post(`${this.base(workspaceSlug)}/${teamId}/projects/`, { project_ids: projectIds }));
  }

  removeProjects(workspaceSlug: string, teamId: string, projectIds: string[]) {
    return this.call(this.delete(`${this.base(workspaceSlug)}/${teamId}/projects/`, { project_ids: projectIds }));
  }

  workItems(workspaceSlug: string, teamId: string, filters: TTeamWorkFilters): Promise<TTeamWorkItem[]> {
    return this.page(`${this.base(workspaceSlug)}/${teamId}/work-items/`, filters);
  }

  workload(workspaceSlug: string, teamId: string): Promise<TTeamWorkload> {
    return this.call(this.get(`${this.base(workspaceSlug)}/${teamId}/workload/`));
  }
}
