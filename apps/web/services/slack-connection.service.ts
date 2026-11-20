/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TSlackConnection } from "@plane/types";
import { APIService } from "@/services/api.service";

/** The workspace's Slack connection. The server never returns the bot token. */
export class SlackConnectionService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private url(workspaceSlug: string) {
    return `/api/workspaces/${workspaceSlug}/slack/`;
  }

  private async call<T>(promise: Promise<{ data: T } | undefined>): Promise<T> {
    try {
      const response = await promise;
      return response?.data as T;
    } catch (error) {
      throw (error as { response?: { data?: unknown } })?.response?.data;
    }
  }

  getConnection(workspaceSlug: string): Promise<TSlackConnection> {
    return this.call(this.get(this.url(workspaceSlug)));
  }

  connect(workspaceSlug: string, botToken: string): Promise<TSlackConnection> {
    return this.call(this.put(this.url(workspaceSlug), { bot_token: botToken }));
  }

  disconnect(workspaceSlug: string): Promise<void> {
    return this.call(this.delete(this.url(workspaceSlug)));
  }
}
