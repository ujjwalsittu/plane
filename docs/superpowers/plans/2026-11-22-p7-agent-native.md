# P7 · Agent-native Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agents become named members of a workspace whose work is credited to them, run under limits a person sets, report what they did on each work item, react to events instead of polling, and can be started from a work item as Claude Managed Agents sessions.

**Architecture:** An agent is a bot `User` (`bot_type="agent"`) with a `WorkspaceAgent` profile, a workspace-bound `APIToken`, and project memberships. Every agent request passes a guardrail check inside `APIKeyAuthentication` (scopes, then approval gates for risky actions; an approved request is replayed in-process). Runs are `AgentRun` + `AgentRunStep`; managed runs are Claude Managed Agents sessions that reach Plane through the Plane MCP server with the agent's own token (vault credential), synced into the run log by a Celery beat job. A `WorkspaceEvent` log, written next to the existing webhook dispatch, backs a cursor feed and an SSE stream; webhooks gain decision, approval, agent-run and milestone events.

**Tech Stack:** Django 5 / DRF / Celery / Postgres, ASGI under `uvicorn` workers (async SSE view), Anthropic Python SDK (`client.beta.agents|environments|vaults|sessions`), React + MobX + SWR + `@makeplane/propel` (apps/web), the Plane MCP image in `deployments/plane-mcp`.

**Spec:** `docs/superpowers/specs/2026-11-20-product-roadmap-design.md` (P7 must-haves 8, 9, 10, 12, 13; item 10 uses Claude Managed Agents, chosen by Ujjwal on 2026-11-22). Plane work items: PLAT-35, 36, 37, 39, 40. Stretch items 11, 14–17 (PLAT-38, 41–44) get their own plan.

## Global Constraints

- New `.py`, `.ts`, `.tsx` files start with the repo's `COPYRIGHT.txt` header.
- Every new setting is stored **per workspace**. Instance-wide config is only: `ANTHROPIC_API_KEY` (fallback key), `CLAUDE_MODEL` (default `claude-opus-5-5`), `SLACK_SIGNING_SECRET`, and the new `PLANE_MCP_URL` (public Streamable-HTTP URL of the Plane MCP server, e.g. `https://mcp.plane.azeonics.com/mcp`).
- Secrets (model keys, agent tokens in vaults) are stored with `plane.license.utils.encryption.encrypt_data` and never returned by any endpoint after creation; an agent's API token is shown exactly once, at creation.
- An agent is a `User` with `is_bot=True, bot_type="agent"`; P6's `is_agent_activity` already counts it as an agent. A person always stays the work item's owner (assignee); agents are never assignees and are left out of assignee and mention pickers.
- An agent sees and changes only projects it is an active `ProjectMember` of; this holds for the API, the event feed, run starts and the MCP.
- Managed Agents calls use the official `anthropic` SDK `client.beta.*` namespaces as documented in the claude-api skill (`python/managed-agents/README.md`, `shared/managed-agents-*.md`); verify any field not shown there against the SDK repo before using it. Agent toolset: `agent_toolset_20260401`, `permission_policy` `always_allow`, `web_search` and `web_fetch` disabled. MCP toolset for server name `plane`, `always_allow` (Plane enforces approvals server-side).
- Money is integer cents (`*_cents`), USD only; the Managed Agents `budget.max_list_cost.amount` is the cents value as a string.
- Migrations start at `0149`: `uv run python manage.py makemigrations db -n <name>` (rewrites `migrations_lockfile.txt`; commit both).
- i18n: new strings go under an `agents` key in `packages/i18n/src/locales/en/milestone.json`; the last task translates them into all 21 locales with the `translate` skill.
- Every new capability agents need gets an external `/api/v1/` endpoint with SDK-style shapes and an MCP tool (Task 11).
- Tests: `docker compose -f docker-compose-test.yml run --rm api-tests sh -c "pytest <path> -p no:cacheprovider --create-db -q"`; web: `pnpm turbo run check:types --filter=web`, `npx oxlint --deny-warnings <files>`, `pnpm exec oxfmt <files>`. Anthropic and GitHub calls are mocked in tests.
- Deploy per feature as in P6: commit, push `custom`, wait for "Custom images", run Coolify task `pre-upgrade-pgdump` when migrations are included, set `APP_RELEASE=sha-<7>`, deploy, verify `/version.json`. Never print env values.

## Review Focus

1. **Projects an agent isn't in:** an agent token must get 404 for items, runs and events of other projects, and the feed and stream must never carry them — Task 1 (`test_agent_only_reaches_its_projects`), Task 6 (`test_feed_hides_projects_agent_is_not_in`).
2. **Approved action whose target changed:** replaying an approved delete after the item was already deleted, or approving twice, must record the outcome once and never 500 — Task 4 (`test_replay_runs_once_and_records_missing_target`).
3. **Can't start a run:** no model key, the workspace over its monthly limit, the agent outside the item's project, or the Anthropic API failing must leave a clear message and no half-started session — Task 8 (`test_start_refused_without_key_or_over_limit`, `test_start_marks_failed_when_api_errors`).
4. **Sync surprises:** the same event fetched twice, a session deleted on Anthropic's side, or a run with no new events for 6 hours must not duplicate steps or leave a run "running" forever — Task 8 (`test_sync_is_idempotent_and_ends_lost_runs`).
5. **Turning an agent off mid-run:** deactivating an agent must revoke its token, interrupt its running sessions and mark those runs cancelled — Task 1 (`test_deactivate_revokes_token`) and Task 8 (`test_deactivating_agent_cancels_running_runs`).

