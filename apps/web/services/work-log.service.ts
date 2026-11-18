/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TWorkLog } from "@plane/types";
import { APIService } from "@/services/api.service";

/** Time logged on work items, in minutes. */
export class WorkLogService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private base(workspaceSlug: string, projectId: string, issueId: string) {
    return `/api/workspaces/${workspaceSlug}/projects/${projectId}/issues/${issueId}/work-logs/`;
  }

  private async call<T>(promise: Promise<{ data: T } | undefined>): Promise<T> {
    try {
      const response = await promise;
      return response?.data as T;
    } catch (error) {
      throw (error as { response?: { data?: unknown } })?.response?.data;
    }
  }

  list(workspaceSlug: string, projectId: string, issueId: string): Promise<TWorkLog[]> {
    return this.call(this.get(this.base(workspaceSlug, projectId, issueId)));
  }

  create(
    workspaceSlug: string,
    projectId: string,
    issueId: string,
    data: { duration: number; description: string }
  ): Promise<TWorkLog> {
    return this.call(this.post(this.base(workspaceSlug, projectId, issueId), data));
  }

  remove(workspaceSlug: string, projectId: string, issueId: string, workLogId: string): Promise<void> {
    return this.call(this.delete(`${this.base(workspaceSlug, projectId, issueId)}${workLogId}/`));
  }
}
