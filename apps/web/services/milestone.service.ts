/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type {
  TIssue,
  TIssueType,
  TIssueTypeFormData,
  TMilestone,
  TMilestoneFormData,
  TProjectOverview,
  TProjectOverviewUpdate,
  TProjectTag,
  TWorkItemPageLink,
} from "@plane/types";
import { APIService } from "@/services/api.service";

export class MilestoneService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private base(workspaceSlug: string, projectId: string) {
    return `/api/workspaces/${workspaceSlug}/projects/${projectId}`;
  }

  async list(workspaceSlug: string, projectId: string): Promise<TMilestone[]> {
    return this.get(`${this.base(workspaceSlug, projectId)}/milestones/`)
      .then((res) => res?.data)
      .catch((err) => {
        throw err?.response?.data;
      });
  }

  async retrieve(workspaceSlug: string, projectId: string, milestoneId: string): Promise<TMilestone> {
    return this.get(`${this.base(workspaceSlug, projectId)}/milestones/${milestoneId}/`)
      .then((res) => res?.data)
      .catch((err) => {
        throw err?.response?.data;
      });
  }

  async create(workspaceSlug: string, projectId: string, data: Partial<TMilestoneFormData>): Promise<TMilestone> {
    return this.post(`${this.base(workspaceSlug, projectId)}/milestones/`, data)
      .then((res) => res?.data)
      .catch((err) => {
        throw err?.response?.data;
      });
  }

  async update(
    workspaceSlug: string,
    projectId: string,
    milestoneId: string,
    data: Partial<TMilestoneFormData>
  ): Promise<TMilestone> {
    return this.patch(`${this.base(workspaceSlug, projectId)}/milestones/${milestoneId}/`, data)
      .then((res) => res?.data)
      .catch((err) => {
        throw err?.response?.data;
      });
  }

  async remove(workspaceSlug: string, projectId: string, milestoneId: string): Promise<void> {
    return this.delete(`${this.base(workspaceSlug, projectId)}/milestones/${milestoneId}/`)
      .then((res) => res?.data)
      .catch((err) => {
        throw err?.response?.data;
      });
  }

  async addIssues(workspaceSlug: string, projectId: string, milestoneId: string, issueIds: string[]): Promise<void> {
    return this.post(`${this.base(workspaceSlug, projectId)}/milestones/${milestoneId}/milestone-issues/`, {
      issues: issueIds,
    })
      .then((res) => res?.data)
      .catch((err) => {
        throw err?.response?.data;
      });
  }

  /** Work items of a project matching legacy filter params (e.g. milestone, issue_type, parent). */
  async listIssues(workspaceSlug: string, projectId: string, params: Record<string, string>): Promise<TIssue[]> {
    return this.get(`${this.base(workspaceSlug, projectId)}/issues/`, {
      params: { per_page: 1000, cursor: "1000:0:0", ...params },
    })
      .then((res) => {
        const results = res?.data?.results;
        return Array.isArray(results) ? (results as TIssue[]) : [];
      })
      .catch((err) => {
        throw err?.response?.data;
      });
  }

  async listIssueTypes(workspaceSlug: string, projectId: string): Promise<TIssueType[]> {
    return this.get(`${this.base(workspaceSlug, projectId)}/issue-types/`)
      .then((res) => res?.data)
      .catch((err) => {
        throw err?.response?.data;
      });
  }

  async createIssueType(
    workspaceSlug: string,
    projectId: string,
    data: Partial<TIssueTypeFormData>
  ): Promise<TIssueType> {
    return this.post(`${this.base(workspaceSlug, projectId)}/issue-types/`, data)
      .then((res) => res?.data)
      .catch((err) => {
        throw err?.response?.data;
      });
  }

  async updateIssueType(
    workspaceSlug: string,
    projectId: string,
    issueTypeId: string,
    data: Partial<TIssueType>
  ): Promise<TIssueType> {
    return this.patch(`${this.base(workspaceSlug, projectId)}/issue-types/${issueTypeId}/`, data)
      .then((res) => res?.data)
      .catch((err) => {
        throw err?.response?.data;
      });
  }

  async deleteIssueType(workspaceSlug: string, projectId: string, issueTypeId: string): Promise<void> {
    return this.delete(`${this.base(workspaceSlug, projectId)}/issue-types/${issueTypeId}/`)
      .then((res) => res?.data)
      .catch((err) => {
        throw err?.response?.data;
      });
  }

  async getOverview(workspaceSlug: string, projectId: string): Promise<TProjectOverview> {
    return this.get(`${this.base(workspaceSlug, projectId)}/overview/`)
      .then((res) => res?.data)
      .catch((err) => {
        throw err?.response?.data;
      });
  }

  async updateOverview(
    workspaceSlug: string,
    projectId: string,
    data: TProjectOverviewUpdate
  ): Promise<TProjectOverview> {
    return this.patch(`${this.base(workspaceSlug, projectId)}/overview/`, data)
      .then((res) => res?.data)
      .catch((err) => {
        throw err?.response?.data;
      });
  }

  async listProjectTags(workspaceSlug: string): Promise<TProjectTag[]> {
    return this.get(`/api/workspaces/${workspaceSlug}/project-tags/`)
      .then((res) => res?.data)
      .catch((err) => {
        throw err?.response?.data;
      });
  }

  async createProjectTag(workspaceSlug: string, data: Partial<TProjectTag>): Promise<TProjectTag> {
    return this.post(`/api/workspaces/${workspaceSlug}/project-tags/`, data)
      .then((res) => res?.data)
      .catch((err) => {
        throw err?.response?.data;
      });
  }

  // pages linked to a work item
  async listWorkItemPages(workspaceSlug: string, projectId: string, issueId: string): Promise<TWorkItemPageLink[]> {
    return this.get(`/api/workspaces/${workspaceSlug}/projects/${projectId}/issues/${issueId}/pages/`)
      .then((res) => res?.data)
      .catch((err) => {
        throw err?.response?.data;
      });
  }

  async linkWorkItemPage(
    workspaceSlug: string,
    projectId: string,
    issueId: string,
    pageId: string
  ): Promise<TWorkItemPageLink> {
    return this.post(`/api/workspaces/${workspaceSlug}/projects/${projectId}/issues/${issueId}/pages/`, {
      page_id: pageId,
    })
      .then((res) => res?.data)
      .catch((err) => {
        throw err?.response?.data;
      });
  }

  async unlinkWorkItemPage(workspaceSlug: string, projectId: string, issueId: string, linkId: string): Promise<void> {
    return this.delete(`/api/workspaces/${workspaceSlug}/projects/${projectId}/issues/${issueId}/pages/${linkId}/`)
      .then(() => undefined)
      .catch((err) => {
        throw err?.response?.data;
      });
  }
}