---

### Task 1: Agents as members (item 8)

**Files:**

- Create: `apps/api/plane/db/models/agents.py` (`WorkspaceAgent`), register in `db/models/__init__.py`; migration `0149_workspaceagent`
- Create: `apps/api/plane/utils/agents.py`
- Create: `apps/api/plane/api/views/agents.py`, `apps/api/plane/api/urls/agents.py` (include in `api/urls/__init__.py`), `apps/api/plane/app/views/agents.py`; app routes in `plane/app/urls/milestone.py`
- Test: `apps/api/plane/tests/contract/app/test_agents.py`

**Interfaces:**

- Produces: `WorkspaceAgent(workspace, user OneToOne User (the bot), name, description, owner FK User (the person responsible), permission CharField in ("read","contribute","manage") default "contribute", approval_actions JSONField default ["delete","change_dates"], run_budget_cents PositiveInteger default 500, is_active, ma_agent_id CharField blank, ma_agent_version PositiveInteger null, ma_vault_id CharField blank)`; unique (workspace, name).
- `AgentError(message, status_code=400, field="error")` (same shape as `SupervisionError`).
- `create_agent(workspace, data, actor) -> tuple[WorkspaceAgent, str]` — creates the bot `User` (`email=f"agent-{uuid4().hex}@agents.invalid"`, `display_name=name`, `first_name=name`, `is_bot=True`, `bot_type="agent"`, `is_password_autoset=True`, avatar from `data["avatar_url"]` when given), a `WorkspaceMember` (role 15), a `ProjectMember` (role 15) for each id in `data["project_ids"]` (each must be a project the actor admins), and an `APIToken(user=bot, user_type=1, workspace=workspace, label=f"agent:{name}")`; returns the plaintext token once. Only workspace admins (role 20) create, edit or deactivate agents.
- `update_agent(agent, data, actor) -> WorkspaceAgent` (name, description, owner, permission, approval_actions ⊆ {"delete","change_dates"}, run_budget_cents 50–100000, project_ids sync), `deactivate_agent(agent, actor)` (agent and bot user inactive, tokens `is_active=False`, project memberships inactive, calls the `on_agent_deactivated(agent)` hook that Task 8 fills), `rotate_token(agent, actor) -> str`.
- `agent_for_user(user) -> WorkspaceAgent | None`; `agent_payload(agent) -> dict` (`{"id","name","description","avatar_url","owner": {"id","display_name"},"permission","approval_actions","run_budget_cents","is_active","project_ids","last_active_at"}`; `last_active_at` = max `APIToken.last_used`).
- Endpoints: app `GET/POST /api/workspaces/<slug>/agents/`, `GET/PATCH/DELETE .../agents/<id>/` (DELETE = deactivate), `POST .../agents/<id>/rotate-token/`; external read-only `GET /api/v1/workspaces/<slug>/agents/` (so agents can see each other).
- Pickers: the project/workspace member list serializers already include `member__is_bot` or add it; the web assignee and mention pickers filter out `is_bot` members (web part in Task 9).

