/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TTemplate, TTemplateKind, TTemplateUseResult } from "@plane/types";
import { APIService } from "@/services/api.service";

export type TTemplateInput = Partial<Pick<TTemplate, "name" | "description_html" | "template_data">> & {
  kind?: TTemplateKind;
  project_id?: string | null;
};

/** Work item, page and project templates, and creating things from them. */
export class TemplateService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private base(workspaceSlug: string) {
    return `/api/workspaces/${workspaceSlug}/templates`;
  }

  private async call<T>(promise: Promise<{ data: T } | undefined>): Promise<T> {
    try {
      const response = await promise;
      return response?.data as T;
    } catch (error) {
      throw (error as { response?: { data?: unknown } })?.response?.data;
    }
  }

  list(workspaceSlug: string, params: { kind?: TTemplateKind; project_id?: string } = {}): Promise<TTemplate[]> {
    return this.call(this.get(`${this.base(workspaceSlug)}/`, { params }));
  }

  retrieve(workspaceSlug: string, templateId: string): Promise<TTemplate> {
    return this.call(this.get(`${this.base(workspaceSlug)}/${templateId}/`));
  }

  create(workspaceSlug: string, data: TTemplateInput): Promise<TTemplate> {
    return this.call(this.post(`${this.base(workspaceSlug)}/`, data));
  }

  update(workspaceSlug: string, templateId: string, data: TTemplateInput): Promise<TTemplate> {
    return this.call(this.patch(`${this.base(workspaceSlug)}/${templateId}/`, data));
  }

  remove(workspaceSlug: string, templateId: string): Promise<void> {
    return this.call(this.delete(`${this.base(workspaceSlug)}/${templateId}/`));
  }

  use(
    workspaceSlug: string,
    templateId: string,
    data: { project_id?: string; name?: string; identifier?: string }
  ): Promise<TTemplateUseResult> {
    return this.call(this.post(`${this.base(workspaceSlug)}/${templateId}/use/`, data));
  }
}
