/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TCustomRelationItem, TRelationDefinition } from "@plane/types";
import { APIService } from "@/services/api.service";

/** Workspace relation types and the custom relations of a work item. */
export class RelationDefinitionService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private async call<T>(promise: Promise<{ data: T } | undefined>): Promise<T> {
    try {
      const response = await promise;
      return response?.data as T;
    } catch (error) {
      throw (error as { response?: { data?: unknown } })?.response?.data;
    }
  }

  async listDefinitions(workspaceSlug: string): Promise<TRelationDefinition[]> {
    const data = await this.call<{ results: TRelationDefinition[] }>(
      this.get(`/api/workspaces/${workspaceSlug}/relation-definitions/`)
    );
    return data?.results ?? [];
  }

  createDefinition(
    workspaceSlug: string,
    data: Pick<TRelationDefinition, "name" | "outward" | "inward">
  ): Promise<TRelationDefinition> {
    return this.call(this.post(`/api/workspaces/${workspaceSlug}/relation-definitions/`, data));
  }

  deleteDefinition(workspaceSlug: string, definitionId: string): Promise<void> {
    return this.call(this.delete(`/api/workspaces/${workspaceSlug}/relation-definitions/${definitionId}/`));
  }

  private issueBase(workspaceSlug: string, projectId: string, issueId: string) {
    return `/api/workspaces/${workspaceSlug}/projects/${projectId}/issues/${issueId}/custom-relations/`;
  }

  /** Related work items grouped by the label shown on this work item. */
  listRelations(
    workspaceSlug: string,
    projectId: string,
    issueId: string
  ): Promise<Record<string, TCustomRelationItem[]>> {
    return this.call(this.get(this.issueBase(workspaceSlug, projectId, issueId)));
  }

  addRelations(
    workspaceSlug: string,
    projectId: string,
    issueId: string,
    definitionId: string,
    label: string,
    workItemIds: string[]
  ): Promise<TCustomRelationItem[]> {
    return this.call(
      this.post(this.issueBase(workspaceSlug, projectId, issueId), {
        relation_definition_id: definitionId,
        relation_definition_type: label,
        work_item_ids: workItemIds,
      })
    );
  }

  removeRelation(workspaceSlug: string, projectId: string, issueId: string, relatedId: string): Promise<void> {
    return this.call(this.delete(`${this.issueBase(workspaceSlug, projectId, issueId)}${relatedId}/`));
  }
}
