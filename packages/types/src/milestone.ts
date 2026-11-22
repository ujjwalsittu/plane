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
  issue_sync: boolean;
  issue_sync_imported_at: string | null;
  created_at: string | null;
};

export type TGitHubRepository = {
  id: number;
  full_name: string;
  html_url: string;
  default_branch: string;
  private: boolean;
};

export type TGitHubAvailableInstallation = {
  installation_id: number;
  account_login: string;
  account_type: string;
  account_avatar_url: string;
  repository_selection: string;
  suspended_at: string | null;
};

export type TGitHubIntegration = {
  configured: boolean;
  app_slug: string | null;
  installations: TGitHubInstallation[];
  links: TGitHubRepositoryLink[];
};

export type TGitHubPullRequestStatus = "open" | "draft" | "merged" | "closed";

export type TWorkItemGitHub = {
  issue: { repository: string; number: number; url: string } | null;
  enabled: boolean;
  branch_name: string;
  pull_requests: {
    id: string;
    repository: string;
    number: number;
    title: string;
    url: string;
    status: TGitHubPullRequestStatus;
    review_state: "" | "approved" | "changes_requested";
    checks_state: "" | "pending" | "success" | "failure";
    author: string;
    head_ref: string;
    base_ref: string;
    updated_at: string | null;
  }[];
  branches: { id: string; repository: string; name: string; url: string }[];
  commits: {
    id: string;
    repository: string;
    sha: string;
    message: string;
    url: string;
    author: string;
    committed_at: string | null;
  }[];
};

export type TGitHubAutomationRule = "draft_state" | "open_state" | "review_requested_state" | "merge_state";

export type TGitHubAutomation = {
  project: string;
  enabled: boolean;
  close_keywords: boolean;
  is_default: boolean;
} & Record<TGitHubAutomationRule, string | null>;

export type TGitHubPerson = { user: string; github_login: string };

export type TInitiativeState = "DRAFT" | "PLANNED" | "ACTIVE" | "COMPLETED" | "CLOSED";

export type TInitiativeProgress = {
  total: number;
  completed: number;
  cancelled: number;
  started: number;
  unstarted: number;
  backlog: number;
  percent: number;
};

export type TInitiative = {
  id: string;
  name: string;
  description_html: string;
  description_stripped: string;
  start_date: string | null;
  end_date: string | null;
  logo_props: Record<string, unknown>;
  state: TInitiativeState;
  lead: string | null;
  workspace: string;
  sort_order: number;
  project_ids: string[];
  work_item_ids: string[];
  progress: TInitiativeProgress;
  created_at: string | null;
  updated_at: string | null;
};

export type TReleaseStatus = "unreleased" | "released" | "cancelled";

export type TReleaseTag = {
  id: string;
  version: string;
  description: string;
  commit_hash: string;
  git_tag: string;
  created_at: string | null;
};

export type TReleaseLabel = { id: string; name: string; color: string; sort_order: number };

export type TRelease = {
  id: string;
  name: string;
  description_html: string;
  status: TReleaseStatus;
  release_date: string | null;
  target_date: string | null;
  lead: string | null;
  tag: string | null;
  tag_version: string | null;
  is_latest: boolean;
  is_prerelease: boolean;
  label_ids: string[];
  progress: { total: number; completed: number; cancelled: number; percent: number };
  created_at: string | null;
};

export type TReleaseWorkItem = {
  id: string;
  name: string;
  project_id: string;
  project_identifier: string;
  sequence_id: number;
  state_group: string | null;
  state_name: string | null;
};

// --- templates ----------------------------------------------------------------------------------

export type TTemplateKind = "workitem" | "page" | "project";

export type TTemplateWorkItemBody = {
  name?: string;
  description_html?: string;
  priority?: "urgent" | "high" | "medium" | "low" | "none";
  state?: string;
  labels?: string[];
  assignees?: string[];
  sub_work_items?: (string | TTemplateWorkItemBody)[];
};

export type TTemplatePageBody = { name?: string; description_html?: string };

export type TTemplateProjectBody = {
  description?: string;
  network?: 0 | 2;
  features?: Partial<Record<"cycles" | "modules" | "views" | "pages" | "intake" | "time_tracking", boolean>>;
  states?: { name: string; group: "backlog" | "unstarted" | "started" | "completed" | "cancelled"; color?: string }[];
  labels?: (string | { name: string; color?: string })[];
  work_items?: TTemplateWorkItemBody[];
  pages?: TTemplatePageBody[];
};

