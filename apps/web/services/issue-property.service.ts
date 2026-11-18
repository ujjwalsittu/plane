/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TIssueProperty, TIssuePropertyCreate, TIssuePropertyValueRow } from "@plane/types";
import { APIService } from "@/services/api.service";

/** Custom work item properties: a project's definitions and a work item's values. */
export class IssuePropertyService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private base(workspaceSlug: string, projectId: string) {
    return `/api/workspaces/${workspaceSlug}/projects/${projectId}`;
  }

  private async call<T>(promise: Promise<{ data: T } | undefined>): Promise<T> {
    try {
      const response = await promise;
      return response?.data as T;
    } catch (error) {
      throw (error as { response?: { data?: unknown } })?.response?.data;
    }
  }

  list(workspaceSlug: string, projectId: string): Promise<TIssueProperty[]> {
    return this.call(this.get(`${this.base(workspaceSlug, projectId)}/issue-properties/`));
  }

  create(workspaceSlug: string, projectId: string, data: TIssuePropertyCreate): Promise<TIssueProperty> {
    return this.call(this.post(`${this.base(workspaceSlug, projectId)}/issue-properties/`, data));
  }

  remove(workspaceSlug: string, projectId: string, propertyId: string): Promise<void> {
    return this.call(this.delete(`${this.base(workspaceSlug, projectId)}/issue-properties/${propertyId}/`));
  }

  listValues(workspaceSlug: string, projectId: string, issueId: string): Promise<TIssuePropertyValueRow[]> {
    return this.call(this.get(`${this.base(workspaceSlug, projectId)}/issues/${issueId}/property-values/`));
  }

  setValue(
    workspaceSlug: string,
    projectId: string,
    issueId: string,
    propertyId: string,
    value: string | number | boolean | string[] | null
  ): Promise<TIssuePropertyValueRow[]> {
    return this.call(
      this.put(`${this.base(workspaceSlug, projectId)}/issues/${issueId}/property-values/`, {
        property_id: propertyId,
        value,
      })
    );
  }
}
