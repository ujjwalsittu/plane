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
  /** Present on the workspace tag list: projects carrying this tag. */
  project_ids?: string[];
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

export type TWorkItemPageLink = {
  id: string;
  page: {
    id: string;
    name: string;
    logo_props: Record<string, unknown> | null;
    access: number;
    archived_at: string | null;
  };
  issue: string;
  project: string;
  created_at: string | null;
};

export type TIssuePropertyType =
  | "TEXT"
  | "DATETIME"
  | "DECIMAL"
  | "BOOLEAN"
  | "OPTION"
  | "RELATION"
  | "URL"
  | "EMAIL"
  | "FILE";

export type TIssuePropertyOption = {
  id: string;
  name: string;
  logo_props: { color?: string } | null;
  is_default: boolean;
  sort_order: number;
};

export type TIssueProperty = {
  id: string;
  display_name: string;
  description: string;
  property_type: TIssuePropertyType;
  relation_type: "ISSUE" | "USER" | null;
  is_required: boolean;
  is_multi: boolean;
  is_active: boolean;
  settings: { display_format?: string };
  project: string | null;
  issue_type: string | null;
  options: TIssuePropertyOption[];
};

export type TIssuePropertyCreate = {
  display_name: string;
  property_type: TIssuePropertyType;
  relation_type?: "ISSUE" | "USER";
  is_multi?: boolean;
  issue_type_id?: string | null;
  options?: string[];
};

/** A property that applies to a work item, with its current values (strings, numbers or booleans). */
export type TIssuePropertyValueRow = {
  property: TIssueProperty;
  values: (string | number | boolean | null)[];
};

export type TRelationDefinition = {
  id: string;
  name: string;
  outward: string;
  inward: string;
  color: string | null;
  is_default: boolean;
  is_active: boolean;
};

export type TCustomRelationItem = {
  id: string;
  name: string;
  sequence_id: number;
  project_id: string;
  relation_type: string;
};

export type TWorkLog = {
  id: string;
  issue_id: string;
  duration: number;
  description: string;
  logged_by: string;
  created_at: string | null;
};

export type TWikiCollection = {
  id: string;
  name: string;
  access: 0 | 1;
  current_user_access: 0 | 1 | 2;
  has_pages: boolean;
  owned_by_id: string;
};

export type TWikiPage = {
  id: string;
  name: string;
  description_html: string;
  access: 0 | 1;
  owned_by: string;
  archived_at: string | null;
  parent_id: string | null;
  collection_id: string | null;
  page_collection_id: string | null;
  updated_at: string | null;
};

export type TGitHubInstallation = {
  id: string;
  installation_id: number;
  account_login: string;
  account_type: string;
  account_avatar_url: string;
  repository_selection: string;
  suspended_at: string | null;
  manage_url: string;
  created_at: string | null;
};

export type TGitHubRepositoryLink = {
  id: string;
  installation: string;
  project: string;
  repository_id: number;
  full_name: string;
  html_url: string;
  default_branch: string;
  is_private: boolean;
  created_at: string | null;
};

export type TGitHubRepository = {
  id: number;
  full_name: string;
  html_url: string;
  default_branch: string;
  private: boolean;
};

export type TGitHubIntegration = {
  configured: boolean;
  app_slug: string | null;
  installations: TGitHubInstallation[];
  links: TGitHubRepositoryLink[];
};