export type TTemplate = {
  id: string;
  name: string;
  kind: TTemplateKind;
  description: string;
  description_html: string;
  logo_props: Record<string, unknown>;
  template_data: TTemplateWorkItemBody & TTemplatePageBody & TTemplateProjectBody;
  project: string | null;
  workspace: string;
  created_at: string;
  updated_at: string;
};

export type TTemplateUseResult = {
  kind: TTemplateKind;
  id: string;
  project_id: string;
  sequence_id?: number;
  identifier?: string;
};

// --- teams --------------------------------------------------------------------------------------

export type TTeam = {
  id: string;
  name: string;
  description_html: string;
  description_stripped: string;
  logo_props: Record<string, unknown>;
  lead: string | null;
  member_ids: string[];
  project_ids: string[];
  workspace: string;
  created_at: string;
  updated_at: string;
};

export type TTeamWorkItem = {
  id: string;
  name: string;
  project_id: string;
  project_identifier: string;
  sequence_id: number;
  priority: string;
  state_id: string | null;
  state_name: string | null;
  state_group: string | null;
  target_date: string | null;
  assignee_ids: string[];
};

export type TTeamWorkload = {
  members: { member_id: string; open: number; started: number; completed: number }[];
  unassigned_open: number;
};

// --- supervision (brief, decisions, waiting) ----------------------------------------------------

export type TSupervisionWorkItem = {
  id: string;
  name: string;
  identifier: string;
  project_id: string;
  project_identifier: string;
  state_group: string | null;
  state_name: string | null;
  priority: string;
  target_date: string | null;
  milestone_id: string | null;
};

export type TDecisionPerson = { id: string; display_name: string };

export type TDecisionRequest = {
  id: string;
  issue_id: string;
  question: string;
  options: string[];
  status: string;
  answer: string | null;
  asked_user: TDecisionPerson | null;
  requested_by: TDecisionPerson | null;
  answered_by: string | null;
  answered_at: string | null;
  created_at: string;
  source: string;
  issue?: TSupervisionWorkItem;
};

export type TBriefWhy = "assigned" | "mentioned" | "decision" | "approval";

/** An agent's risky action held for its owner to approve (a Brief row, not the full approval record). */
export type TAgentApproval = {
  id: string;
  summary: string;
  action: "delete" | "change_dates";
  agent: { id: string; name: string; avatar_url: string | null };
  created_at: string;
};

export type TBriefNeedsMe = {
  /** Null for an approval about something that is not a work item you can see (a cycle, a module). */
  issue: TSupervisionWorkItem | null;
  why: TBriefWhy;
  decision_id: string | null;
  approval?: TAgentApproval;
  due: string | null;
  overdue: boolean;
};

export type TBlockedReasonKind = "blocked_by" | "waiting_on" | "stale";

export type TBlockedItem = {
  issue: TSupervisionWorkItem;
  reasons: { kind: TBlockedReasonKind; detail: string; since: string | null; hidden: boolean }[];
};

export type TBriefDone = {
  project_id: string;
  project_identifier: string;
  items: {
    issue: TSupervisionWorkItem;
    completed_at: string | null;
    by: { id: string | null; display_name: string | null; is_agent: boolean };
  }[];
};

export type TBriefMilestone = {
  id: string;
  title: string;
  project_identifier: string;
  target_date: string | null;
  open: number;
  total: number;
  assigned_to_me_open: number;
};

export type TProjectHealth = "on_track" | "at_risk" | "off_track";

export type TBriefProject = {
  id: string;
  identifier: string;
  name: string;
  health: TProjectHealth;
  latest_update: {
    health: TProjectHealth;
    excerpt: string;
    created_at: string;
    by: { display_name: string | null; is_agent: boolean };
  } | null;
  predicted_finish: string | null;
  target_date: string | null;
};

export type TBrief = {
  since: string | null;
  generated_at: string;
  needs_me: TBriefNeedsMe[];
  blocked: TBlockedItem[];
  done: TBriefDone[];
  milestones_due: TBriefMilestone[];
  projects: TBriefProject[];
};

export type TBriefSummary = {
  text: string | null;
  item_ids: string[];
};

export type TAskSource = {
  kind: "work_item" | "page" | "milestone" | "pull_request";
  id: string;
  identifier: string | null;
  title: string;
  url: string;
};

export type TAskAnswer = {
  answer: string;
  sources: TAskSource[];
};

export type TAskTurn = {
  role: "user" | "assistant";
  content: string;
};

export type TWorkItemWaiting = {
  id: string;
  issue_id: string;
  waiting_on_user: string | null;
  waiting_on_name: string | null;
  waiting_on_text: string;
  note: string;
  since: string | null;
};