- [ ] **Step 1: Write the failing tests** `test_admin_creates_agent_with_token_shown_once` (POST returns `token`; GET never does; bot user `is_bot` and `bot_type == "agent"`; member of the chosen projects only), `test_agent_writes_are_credited_to_agent` (create a work item with the agent token through `/api/v1/`; the `IssueActivity.actor` is the bot user, `source == "api"`, and P6 `is_agent_activity` is True), `test_agent_only_reaches_its_projects` (agent token → 404 on a work item in a project it isn't a member of), `test_non_admin_cannot_manage_agents` (role 15 → 403), `test_deactivate_revokes_token` (after DELETE the token gets 401).
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement model, migration, helpers and views.
- [ ] **Step 4:** Run; expect PASS. Run the full suite.
- [ ] **Step 5: Commit** `feat: agents as workspace members with their own tokens (PLAT-35)`

### Task 2: Workspace model key and spend limit (item 12, part 1)

**Files:**

- Modify: `apps/api/plane/db/models/agents.py` (`WorkspaceAIConfig`); migration `0150_workspaceaiconfig`
- Create: `apps/api/plane/utils/ai_config.py`
- Modify: `apps/api/plane/utils/brief_summary.py` (use `anthropic_client_for`)
- Modify: `apps/api/plane/app/views/agents.py`, `plane/app/urls/milestone.py`
- Test: `apps/api/plane/tests/unit/utils/test_ai_config.py`

**Interfaces:**

- Produces: `WorkspaceAIConfig(workspace unique, api_key_encrypted TextField blank, monthly_limit_cents PositiveInteger null, model CharField blank, ma_environment_id CharField blank, status in ("ok","broken","unset") default "unset", last_error TextField blank)`.
- `anthropic_client_for(workspace) -> anthropic.Anthropic | None` — the workspace key when set and decryptable; else the instance `ANTHROPIC_API_KEY` when set; else None. A stored key that no longer decrypts (SECRET_KEY changed) sets `status="broken"`, `last_error="reconnect"` and returns None (no fallback, so a broken key is noticed).
- `model_for(workspace) -> str` (`config.model or settings.CLAUDE_MODEL`).
- `spent_this_month_cents(workspace) -> int` (sum of `AgentRun.cost_cents` with `created_at` in the current UTC month; returns 0 until Task 3 adds `AgentRun`, so import lazily), `check_spend(workspace, extra_cents=0)` raises `AgentError("Monthly AI limit reached", 409, "spend_limit_reached")` when `monthly_limit_cents` is set and `spent + extra_cents > limit`.
- `set_api_key(workspace, key, actor)` validates with `client.models.list(limit=1)` (401 → `AgentError("That key was rejected by Anthropic", 400, "api_key")`), stores encrypted, `status="ok"`.
- Endpoints (admins): `GET/PUT/DELETE /api/workspaces/<slug>/ai-settings/` → `{"has_key": bool, "uses_instance_key": bool, "status","last_error","model","monthly_limit_cents","spent_this_month_cents","cloud_agents_ready": bool}`; PUT accepts `api_key`, `model`, `monthly_limit_cents` (null clears).

- [ ] **Step 1: Write the failing tests** `test_workspace_key_preferred_over_instance_key`, `test_falls_back_to_instance_key_when_unset`, `test_key_unreadable_after_secret_key_change_marks_broken`, `test_rejected_key_is_not_stored`, `test_check_spend_blocks_over_limit` (limit 1000, spent 990, extra 20 → 409).
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement; switch `brief_summary.py` to `anthropic_client_for(workspace)` and `model_for(workspace)`.
- [ ] **Step 4:** Run; expect PASS, plus the P6 brief summary tests.
- [ ] **Step 5: Commit** `feat: per-workspace Claude key and monthly AI limit (PLAT-39)`

### Task 3: Run log (item 9)

**Files:**

- Modify: `apps/api/plane/db/models/agents.py` (`AgentRun`, `AgentRunStep`); migration `0151_agentrun`
- Create: `apps/api/plane/utils/agent_runs.py`
- Modify: `apps/api/plane/api/views/agents.py`, `api/urls/agents.py`, `app/views/agents.py`, `app/urls/milestone.py`
- Test: `apps/api/plane/tests/contract/api/test_agent_runs.py`

**Interfaces:**

- Consumes: `agent_for_user`, `is_agent_activity`.
- Produces: `AgentRun(workspace, project, issue, agent FK WorkspaceAgent null, actor FK User (who reports: the agent's bot user, or a person's own token for a Claude Code session), delegated_by FK User null, kind in ("managed","external"), status in ("queued","running","waiting","succeeded","failed","cancelled"), title, instructions TextField blank, external_session_id blank, external_url blank, started_at null, ended_at null, last_event_at null, cost_cents PositiveInteger null, input_tokens/output_tokens PositiveBigInteger default 0, summary TextField blank, error TextField blank)`; `AgentRunStep(run, seq PositiveInteger, kind in ("message","tool","status","pr","commit","error"), text TextField, data JSONField, external_event_id CharField blank, created_at)` with unique (run, external_event_id) when non-blank and unique (run, seq).
- `start_external_run(issue, actor, data) -> AgentRun` (status `running`, `started_at=now`), `add_step(run, kind, text, data=None, external_event_id="") -> AgentRunStep | None` (returns None for a duplicate external id; updates `last_event_at`), `finish_run(run, status, summary="", error="", cost_cents=None)` (sets `ended_at`; status must be terminal), `run_payload(run, steps=False) -> dict` (`{"id","kind","status","title","agent": agent_payload-lite {"id","name","avatar_url"}|None,"actor":{"id","display_name","is_agent"},"delegated_by","started_at","ended_at","duration_seconds","cost_cents","summary","error","external_url","is_live","links": [GitHub PRs/commits linked to the issue (P3) created at or after started_at],"steps": [...] when steps}`).
- `is_live` = status in (`running`,`queued`) and `last_event_at` (or `started_at`) within the last 10 minutes. `live_runs_for(issue_ids) -> dict[issue_id, run_payload]` for list and Brief badges.
- Endpoints: external `GET/POST /api/v1/workspaces/<slug>/projects/<pid>/work-items/<iid>/agent-runs/`, `GET/PATCH .../agent-runs/<run_id>/` (PATCH: `status`, `summary`, `error`, `cost_cents`, `external_url`; only the run's `actor` may write → 403), `POST .../agent-runs/<run_id>/steps/` (`kind`, `text`, `data`); app twins for reading, plus `GET /api/workspaces/<slug>/agent-runs/live/?issue_ids=...`. Every create, step and finish calls `emit_event` once Task 6 lands (leave a `# Task 6` no-op hook `on_run_changed(run, action)` here).

- [ ] **Step 1: Write the failing tests** `test_agent_reports_a_run_with_steps` (POST run, two steps, PATCH `succeeded` with cost 37 → GET shows duration, cost, steps in order), `test_only_reporter_can_write_run` (another member's token → 403), `test_duplicate_external_step_ignored`, `test_live_flag_expires_after_10_minutes`, `test_run_links_include_prs_since_start`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement models, helpers, views.
- [ ] **Step 4:** Run; expect PASS.
- [ ] **Step 5: Commit** `feat: agent run log on work items (PLAT-36)`

### Task 4: Guardrails: scopes and approval gates (item 12, part 2)

**Files:**

- Modify: `apps/api/plane/db/models/agents.py` (`AgentApproval`); migration `0152_agentapproval`
- Create: `apps/api/plane/utils/guardrails.py`
- Modify: `apps/api/plane/api/middleware/api_authentication.py` (call `check_request` after the token validates)
- Modify: `apps/api/plane/app/views/agents.py`, `app/urls/milestone.py`
- Test: `apps/api/plane/tests/contract/api/test_guardrails.py`

**Interfaces:**

- Consumes: `agent_for_user`, `WorkspaceAgent.permission`, `approval_actions`.
- Produces: `AgentApproval(workspace, project null, issue null, agent, asked_user FK User (= agent.owner), action in ("delete","change_dates"), summary, method, path, query, body JSONField, status in ("open","approved","rejected","expired","executed","failed"), decided_by null, decided_at null, result_status PositiveSmallInteger null, result_body JSONField null)`.
- `classify(request) -> str | None`: `"delete"` for any `DELETE` and any `POST` to a path ending `/archive/`; `"change_dates"` for `PATCH`/`PUT` whose JSON body contains any of `start_date`, `target_date`, `end_date`; else None.
- `check_request(request, user)` — no-op for non-agent users. For an agent: inactive → `AuthenticationFailed`; `permission == "read"` and method not in `GET, HEAD, OPTIONS` → `PermissionDenied("This agent is read-only")`; `permission == "contribute"` and `classify(...) == "delete"` with `"delete"` not in `approval_actions` → `PermissionDenied`; when `classify(...)` is in `approval_actions` and the request carries no valid `X-Plane-Approval` header → create (or reuse an `open` one with the same method/path/body hash) an `AgentApproval` and raise `ApprovalRequired` (a DRF `APIException`, status 403, body `{"error": "approval_required", "approval_id": str, "detail": "Waiting for {owner} to approve: {summary}. Plane runs it once approved; do not retry."}`). `"manage"` agents still go through approval gates.
- `decide_approval(approval, user, approve: bool) -> AgentApproval` (only `asked_user` or a workspace admin → 403; not `open` → 409). On approve: `replay(approval)` — builds the same request with `rest_framework.test.APIRequestFactory`, headers `X-Api-Key` (the agent's active token) and `X-Plane-Approval: django.core.signing.dumps(str(approval.id), salt="agent-approval")`, resolves the path with `django.urls.resolve` and calls the view; stores `result_status`/`result_body`; status `executed` on 2xx, else `failed`. A header signature that doesn't match this exact approval, or an approval not in `approved` state, is ignored (the gate fires again).
- `expire_approvals()` sets `open` approvals older than 7 days to `expired` (beat daily 03:45 UTC, added in this task to `plane/celery.py`).
- Hook `on_approval_created(approval)` (Task 5 fills: Slack DM and notification).
- Endpoints: app `GET /api/workspaces/<slug>/approvals/?status=open` (mine), `POST .../approvals/<id>/approve/`, `POST .../approvals/<id>/reject/`; external `GET /api/v1/workspaces/<slug>/approvals/<id>/` (agents check outcome).

- [ ] **Step 1: Write the failing tests** `test_read_only_agent_cannot_write`, `test_delete_needs_approval_then_runs_once` (agent DELETE → 403 `approval_required`, item still exists; owner approves → item deleted, approval `executed`, `result_status == 204`), `test_date_change_needs_approval` (PATCH `target_date` → gated; PATCH `name` → 200), `test_same_request_reuses_open_approval`, `test_replay_runs_once_and_records_missing_target` (delete the item as a person before approving → approval `failed` with `result_status == 404`; approving again → 409), `test_people_are_not_gated` (a person's token deletes freely), `test_forged_approval_header_is_ignored`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement model, `guardrails.py`, the hook in `APIKeyAuthentication.authenticate`, endpoints, beat entry.
- [ ] **Step 4:** Run; expect PASS; run the full suite (the auth change touches every external request).
- [ ] **Step 5: Commit** `feat: agent scopes and approval gates for risky actions (PLAT-39)`

### Task 5: Approvals on the Brief, in Slack and in the audit trail (item 12, part 3)

**Files:**

- Modify: `apps/api/plane/utils/brief.py` (`needs_me` gains `why: "approval"`), `apps/api/plane/utils/guardrails.py` (`on_approval_created`), `apps/api/plane/bgtasks/supervision_task.py` (`notify_approval`), `apps/api/plane/app/views/slack_interactivity.py` (`approval:{id}:approve|reject`)
- Modify: `apps/api/plane/app/views/agents.py` (`GET /api/workspaces/<slug>/agents/<id>/audit/`)
- Create: `apps/web/components/brief/approval-answer.tsx`; modify `apps/web/components/brief/needs-me.tsx`, `apps/web/services/supervision.service.ts`, `packages/types/src/milestone.ts` (`TAgentApproval`)
- Test: `apps/api/plane/tests/unit/bgtasks/test_approval_notifications.py`

**Interfaces:**

- Consumes: `brief_for`, `dm`, `verify_signature`, `decide_approval`.
- Produces: Brief `needs_me` rows `{"why": "approval", "approval": {"id","summary","action","agent": {"id","name","avatar_url"},"created_at"}, "issue": payload|None}` sorted with decisions. `notify_approval(approval_id)` DMs the owner "{agent} wants to {summary}" with Approve / Reject buttons and creates a `Notification` (`entity_name="approval"`, `sender="approval"`) so the P6 priority inbox shows it. Slack clicks call `decide_approval` as the linked user and replace the message with "Approved" / "Rejected".
- `audit_for(agent, limit=200) -> list[dict]` merges, newest first: `APIActivityLog` rows for the agent's tokens (`{"at","kind":"request","method","path","status"}`), approvals (`kind: "approval"`), runs (`kind: "run"`).
- Web: the Needs me list renders approvals with the agent's avatar, the summary, and Approve / Reject buttons.

- [ ] **Step 1: Write the failing tests** `test_approval_shows_in_owners_brief`, `test_approval_dm_has_buttons`, `test_slack_click_approves_and_runs` (signed payload), `test_audit_lists_requests_approvals_and_runs`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement backend and the Brief UI.
- [ ] **Step 4:** Run; expect PASS; web type check, lint and format pass.
- [ ] **Step 5: Commit** `feat: approve agent actions from the Brief and Slack, with an audit trail (PLAT-39)`

### Task 6: Event log, feed, stream and webhooks (item 13)

**Files:**

- Modify: `apps/api/plane/db/models/agents.py` (`WorkspaceEvent`); `apps/api/plane/db/models/webhook.py` (`Webhook`: add `decision`, `approval`, `agent_run`, `milestone` booleans); migration `0153_workspaceevent`
- Create: `apps/api/plane/utils/events.py`, `apps/api/plane/api/views/events.py` (feed + async SSE), routes in `api/urls/agents.py`
- Modify: `apps/api/plane/bgtasks/webhook_task.py` (`webhook_activity` records a `WorkspaceEvent` and filters the new flags), `apps/api/plane/utils/decisions.py`, `apps/api/plane/utils/guardrails.py`, `apps/api/plane/utils/agent_runs.py` (call `emit_event`), milestone create/update/delete views (`emit_event("milestone", ...)`), `plane/celery.py` (`prune-events` daily 04:00 UTC), web webhook form (`apps/web/components/web-hooks/form/` — 4 new checkboxes)
- Test: `apps/api/plane/tests/contract/api/test_events.py`

**Interfaces:**

- Produces: `WorkspaceEvent(id BigAutoField, workspace FK, project_id UUID null, event CharField (issue, issue_comment, project, cycle, module, milestone, decision, approval, agent_run), action CharField (created, updated, deleted, answered, approved, rejected, started, finished…), entity_id UUID, actor_id UUID null, is_agent bool, data JSONField, created_at)`; index (workspace, id). Not a `BaseModel` (needs the integer cursor).
- `emit_event(workspace_id, event, action, entity_id, project_id=None, actor=None, data=None)` — writes the row and, for the four new kinds, sends to webhooks with the matching flag through the existing `webhook_send_task`.
- `events_after(workspace, user, after_id=0, types=None, project_id=None, limit=100) -> list[dict]` — only projects the user is an active member of, plus workspace-level rows (`project_id` null); each `{"id","event","action","entity_id","project_id","actor_id","is_agent","data","created_at"}`.
- Endpoints: `GET /api/v1/workspaces/<slug>/events/?after=<id>&types=issue,decision&project=<id>` → `{"results": [...], "next_after": int}`; `GET /api/v1/workspaces/<slug>/events/stream/` — async `StreamingHttpResponse` (`text/event-stream`), starts after `Last-Event-ID` or `?after=`, polls `events_after` every 1 s, sends `id:`/`event:`/`data:` frames, a `: ping` comment every 15 s, closes after 300 s (clients reconnect with `Last-Event-ID`); headers `Cache-Control: no-cache`, `X-Accel-Buffering: no`. Both take API-key or session auth.
- `prune_events()` deletes rows older than 30 days.

- [ ] **Step 1: Write the failing tests** `test_issue_change_appears_in_feed` (update an item → feed has `issue/updated` with `is_agent` correct), `test_feed_cursor_and_type_filter`, `test_feed_hides_projects_agent_is_not_in`, `test_decision_and_run_events_reach_webhooks` (mock `webhook_send_task.delay`), `test_stream_sends_events_and_ping` (call the async view with a short timeout override; read the first frames).
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement; fill the `on_run_changed` hook from Task 3.
- [ ] **Step 4:** Run; expect PASS; full suite.
- [ ] **Step 5: Commit** `feat: workspace event feed, live stream and new webhook events (PLAT-40)`

### Task 7: Cloud agent setup on Managed Agents (item 10, part 1)

**Files:**

- Create: `apps/api/plane/utils/managed_agents.py`
- Modify: `apps/api/plane/settings/common.py` (`PLANE_MCP_URL = os.environ.get("PLANE_MCP_URL", "")`), `apps/api/plane/utils/agents.py` (create/update/rotate/deactivate keep the Managed Agents agent and vault in step), `apps/api/plane/app/views/agents.py` (`POST /api/workspaces/<slug>/ai-settings/cloud-agents/` sets up)
- Modify: `apps/api/plane/api/views/user.py` (`/api/v1/users/me/` adds `token_workspace_slug` when authenticated by a workspace-bound token; additive)
- Test: `apps/api/plane/tests/unit/utils/test_managed_agents.py`

**Interfaces:**

- Consumes: `anthropic_client_for`, `model_for`, `WorkspaceAgent.ma_*`, `WorkspaceAIConfig.ma_environment_id`.
- Produces: `ensure_environment(workspace) -> str` (`client.beta.environments.create(name=f"plane-{slug}", config={"type": "cloud", "networking": {"type": "limited", "allow_package_managers": True, "allow_mcp_servers": True, "allowed_hosts": [<Plane host>, "api.github.com", "github.com"]}})`, stored on the config; reused when present); `sync_ma_agent(agent) -> None` (creates or updates the Managed Agents agent: `name=agent.name`, `model=model_for(workspace)`, `system=AGENT_SYSTEM_PROMPT`, `mcp_servers=[{"type": "url", "name": "plane", "url": settings.PLANE_MCP_URL}]`, tools per Global Constraints; stores `ma_agent_id`, `ma_agent_version`); `sync_vault(agent, token) -> None` (one vault per agent, `display_name=f"plane-{slug}-{agent.name}"`, one `static_bearer` credential for `PLANE_MCP_URL` with the agent's token — check the credential shape in the SDK before writing it; on token rotation archive and recreate the credential); `archive_ma_agent(agent)` on deactivation. Setup fails with `AgentError(..., 400, "cloud_agents")` when `PLANE_MCP_URL` or a key is missing.
- `AGENT_SYSTEM_PROMPT` (module constant, written in this task): you work for {workspace} through the Plane MCP tools; the work item in your first message is your brief; post progress as work item comments; when you need a person's choice, create a decision request and stop; risky actions may answer `approval_required` — note it and move on, never retry; mounted repositories are under `/workspace`; push a branch and open the pull request through the GitHub REST API, which the git proxy authenticates; finish with a short summary of what changed and what's left.
- `cloud_agents_ready` in `GET ai-settings/` = environment set and every active agent has `ma_agent_id` and `ma_vault_id`.

- [ ] **Step 1: Write the failing tests** (mock the client): `test_setup_creates_environment_once`, `test_agent_sync_declares_plane_mcp_and_disables_web_tools`, `test_vault_holds_agent_token_for_mcp_url`, `test_rotate_token_replaces_vault_credential`, `test_setup_requires_mcp_url_and_key`, `test_users_me_reports_token_workspace` (contract test against `/api/v1/users/me/`).
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run; expect PASS.
- [ ] **Step 5: Commit** `feat: set up cloud agents on Claude Managed Agents (PLAT-37)`

### Task 8: Delegate a work item to a cloud agent (item 10, part 2)

**Files:**

- Modify: `apps/api/plane/utils/managed_agents.py` (`start_managed_run`, `sync_run`, `send_follow_up`, `cancel_run`), `apps/api/plane/utils/agents.py` (`on_agent_deactivated` → cancel running runs)
- Create: `apps/api/plane/bgtasks/agent_runs_task.py`; modify `plane/celery.py` (`sync-agent-runs` every 15 s)
- Modify: `apps/api/plane/app/views/agents.py`, `apps/api/plane/api/views/agents.py` (start/follow-up/cancel endpoints)
- Test: `apps/api/plane/tests/unit/utils/test_managed_runs.py`

**Interfaces:**

- Consumes: `start_external_run`-style model fields, `add_step`, `finish_run`, `check_spend`, `anthropic_client_for`, `emit_event`, P3 project ↔ repository links and the GitHub App installation token helper in `utils/github_app.py`.
- Produces: `start_managed_run(issue, agent, delegated_by, instructions="") -> AgentRun`: refuses (AgentError, nothing created) when the agent is inactive or not a member of the issue's project (400), the workspace isn't set up for cloud agents (400 `cloud_agents`), or `check_spend(workspace, agent.run_budget_cents)` fails (409). Creates the run (`kind="managed"`, `status="queued"`), then `client.beta.sessions.create(agent={"type": "agent", "id", "version"}, environment_id, vault_ids=[agent.ma_vault_id], title=f"{project.identifier}-{issue.sequence_id}: {issue.name}"[:200], metadata={"plane_run_id", "plane_workspace"}, budget={"type": "limit", "max_list_cost": {"amount": str(agent.run_budget_cents), "currency": "USD"}}, resources=[one github_repository per linked repo, at most 3, with a fresh installation token, mount_path f"/workspace/{repo_name}"])` and sends one `user.message` with `build_brief(issue, instructions)`. Stores `external_session_id` and `external_url` (`https://platform.claude.com/workspaces/default/sessions/{id}`). Any Anthropic error → run `failed` with `error` set, no retry.
- `build_brief(issue, instructions) -> str`: identifier, title, URL, state, priority, dates, milestone, description (plain text), the last 10 comments, open decision requests, linked PRs, then the person's instructions.
- `sync_run(run)`: lists all session events (`client.beta.sessions.events.list`, paged), maps new ones by `external_event_id` — `agent.message` → `message` step (text), `agent.mcp_tool_use` / `agent.tool_use` → `tool` step (`{name}` + short input), `session.error` → `error` step, git pushes and PR URLs found in tool results → `commit`/`pr` steps; then reads the session: `running` → run `running`; idle with `end_turn` → `succeeded` with the last agent message as `summary`; idle with `budget_reached` → `failed`, `error="Run budget reached"`; idle with `requires_action` → deny pending confirmations and add an `error` step; `terminated` → `failed` unless the last idle was `end_turn`. Always copies `usage.list_cost.amount` → `cost_cents` and token totals. Session 404 → `failed`, `error="Session no longer exists"`. No new events for 6 hours while `running` → interrupt, `failed`, `error="No progress for 6 hours"`.
- `send_follow_up(run, user, text)` (only when status `succeeded` or `waiting`; status back to `running`), `cancel_run(run, user)` (`user.interrupt`, status `cancelled`).
- Endpoints: app and external `POST .../work-items/<iid>/agent-runs/delegate/` (`agent_id`, `instructions`), `POST .../agent-runs/<id>/follow-up/` (`text`), `POST .../agent-runs/<id>/cancel/`. Delegating needs project role ≥ 15.

- [ ] **Step 1: Write the failing tests** (mock the client): `test_delegate_starts_session_with_brief_budget_and_repos`, `test_start_refused_without_key_or_over_limit`, `test_start_marks_failed_when_api_errors`, `test_sync_maps_events_to_steps_and_finishes_with_cost`, `test_sync_is_idempotent_and_ends_lost_runs` (same events twice → no duplicates; 404 → failed; 6 h silence → failed), `test_deactivating_agent_cancels_running_runs`, `test_follow_up_and_cancel`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement helpers, the beat task (only runs in `queued`/`running`/`waiting` with `kind="managed"`, each in its own try/except), endpoints.
- [ ] **Step 4:** Run; expect PASS; full suite.
- [ ] **Step 5: Commit** `feat: delegate work items to cloud Claude agents with a live run log (PLAT-37)`

### Task 9: Agents and AI settings pages (web, items 8 and 12)

**Files:**

- Create: route `apps/web/app/(all)/[workspaceSlug]/(settings)/settings/(workspace)/agents/page.tsx`, `apps/web/components/agents/settings/{root,agent-form,agent-list,token-reveal,ai-settings,audit}.tsx`, `apps/web/services/agents.service.ts`
- Modify: workspace settings nav (where `slack` was added in P6), `packages/types/src/milestone.ts` (`TWorkspaceAgent`, `TAISettings`, `TAgentRun`, `TAgentRunStep`, `TAgentAuditEntry`), `packages/i18n/src/locales/en/milestone.json` (`agents`), the assignee and mention member pickers (filter `is_bot`)

**Interfaces:**

- Consumes: Task 1, 2, 5 and 7 endpoints.
- Produces: an admin-only Agents settings page: AI settings card (key field `type=password`, "uses the installation key" note, model, monthly limit, spent this month, "Set up cloud agents" button with ready/not ready state and the error from setup); agent list (avatar, name, owner, permission, projects, last active, active toggle); create/edit form (name, description, avatar URL, owner, projects, permission, approval toggles for "Deleting or archiving" and "Changing dates", run budget in dollars); token reveal dialog shown once with copy and "store it now" copy; per-agent audit drawer.

- [ ] **Step 1:** Build the service and types; build the page and components with `@makeplane/propel` primitives, following `components/integration/slack/root.tsx`.
- [ ] **Step 2:** Filter bot members out of assignee and mention pickers.
- [ ] **Step 3:** `pnpm turbo run check:types --filter=web`, oxlint, oxfmt pass. Run `pnpm dev`, create an agent against the local API, check the token is shown once and the agent is missing from the assignee picker.
- [ ] **Step 4: Commit** `feat: agents and AI settings pages (PLAT-35, PLAT-39)`

### Task 10: Run log and delegation on the work item (web, items 9 and 10)

**Files:**

- Create: `apps/web/components/issues/issue-detail-widgets/agent-runs/{root,run-row,run-steps,delegate-modal,live-pill}.tsx`
- Modify: the work item detail widgets list (where the P6 supervision widget is registered), the work item header (live pill), list and board item properties (small live dot from `agent-runs/live/`), `apps/web/components/brief/done.tsx` (agent avatar and name for agent rows)

**Interfaces:**

- Consumes: Task 3 and 8 endpoints, `TAgentRun`.
- Produces: an "Agent runs" widget listing runs newest first (agent avatar and name, "for {delegated_by}", status chip, duration, cost as `$0.37`, linked PRs), expandable steps (messages as text, tool steps collapsed to one line, PR and commit steps as links), "Open session" link for managed runs, follow-up box and Cancel for managed runs; "Delegate to agent" button (members) opening a modal with active agents in this project and an instructions field, showing the server's refusal message inline; SWR refresh every 5 s while any run is live, else on focus; "Agent working" pill in the header while live.

- [ ] **Step 1:** Build the widget, modal and pills.
- [ ] **Step 2:** Type check, lint, format pass. With `pnpm dev`, report an external run through `/api/v1/` with curl and watch it appear and turn live, then finish it.
- [ ] **Step 3: Commit** `feat: agent run log, live presence and delegation on work items (PLAT-36, PLAT-37)`

### Task 11: MCP: bearer auth and agent tools

**Files:**

- Modify: `deployments/plane-mcp/plane_header_auth_provider.py` (accept `Authorization: Bearer plane_api_…` when `x-api-key` is absent; workspace slug from `x-workspace-slug`, else `token_workspace_slug` from `/api/v1/users/me/`, cached with the key), `deployments/plane-mcp/patch_mcp.py` (new tool module)
- Create: `deployments/plane-mcp/agent_tools.py` (copied into `/app/plane_mcp/tools/` and registered by the patch)
- Test: `deployments/plane-mcp/test_agent_tools.py` run in the built image (`docker build` then `docker run --rm <image> python -m pytest /app/plane_mcp/tools/test_agent_tools.py`), or the closest check the image allows

**Interfaces:**

- Consumes: Task 3, 4, 6 external endpoints.
- Produces: MCP tools in the existing style (one tool per resource with an `action` argument): `agent_run` (`start` with project_id, workitem_id, title; `step` with run_id, kind, text; `finish` with run_id, status, summary, cost_cents; `list`, `retrieve`), `approval` (`retrieve` by id), `event` (`list` with after, types, project_id). Every anchor in `patch_mcp.py` must match or the image build fails.

- [ ] **Step 1:** Write the bearer-auth change and the tools; extend `patch_mcp.py` to install and register them.
- [ ] **Step 2:** Build the image locally (`docker build deployments/plane-mcp`), start it against the local API, and call `agent_run start/step/finish` with an agent token sent as `Authorization: Bearer` and no slug header; the run appears in Plane.
- [ ] **Step 3: Commit** `feat: MCP accepts bearer agent tokens; agent run, approval and event tools (PLAT-36, PLAT-40)`

### Task 12: Translate, verify and ship

**Files:**

- Modify: `packages/i18n/src/locales/<21 locales>/milestone.json` (`agents` key)

- [ ] **Step 1:** Translate every `agents` string into all 21 locales with the `translate` skill and `check_i18n.py`; `pnpm --filter=@plane/i18n sync:check` passes.
- [ ] **Step 2:** Full backend suite and web type check pass.
- [ ] **Step 3:** Deploy with the Global Constraints procedure (migrations 0149–0153 → backup first). Ask Ujjwal to: give the Plane MCP service a public HTTPS domain if it has none and set `PLANE_MCP_URL` in Coolify; deploy the new MCP image.
- [ ] **Step 4:** Verify in production:
  - Create an agent "Builder" owned by Ujjwal in PLAT, with the token shown once; an MCP change made with its token shows "Builder" on the Brief's Done list.
  - The agent deleting a test work item is held for approval; approving from Slack deletes it once.
  - The event feed returns that delete; the stream sends it live.
  - Set up cloud agents in AI settings (Ujjwal enters the workspace key himself), delegate a small PLAT work item to Builder, watch steps arrive, and see the run finish with a cost and a summary comment on the item.
- [ ] **Step 5:** Mark PLAT-35, 36, 37, 39, 40 Done as each is verified. Stretch items (PLAT-38, 41–44) go into the next plan.
