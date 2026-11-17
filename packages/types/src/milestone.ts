/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export type TMilestone = {
  id: string;
  title: string;
  description: string;
  target_date: string | null;
  sort_order: number;
  external_source: string | null;
  external_id: string | null;
  project_id: string;
  workspace_id: string;
  created_at: string;
  updated_at: string;
  created_by: string | null;
  updated_by: string | null;
  // progress
  total_issues: number;
  completed_issues: number;
  cancelled_issues: number;
  started_issues: number;
  unstarted_issues: number;
  backlog_issues: number;
};

export type TMilestoneFormData = Pick<TMilestone, "title" | "description" | "target_date">;

export type TIssueType = {
  id: string;
  name: string;
  description: string;
  logo_props: Record<string, unknown>;
  is_epic: boolean;
  is_default: boolean;
  is_active: boolean;
  level: number;
  external_source: string | null;
  external_id: string | null;
  workspace_id: string;
  created_at: string;
  updated_at: string;
};

export type TIssueTypeFormData = Pick<TIssueType, "name" | "description" | "is_epic">;

export type TProjectTag = {
  id: string;
  name: string;
  color: string;
};

export type TProjectOverviewLinkedPage = {
  id: string;
  name: string;
  access: number;
  archived_at: string | null;
};

export type TProjectOverview = {
  project_id: string;
  overview_html: string;
  linked_pages: TProjectOverviewLinkedPage[];
  overview_page_ids: string[];
  tags: TProjectTag[];
  updated_at: string | null;
};

export type TProjectOverviewUpdate = Partial<{
  overview_html: string;
  overview_page_ids: string[];
  tag_ids: string[];
}>;
