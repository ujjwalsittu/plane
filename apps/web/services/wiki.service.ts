/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TWikiCollection, TWikiPage } from "@plane/types";
import { APIService } from "@/services/api.service";

/** Workspace pages (not tied to a project) and the collections they're filed in. */
export class WikiService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private base(workspaceSlug: string) {
    return `/api/workspaces/${workspaceSlug}/wiki`;
  }

  private async call<T>(promise: Promise<{ data: T } | undefined>): Promise<T> {
    try {
      const response = await promise;
      return response?.data as T;
    } catch (error) {
      throw (error as { response?: { data?: unknown } })?.response?.data;
    }
  }

  async listPages(workspaceSlug: string, archived = false): Promise<TWikiPage[]> {
    const data = await this.call<{ results: TWikiPage[] }>(
      this.get(`${this.base(workspaceSlug)}/pages/`, { params: { archived, per_page: 500 } })
    );
    return data?.results ?? [];
  }

  getPage(workspaceSlug: string, pageId: string): Promise<TWikiPage> {
    return this.call(this.get(`${this.base(workspaceSlug)}/pages/${pageId}/`));
  }

  createPage(
    workspaceSlug: string,
    data: { name: string; collection_id?: string | null; parent_id?: string | null }
  ): Promise<TWikiPage> {
    return this.call(this.post(`${this.base(workspaceSlug)}/pages/`, data));
  }

  updatePage(
    workspaceSlug: string,
    pageId: string,
    data: Partial<Pick<TWikiPage, "name" | "description_html" | "access">>
  ): Promise<TWikiPage> {
    return this.call(this.patch(`${this.base(workspaceSlug)}/pages/${pageId}/`, data));
  }

  archivePage(workspaceSlug: string, pageId: string): Promise<void> {
    return this.call(this.post(`${this.base(workspaceSlug)}/pages/${pageId}/archive/`));
  }

  restorePage(workspaceSlug: string, pageId: string): Promise<void> {
    return this.call(this.delete(`${this.base(workspaceSlug)}/pages/${pageId}/archive/`));
  }

  deletePage(workspaceSlug: string, pageId: string): Promise<void> {
    return this.call(this.delete(`${this.base(workspaceSlug)}/pages/${pageId}/`));
  }

  listCollections(workspaceSlug: string): Promise<TWikiCollection[]> {
    return this.call(this.get(`${this.base(workspaceSlug)}/collections/`));
  }

  createCollection(workspaceSlug: string, data: { name: string; access: 0 | 1 }): Promise<TWikiCollection> {
    return this.call(this.post(`${this.base(workspaceSlug)}/collections/`, data));
  }

  deleteCollection(workspaceSlug: string, collectionId: string): Promise<void> {
    return this.call(
      this.delete(`${this.base(workspaceSlug)}/collections/${collectionId}/`, undefined, {
        params: { archive_pages: false },
      })
    );
  }

  /** File a page into a collection (moving it out of any other). */
  async setCollection(workspaceSlug: string, page: TWikiPage, collectionId: string | null): Promise<void> {
    if (page.collection_id && page.page_collection_id) {
      const path = `${this.base(workspaceSlug)}/collections/${page.collection_id}/pages/${page.page_collection_id}/`;
      if (collectionId) await this.call(this.patch(path, { collection: collectionId }));
      else await this.call(this.delete(path));
      return;
    }
    if (collectionId)
      await this.call(
        this.post(`${this.base(workspaceSlug)}/collections/${collectionId}/pages/`, { page_ids: [page.id] })
      );
  }
}
