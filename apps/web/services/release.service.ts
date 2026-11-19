/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TRelease, TReleaseLabel, TReleaseTag, TReleaseWorkItem } from "@plane/types";
import { APIService } from "@/services/api.service";

type TPage<T> = { results: T[] };

/** Releases, their version tags and the workspace's release label palette. */
export class ReleaseService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private base(workspaceSlug: string) {
    return `/api/workspaces/${workspaceSlug}/releases`;
  }

  private async call<T>(promise: Promise<{ data: T } | undefined>): Promise<T> {
    try {
      const response = await promise;
      return response?.data as T;
    } catch (error) {
      throw (error as { response?: { data?: unknown } })?.response?.data;
    }
  }

  private async page<T>(url: string): Promise<T[]> {
    const data = await this.call<TPage<T>>(this.get(url, { params: { per_page: 100 } }));
    return data?.results ?? [];
  }

  list(workspaceSlug: string): Promise<TRelease[]> {
    return this.page(`${this.base(workspaceSlug)}/`);
  }

  retrieve(workspaceSlug: string, releaseId: string): Promise<TRelease> {
    return this.call(this.get(`${this.base(workspaceSlug)}/${releaseId}/`));
  }

  create(workspaceSlug: string, data: Partial<TRelease>): Promise<TRelease> {
    return this.call(this.post(`${this.base(workspaceSlug)}/`, data));
  }

  update(workspaceSlug: string, releaseId: string, data: Partial<TRelease>): Promise<TRelease> {
    return this.call(this.patch(`${this.base(workspaceSlug)}/${releaseId}/`, data));
  }

  remove(workspaceSlug: string, releaseId: string): Promise<void> {
    return this.call(this.delete(`${this.base(workspaceSlug)}/${releaseId}/`));
  }

  async getChangelog(workspaceSlug: string, releaseId: string): Promise<string> {
    const data = await this.call<{ changelog: { description_html: string } }>(
      this.get(`${this.base(workspaceSlug)}/${releaseId}/changelog/`)
    );
    return data?.changelog?.description_html ?? "<p></p>";
  }

  updateChangelog(workspaceSlug: string, releaseId: string, descriptionHtml: string): Promise<unknown> {
    return this.call(
      this.patch(`${this.base(workspaceSlug)}/${releaseId}/changelog/`, { description_html: descriptionHtml })
    );
  }

  listWorkItems(workspaceSlug: string, releaseId: string): Promise<TReleaseWorkItem[]> {
    return this.page(`${this.base(workspaceSlug)}/${releaseId}/work-items/`);
  }

  addWorkItems(workspaceSlug: string, releaseId: string, ids: string[]): Promise<unknown> {
    return this.call(this.post(`${this.base(workspaceSlug)}/${releaseId}/work-items/`, { work_item_ids: ids }));
  }

  removeWorkItems(workspaceSlug: string, releaseId: string, ids: string[]): Promise<void> {
    return this.call(this.delete(`${this.base(workspaceSlug)}/${releaseId}/work-items/`, { work_item_ids: ids }));
  }

  attachLabels(workspaceSlug: string, releaseId: string, ids: string[]): Promise<unknown> {
    return this.call(this.post(`${this.base(workspaceSlug)}/${releaseId}/labels/`, { label_ids: ids }));
  }

  detachLabels(workspaceSlug: string, releaseId: string, ids: string[]): Promise<void> {
    return this.call(this.delete(`${this.base(workspaceSlug)}/${releaseId}/labels/`, { label_ids: ids }));
  }

  listTags(workspaceSlug: string): Promise<TReleaseTag[]> {
    return this.page(`${this.base(workspaceSlug)}/tags/`);
  }

  createTag(workspaceSlug: string, data: Partial<TReleaseTag>): Promise<TReleaseTag> {
    return this.call(this.post(`${this.base(workspaceSlug)}/tags/`, data));
  }

  deleteTag(workspaceSlug: string, tagId: string): Promise<void> {
    return this.call(this.delete(`${this.base(workspaceSlug)}/tags/${tagId}/`));
  }

  listLabels(workspaceSlug: string): Promise<TReleaseLabel[]> {
    return this.page(`${this.base(workspaceSlug)}/labels/`);
  }

  createLabel(workspaceSlug: string, data: Partial<TReleaseLabel>): Promise<TReleaseLabel> {
    return this.call(this.post(`${this.base(workspaceSlug)}/labels/`, data));
  }

  deleteLabel(workspaceSlug: string, labelId: string): Promise<void> {
    return this.call(this.delete(`${this.base(workspaceSlug)}/labels/${labelId}/`));
  }
}