export type TSlackConnection = {
  connected: boolean;
  status: "ok" | "broken" | null;
  team_name: string;
  linked_users: number;
  last_error: string;
};

export type TAgentPermission = "read" | "contribute" | "manage";

export type TAgentApprovalAction = "delete" | "change_dates";

/** An agent of the workspace: a bot user with its owner, permission and project access. */
export type TWorkspaceAgent = {
  id: string;
  name: string;
  description: string;
  avatar_url: string | null;
  user_id: string;
  owner: { id: string; display_name: string };
  permission: TAgentPermission;
  approval_actions: TAgentApprovalAction[];
  run_budget_cents: number;
  is_active: boolean;
  project_ids: string[];
  last_active_at: string | null;
};

/** The create/update body. Dollars are converted to `run_budget_cents` by the form. */
export type TWorkspaceAgentPayload = {
  name: string;
  description: string;
  avatar_url: string;
  owner: string;
  project_ids: string[];
  permission: TAgentPermission;
  approval_actions: TAgentApprovalAction[];
  run_budget_cents: number;
};

/** The workspace's Claude key, model and monthly limit. The server never returns the key. */
export type TAISettings = {
  has_key: boolean;
  uses_instance_key: boolean;
  status: string;
  last_error: string | null;
  model: string;
  monthly_limit_cents: number | null;
  spent_this_month_cents: number;
  cloud_agents_ready: boolean;
};

export type TAgentRunKind = "managed" | "external";

export type TAgentRunStatus = "queued" | "running" | "waiting" | "succeeded" | "failed" | "cancelled";

export type TAgentRunStepKind = "message" | "tool" | "status" | "pr" | "commit" | "error";

export type TAgentRunStep = {
  id: string;
  seq: number;
  kind: TAgentRunStepKind;
  text: string;
  data: Record<string, unknown> | null;
  external_event_id: string | null;
  created_at: string;
};

export type TAgentRun = {
  id: string;
  /** None for a loop's run. */
  issue_id: string | null;
  loop_id: string | null;
  project_id: string;
  kind: TAgentRunKind;
  status: TAgentRunStatus;
  title: string;
  agent: { id: string; name: string; avatar_url: string | null } | null;
  actor: { id: string; display_name: string; is_agent: boolean };
  delegated_by: { id: string; display_name: string } | null;
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  cost_cents: number;
  summary: string;
  error: string;
  external_url: string;
  is_live: boolean;
  links: { kind: "pull_request" | "commit"; ref: string; title: string; url: string; repository: string }[];
  /** Only on a single run's response. */
  steps?: TAgentRunStep[];
};

export type TAgentLoopTrigger = "schedule" | "event";
export type TAgentLoopEvery = "hour" | "day" | "week";
export type TAgentLoopEventType = "issue" | "issue_comment" | "decision" | "approval" | "milestone";

/** When a schedule loop runs: `at` is HH:MM UTC (not for hour), `weekday` 0 (Monday) to 6 (week only). */
export type TAgentLoopSchedule = { every: TAgentLoopEvery; at?: string; weekday?: number };

/** A project runs an agent on a schedule or on workspace events, as a person (the owner). */
export type TAgentLoop = {
  id: string;
  project_id: string;
  name: string;
  agent: { id: string; name: string; avatar_url: string | null; is_active: boolean };
  owner: { id: string; display_name: string };
  instructions: string;
  trigger: TAgentLoopTrigger;
  schedule: TAgentLoopSchedule | Record<string, never>;
  event_types: TAgentLoopEventType[];
  cooldown_minutes: number;
  is_active: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  last_error: string;
  last_run: { id: string; status: TAgentRunStatus; created_at: string } | null;
  created_at: string;
};

export type TAgentLoopPayload = {
  name: string;
  agent_id: string;
  owner_id?: string;
  instructions: string;
  trigger: TAgentLoopTrigger;
  schedule?: TAgentLoopSchedule;
  event_types?: TAgentLoopEventType[];
  cooldown_minutes?: number;
  is_active?: boolean;
};

/** One row of an agent's audit trail, newest first. */
export type TAgentAuditEntry =
  | { at: string; kind: "request"; method: string; path: string; status: number }
  | {
      at: string;
      kind: "approval";
      id: string;
      action: TAgentApprovalAction;
      summary: string;
      status: string;
      decided_by: string | null;
      decided_at: string | null;
    }
  | { at: string; kind: "run"; id: string; issue_id: string | null; title: string; status: TAgentRunStatus };
