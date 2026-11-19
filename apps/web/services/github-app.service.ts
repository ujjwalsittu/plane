/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TGitHubIntegration, TGitHubRepository, TGitHubRepositoryLink } from "@plane/types";
import { APIService } from "@/services/api.service";

/** The workspace's GitHub App connection: installations and repository links. */
export class GitHubAppService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private base(workspaceSlug: string) {
    return `/api/workspaces/${workspaceSlug}/github`;
  }

  private async call<T>(promise: Promise<{ data: T } | undefined>): Promise<T> {
    try {
      const response = await promise;
      return response?.data as T;
    } catch (error) {
      throw (error as { response?: { data?: unknown } })?.response?.data;
    }
  }

  getIntegration(workspaceSlug: string): Promise<TGitHubIntegration> {
    return this.call(this.get(`${this.base(workspaceSlug)}/`));
  }

  getInstallUrl(workspaceSlug: string): Promise<{ url: string }> {
    return this.call(this.post(`${this.base(workspaceSlug)}/install-url/`));
  }

  disconnect(workspaceSlug: string, installationId: string): Promise<void> {
    return this.call(this.delete(`${this.base(workspaceSlug)}/installations/${installationId}/`));
  }

  listRepositories(workspaceSlug: string, installationId: string): Promise<TGitHubRepository[]> {
    return this.call(this.get(`${this.base(workspaceSlug)}/installations/${installationId}/repositories/`));
  }

  linkRepository(
    workspaceSlug: string,
    data: { installation: string; project: string; repository_id: number }
  ): Promise<TGitHubRepositoryLink> {
    return this.call(this.post(`${this.base(workspaceSlug)}/links/`, data));
  }

  unlinkRepository(workspaceSlug: string, linkId: string): Promise<void> {
    return this.call(this.delete(`${this.base(workspaceSlug)}/links/${linkId}/`));
  }
}
