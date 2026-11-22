# P7 follow-up fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gaps found in the P7 final review and the production checks of 2026-11-22: approvals that linger in the inbox, agents whose approvals and runs outlive deactivation, agents spending money on cloud runs, external runs eating the AI limit, needless polling, OAuth connections to the MCP, hour-long cloud runs losing GitHub, missing `issue deleted` events, and the hydration warning on work item pages.

**Architecture:** Small changes inside the P7 modules (`plane/utils/guardrails.py`, `agents.py`, `managed_agents.py`, `ai_config.py`, `events`), one change in the shared activity task so every work item and comment delete reaches the event log, one live-runs response flag the web batcher reads, and one auth helper in the MCP image. No new models; no migrations.

**Tech Stack:** Django 5 / DRF / Celery / Postgres, Anthropic Python SDK 1.17 (`client.beta.sessions.*`), React + MobX + SWR + vitest (apps/web), the Plane MCP image in `deployments/plane-mcp`.

**Spec:** `docs/superpowers/specs/2026-11-20-product-roadmap-design.md` (P7 items 8, 9, 10, 12, 13, already shipped by `docs/superpowers/plans/2026-11-22-p7-agent-native.md`). Sources for this plan: the "Final review: minor (deferred, recommended soon after ship)" line and the per-task "minor (deferred)" lines of the git-ignored ledger `.superpowers/sdd/2026-11-22-p7-agent-native/progress.md`, and the 2026-11-22 production checks. The stretch items (PLAT-38, 41–44) are in `docs/superpowers/plans/2026-11-22-p7-stretch.md`.

## Global Constraints

- Branch `custom`, no worktree. Commit with the message each task gives. Never push without Ujjwal's go-ahead. Never add "Co-Authored-By" or any Claude/Anthropic attribution to commit messages. Never print or commit secret values.
- New `.py`, `.ts`, `.tsx` files start with the repo's `COPYRIGHT.txt` header.
- No migrations in this plan. If a task finds it needs one: `uv run python manage.py makemigrations db -n <name>` (next number is `0155`), commit `apps/api/migrations_lockfile.txt` with it.
- An agent is a `User` with `is_bot=True, bot_type="agent"`; a person always stays the owner. An agent sees and changes only projects it is an active `ProjectMember` of.
- Errors use `AgentError(message, status_code, field)` from `plane/utils/agents.py`. Feed events go through `plane.utils.events.emit_event` (best effort, never raises).
- Money is integer cents (`*_cents`), USD only.
- Every new web string goes under the `agents` key of `packages/i18n/src/locales/en/milestone.json`; Task 11 translates them into all 21 locales with the `translate` skill.
- Tests: `docker compose -f docker-compose-test.yml run --rm api-tests sh -c "pytest <path> -p no:cacheprovider --create-db -q"` from the repo root; full suite: same with `plane/tests`. Web: `pnpm turbo run check:types --filter=web`, `pnpm --filter=web exec vitest run <path>`, `npx oxlint --deny-warnings <files>`, `pnpm exec oxfmt <files>`. Anthropic and GitHub calls are mocked.
- Deploy as in P6/P7: push `custom` (only after Ujjwal agrees), wait for "Custom images", set `APP_RELEASE=sha-<7>`, deploy, verify `/version.json`. Never print env values.

## Review Focus

1. **An approval decided in Slack while the inbox row is still on screen:** the row must leave the inbox whatever the path (Brief button, Slack button, expiry, agent deactivation) — Task 1 (`test_decided_approval_leaves_inbox`, `test_expired_approval_leaves_inbox`), Task 2 (`test_deactivating_agent_expires_its_approvals`).
2. **An agent token calling the delegate endpoint through the MCP or curl:** must get 403 and create no run and no session — Task 3 (`test_agent_token_cannot_delegate`).
3. **A two-hour cloud run that pushes at the end:** the GitHub token mounted at start must have been replaced before it expires, and a failed refresh must not fail the run — Task 4 (`test_long_run_refreshes_repository_tokens`, `test_token_refresh_failure_does_not_fail_run`).
4. **A work item deleted by a person in the web app, not only by an approved agent:** the feed and webhooks must both see `issue deleted` — Task 5 (`test_app_delete_reaches_feed`, `test_approved_agent_delete_emits_issue_deleted`).
5. **A workspace with no agents and a 500-item board open all day:** after the first lookup, no live-run request every 15 s — Task 6 (`stops polling a workspace that has nothing live`).

---

### Task 1: Approval lifecycle (inbox, stuck replays, cap)

**Files:**

- Modify: `apps/api/plane/utils/guardrails.py` (`decide_approval`, `expire_approvals`, `_open_approval`, new helpers)
- Test: `apps/api/plane/tests/unit/bgtasks/test_approval_notifications.py`, `apps/api/plane/tests/contract/api/test_guardrails.py`

**Interfaces:**

- Produces: `close_approval_notifications(approval_ids: list) -> int` — marks unread `Notification` rows with `entity_name="approval"` and `data__approval__id` in the ids as read (`read_at=now`), same as `decisions._close_notifications`. Called by `decide_approval` for every outcome (approved, rejected, and the late-expired branch).
- Produces: `expire_open_approvals(queryset) -> int` — sets each `open` approval in the queryset to `expired`, closes their inbox rows, emits one `approval expired` event each (actor None). `expire_approvals()` becomes `expire_open_approvals(<open, older than EXPIRE_DAYS>)` plus the stuck sweep below. Task 2 calls it.
- Stuck replays: `expire_approvals()` also fails approvals left `approved` with `result_status` null and `decided_at` older than 10 minutes (`STUCK_AFTER = timedelta(minutes=10)`): status `failed`, `result_body={"error": "The approved request never ran"}`, one `approval failed` event.
- Cap: `_open_approval` refuses a new approval when the agent already has `MAX_OPEN_APPROVALS = 50` open ones: raise DRF `Throttled` subclass `TooManyApprovals` (429, body `{"error": "too_many_approvals", "detail": "50 actions are already waiting for approval; wait for decisions before asking again."}`). Reusing an existing open approval for the same request is not refused.

- [ ] **Step 1: Write the failing tests** `test_decided_approval_leaves_inbox` (approve via app endpoint and reject via Slack click → the owner's approval Notification has `read_at` set), `test_expired_approval_leaves_inbox` (backdate 8 days, run `expire_approvals()` → `expired`, row read, one `approval/expired` feed event), `test_stuck_approved_replay_is_failed_by_sweep` (status `approved`, `decided_at` 11 min ago, no result → `failed`; one decided 5 min ago stays `approved`), `test_open_approvals_capped_per_agent` (50 open → 51st distinct gated request gets 429 `too_many_approvals`; repeating one of the 50 still gets 403 `approval_required` with the existing id).
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement the helpers and wire them in.
- [ ] **Step 4:** Run the two test files and `plane/tests/contract/api/test_guardrails.py`; expect PASS.
- [ ] **Step 5: Commit** `fix: approvals leave the inbox once decided or expired; sweep stuck replays; cap open approvals (PLAT-39)`

### Task 2: Deactivating an agent ends everything it started

**Files:**

- Modify: `apps/api/plane/utils/agents.py` (`on_agent_deactivated`)
- Test: `apps/api/plane/tests/unit/utils/test_managed_runs.py`

**Interfaces:**

- Consumes: `guardrails.expire_open_approvals(queryset)` (Task 1), `agent_runs.finish_run(run, status, summary=...)`, `managed_agents.cancel_agent_runs(agent)`.
- Produces: `on_agent_deactivated(agent)` runs three independent steps, each in its own savepoint with `log_exception` on failure (same pattern as `deactivate_agent`): `cancel_agent_runs(agent)` (managed runs, unchanged); `expire_open_approvals(AgentApproval.objects.filter(agent=agent, status="open"))`; `close_external_runs(agent)` — new in `agent_runs.py`: every `AgentRun` with `kind="external"`, `actor_id=agent.user_id`, status in `OPEN_STATUSES` → `finish_run(run, "cancelled", summary="Cancelled because the agent was deactivated")`, skipping runs that raise `AgentError` (finished concurrently). Returns the number closed.

- [ ] **Step 1: Write the failing tests** `test_deactivating_agent_expires_its_approvals` (two open approvals + one executed → both open ones `expired`, inbox rows read, executed untouched), `test_deactivating_agent_closes_its_external_runs` (a running external run reported by the agent → `cancelled` with the summary; a person's external run on the same item untouched), `test_deactivation_steps_are_independent` (patch `expire_open_approvals` to raise → external run still closed and agent still deactivated).
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `test_managed_runs.py` and `plane/tests/contract/app/test_agents.py`; expect PASS.
- [ ] **Step 5: Commit** `fix: deactivating an agent expires its approvals and closes its external runs (PLAT-35)`

### Task 3: Cloud run spending rules

**Files:**

- Modify: `apps/api/plane/utils/managed_agents.py` (`start_managed_run`, `send_follow_up`), `apps/api/plane/utils/ai_config.py` (`spent_this_month_cents`)
- Test: `apps/api/plane/tests/unit/utils/test_managed_runs.py`, `apps/api/plane/tests/unit/utils/test_ai_config.py`

**Interfaces:**

- Produces: `start_managed_run` and `send_follow_up` refuse a bot user (`user.is_bot`) before anything else: `AgentError("Only people can start or continue cloud runs", 403, "agent_id")`. Cancelling stays open to agents (it saves money).
- Produces: `spent_this_month_cents(workspace)` sums `cost_cents` of `AgentRun` rows with `kind="managed"` only. External runs keep reporting `cost_cents` for the run log; it no longer counts toward the limit.

- [ ] **Step 1: Write the failing tests** `test_agent_token_cannot_delegate` (POST `/api/v1/.../agent-runs/delegate/` with an agent's token → 403, no `AgentRun`, `sessions.create` not called), `test_agent_cannot_send_follow_up` (403, nothing sent), `test_external_run_cost_not_counted` (external run 900 + managed run 100 this month → 100; limit 500 lets a 300 budget start).
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run; expect PASS.
- [ ] **Step 5: Commit** `fix: only people start cloud runs, and only cloud runs count toward the AI limit (PLAT-37, PLAT-39)`

### Task 4: Long cloud runs keep GitHub access

**Files:**

- Modify: `apps/api/plane/utils/managed_agents.py` (`_repository_resources`, `start_managed_run`, `_sync_run`)
- Test: `apps/api/plane/tests/unit/utils/test_managed_runs.py`

**Interfaces:**

- Consumes: `github_app.forget_installation_token(installation_id)`, `github_app.installation_token(installation_id)`, `GitHubRepositoryLink` (project, installation, full_name, html_url).
- Produces: `refresh_repository_tokens(run, client) -> int` — lists the session's resources (`client.beta.sessions.resources.list(run.external_session_id)`), and for each `github_repository` resource whose `url` matches a linked repository of `run.project` (compare `html_url` or `https://github.com/{full_name}`, case-insensitive, trailing `.git`/`/` stripped) mints a fresh installation token (forget first, once per installation) and calls `client.beta.sessions.resources.update(resource.id, session_id=run.external_session_id, authorization_token=token)`. Returns the number updated; every error is logged and swallowed. Before writing, confirm the `resources.list`/`resources.update` signatures in the installed SDK (`python -c "import anthropic, inspect; print(inspect.signature(anthropic.Anthropic().beta.sessions.resources.update))"` in the test container); the Managed Agents docs give `resources.update(resource_id, {session_id, authorization_token})`.
- Schedule: `REFRESH_TOKENS_EVERY = timedelta(minutes=45)`. `start_managed_run` sets `cache.set(f"agent-run:{run.id}:gh-fresh", 1, 45 * 60)` after the session is created. `_sync_run`, for a run still open after the status handling, calls `refresh_repository_tokens` when `cache.add(f"agent-run:{run.id}:gh-fresh", 1, 45 * 60)` succeeds (the key expired) and the project has linked repositories.
- Mount paths: when two linked repositories share a repo name, both mount at `/workspace/{owner}-{repo}`; otherwise `/workspace/{repo}` as today.
- Failed brief send: when `sessions.create` succeeded but `events.send` of the brief raises, also send `user.interrupt` (errors swallowed) so the idle session is not left open.

- [ ] **Step 1: Write the failing tests** `test_long_run_refreshes_repository_tokens` (key absent → `resources.update` called once per linked repo with a token from a fresh `installation_token`; key present → not called), `test_token_refresh_failure_does_not_fail_run` (`resources.list` raises `anthropic.APIError` → run still `running`, error logged), `test_same_named_repos_get_distinct_mount_paths` (`acme/web` and `beta/web` → `/workspace/acme-web`, `/workspace/beta-web`), `test_failed_brief_send_interrupts_session` (run `failed`, `user.interrupt` sent to the created session).
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `test_managed_runs.py` and `test_managed_agents.py`; expect PASS.
- [ ] **Step 5: Commit** `fix: refresh GitHub tokens for cloud runs past 45 minutes (PLAT-37)`

### Task 5: Every work item and comment delete reaches the event log

Root cause (verify first): `webhook_activity` → `record_workspace_event` is the only path that writes `issue`/`issue_comment` feed rows, and it is only queued by `model_activity` (create/update) and project deletes. Work item deletes (`plane/api/views/issue.py` `delete`, `plane/app/views/issue/base.py` `destroy`, `BulkDeleteIssuesEndpoint`) and comment deletes queue only `issue_activity`, so no delete — by a person or by an approved agent replay — ever produced `issue deleted`. The production check saw only the `approval approved/executed` rows for that reason.

**Files:**

- Modify: `apps/api/plane/bgtasks/issue_activities_task.py` (`issue_activity`), `apps/api/plane/app/views/issue/base.py` (`BulkDeleteIssuesEndpoint`)
- Test: `apps/api/plane/tests/contract/api/test_events.py`

**Interfaces:**

- Produces: in `issue_activity`, after the activity rows are saved, `DELETE_EVENTS = {"issue.activity.deleted": "issue", "comment.activity.deleted": "issue_comment"}`; for those types queue `webhook_activity.delay(event=..., verb="deleted", field=None, old_value=None, new_value=None, actor_id=actor_id, slug=project.workspace.slug, current_site=origin, event_id=<issue_id, or requested_data["comment_id"] for comments>, old_identifier=None, new_identifier=None)`, in its own try/except with `log_exception`. One place covers the API view, the app view and approval replays. `_event_scope` already reads soft-deleted rows through `all_objects`; confirm it finds a deleted comment's project and work item.
- `BulkDeleteIssuesEndpoint` queues one `issue_activity(type="issue.activity.deleted", ...)` per deleted id (same arguments as the single destroy), so bulk deletes appear in activity and the feed too.
- Side effect to keep: webhooks with `issue=True` / `issue_comment=True` now also receive `deleted` deliveries with `{"id": ...}` (the existing `webhook_activity` shape for deletes).

- [ ] **Step 1: Write the failing tests** (follow how `test_events.py` already runs the activity tasks for `issue/updated`): `test_app_delete_reaches_feed` (person deletes through the app endpoint → feed has `issue/deleted` with the item id and `is_agent` False), `test_approved_agent_delete_emits_issue_deleted` (agent DELETE gated, owner approves → feed has `approval/approved`, `approval/executed` and `issue/deleted` with `is_agent` True), `test_comment_delete_reaches_feed`, `test_bulk_delete_reaches_feed` (two ids → two `issue/deleted` rows).
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `test_events.py`, `test_guardrails.py` and `plane/tests/contract/api/test_issues.py`; expect PASS.
- [ ] **Step 5: Commit** `fix: work item and comment deletes reach the event feed and webhooks (PLAT-40)`

### Task 6: Live-run polling only where something can be live

**Files:**

- Modify: `apps/api/plane/app/views/agents.py` (`LiveAgentRunsEndpoint`), `apps/web/services/agents.service.ts` (`getLiveRuns`), `apps/web/components/issues/issue-detail-widgets/agent-runs/live-runs.ts`
- Test: `apps/api/plane/tests/contract/api/test_agent_runs.py`, `apps/web/components/issues/issue-detail-widgets/agent-runs/__tests__/live-runs.test.ts`

**Interfaces:**

- Produces (API): `GET .../agent-runs/live/?issue_ids=...&meta=1` returns `{"runs": {<issue_id>: run_payload}, "poll": bool}`; without `meta` the old bare dict is returned (compatibility). `poll` is True when the workspace has an active `WorkspaceAgent` or any `AgentRun` in `OPEN_STATUSES`.
- Produces (web): `getLiveRuns(workspaceSlug, issueIds): Promise<{ runs: Record<string, TAgentRun>; poll: boolean }>` (sends `meta=1`). The batcher keeps `idleSince: Map<string, number>` per slug: a response with `poll: false` marks the slug idle; the 15 s timer skips idle slugs; an idle slug is checked again once `IDLE_RECHECK_MS = 300_000` has passed (one request), and a `poll: true` answer clears it.

- [ ] **Step 1: Write the failing tests** API `test_live_meta_reports_poll` (no agents and no open runs → `poll` False; an active agent → True; no agents but a running external run → True; no `meta` → bare dict). Web `stops polling a workspace that has nothing live` (fake timers; first response `poll: false` → no request at 15 s, 30 s, 60 s), `rechecks an idle workspace after five minutes` (one request after 300 s; `poll: true` → polling every 15 s resumes).
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run both; expect PASS; web type check, oxlint, oxfmt pass.
- [ ] **Step 5: Commit** `fix: skip live-run polling in workspaces with nothing live (PLAT-36)`

### Task 7: MCP agent tools authenticate like the other tools

**Files:**

- Modify: `deployments/plane-mcp/agent_tools.py` (`_api_key` → `_auth_headers`)
- Test: `deployments/plane-mcp/test_agent_tools.py`

**Interfaces:**

- Produces: `_auth_headers() -> dict[str, str]` mirroring upstream `plane_mcp/client.py` `get_plane_client_context`: no access token → `{"x-api-key": os.getenv("PLANE_API_KEY", "")}`; token whose `claims.get("auth_method", "oauth")` is `api_key_env` or `api_key_header` (our bearer path also sets `api_key_header`) → `{"x-api-key": token.token}`; any other token (OAuth) → the header `PlaneClient(access_token=...)` sends — read it from the installed SDK (`/usr/local/lib/python3.11/site-packages/plane/`) inside the image before writing; expected `{"Authorization": f"Bearer {token.token}"}`. `_request` uses it instead of `{"x-api-key": _api_key()}`.

- [ ] **Step 1: Write the failing tests** `test_oauth_connection_sends_bearer_not_api_key`, `test_api_key_header_connection_sends_x_api_key`, `test_bearer_api_key_connection_sends_x_api_key` (claims `auth_method="api_key_header"` from our provider), `test_environment_fallback_uses_plane_api_key`.
- [ ] **Step 2:** Build the image (`docker build -t plane-mcp-followups deployments/plane-mcp`) and run `docker run --rm --entrypoint python plane-mcp-followups -m pytest /app/plane_mcp/tools/test_agent_tools.py -q` the way P7 Task 11 did (copy the test file in with `-v` if the image doesn't carry it); expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Rebuild, rerun; expect PASS. Run `deployments/plane-mcp/e2e_bearer.sh` once; it still passes.
- [ ] **Step 5: Commit** `fix: MCP agent tools send OAuth tokens as bearer, not as an API key (PLAT-36)`

### Task 8: Agent admin and stream loose ends

**Files:**

- Modify: `apps/api/plane/utils/agents.py` (`update_agent`, `_clean_permission`), `apps/api/plane/utils/ai_config.py` (`update_settings`), `apps/api/plane/utils/managed_agents.py` (`sync_vault` display name on rename), `apps/api/plane/api/views/events.py` (`_generate`)
- Test: `apps/api/plane/tests/contract/app/test_agents.py`, `apps/api/plane/tests/unit/utils/test_managed_agents.py`, `apps/api/plane/tests/contract/api/test_events.py`

**Interfaces:**

- Rename: `update_agent` with a new name updates the bot user's `display_name`/`first_name`, every active `APIToken.label` to `f"agent:{name}"`, and queues `queue_sync(agent)`; `sync_agent` updates the vault's `display_name` to `f"plane-{slug}-{name}"` when it differs (`client.beta.vaults.update`; confirm the method in the SDK).
- `_clean_permission` (and `_clean_approval_actions`) reject unhashable or non-string values with the usual 400 instead of a 500.
- `update_settings`: when `model` changes or a new `api_key` is stored and the workspace is set up for cloud agents (`config.ma_environment_id`), queue `queue_sync(agent)` for every active agent, so Managed Agents agents follow the workspace model.
- Stream: `_generate` re-checks that the user is still an active workspace member every `MEMBERSHIP_CHECK_SECONDS = 30` and ends the stream when not; the first frame is `retry: 5000`.

- [ ] **Step 1: Write the failing tests** `test_rename_updates_token_label_and_queues_sync`, `test_unhashable_permission_is_a_400` (`{"permission": ["manage"]}` → 400), `test_model_change_resyncs_cloud_agents` (two active agents → two `queue_sync` calls; not set up → none), `test_stream_ends_after_member_removed` (short-interval override; remove membership; generator stops), `test_stream_sends_retry_first`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the three files; expect PASS.
- [ ] **Step 5: Commit** `fix: agent renames, model changes and lost membership reach tokens, cloud agents and the stream (PLAT-35, PLAT-40)`

### Task 9: Web loose ends on agents and runs

**Files:**

- Modify: `apps/web/components/agents/settings/token-reveal.tsx`, `apps/web/components/agents/settings/agent-form.tsx` (or `root.tsx`, where the PATCH body is built), `apps/web/components/issues/issue-detail-widgets/agent-runs/run-row.tsx`, `apps/web/components/issues/issue-detail-widgets/agent-runs/use-agent-runs.ts`, `packages/i18n/src/locales/en/milestone.json`

**Interfaces:**

- Token reveal: Escape and outside clicks don't close the dialog; only the "I stored it" button does.
- Edit agent: the PATCH body carries `project_ids` only when the selection changed.
- Run row: an expanded row refetches its steps when its run turns terminal (status changes), so the final steps show without a focus change; a steps load error shows `agents.runs.steps_error` with a retry.
- Cancel asks first (propel `AlertModalCore` or the confirm pattern the codebase uses): `agents.runs.cancel_confirm_title` "Cancel this run?", `agents.runs.cancel_confirm_body` "The cloud session stops now. Work it already pushed stays.", buttons `agents.runs.cancel_confirm` "Cancel run" / `common` "Keep running".

- [ ] **Step 1:** Implement the four changes and the English strings.
- [ ] **Step 2:** Type check, oxlint, oxfmt; `pnpm --filter=@plane/i18n sync:check` reports only the new keys missing in other locales (Task 11 fills them).
- [ ] **Step 3:** With `pnpm dev` against the local API: the token dialog survives Escape; editing an agent's name as a non-admin of one of its projects succeeds; cancelling a run asks first.
- [ ] **Step 4: Commit** `fix: agent token dialog, partial edits, run refresh and cancel confirmation (PLAT-35, PLAT-36)`

### Task 10: Hydration warning #418 and slow first load on work item pages

Goal: find out whether P7 caused them; fix only what P7 caused, and record the rest.

**Files:**

- Notes: `.superpowers/sdd/2026-11-22-p7-follow-ups/hydration.md` (git-ignored ledger folder)
- Modify (only if P7 is the cause): the P7 component found below

**Facts to start from:** `apps/web/react-router.config.ts` has `ssr: false`, so the only hydration is of the prerendered SPA shell (root layout and `HydrateFallback`); P7 components render inside routes, after that shell. P7 web changes on work item pages: `components/issues/issue-detail/main-content.tsx` (live pill), `issue-detail-widget-collapsibles.tsx` (Agent runs widget), list and kanban `block.tsx` (live dot via `useLiveAgentRun`, `useSyncExternalStore` with a null server snapshot).

- [ ] **Step 1:** Run the pre-P7 web image `ghcr.io/ujjwalsittu/plane-web:sha-b7887a8` and the current `sha-45fc4b5` locally against the same local API (`docker-compose-local.yml`), open the same work item page with a cold cache in the built-in browser, and record for each: console errors (#418 or not), number of requests before the title renders, and time to the title (Performance trace or `performance.now()` at first paint of the title). If a pre-P7 image tag is missing, build `b7887a824` from a temporary `git worktree` (remove it afterwards).
- [ ] **Step 2: Decide.** #418 and the slowness on both → pre-existing: write the findings (which component mismatches, from the React development build's full message) into the notes, and propose a separate work item to Ujjwal; no code change here. Only on `sha-45fc4b5` → bisect the four P7 web commits (`b076f0d`, `48bffbe`, `b7299a6`, `f8dd5ec`) and continue.
- [ ] **Step 3 (P7 cause only):** Write a failing vitest render test that reproduces the mismatch or counts the extra requests (e.g. the Agent runs widget fetching before it is expanded), fix it (defer the widget fetch until the widget is visible or opened; no live lookups before the page data loads), rerun, then repeat Step 1 on a local build.
- [ ] **Step 4: Commit** (only when code changed) `fix: <what> on work item pages (PLAT-36)`

### Task 11: Translate, verify and ship

**Files:**

- Modify: `packages/i18n/src/locales/<21 locales>/milestone.json` (new `agents` keys from Task 9)

- [ ] **Step 1:** Translate the new keys with the `translate` skill; `pnpm --filter=@plane/i18n sync:check` passes.
- [ ] **Step 2:** Full backend suite, web type check and vitest pass.
- [ ] **Step 3:** Ask Ujjwal before pushing. After the go-ahead: push, wait for "Custom images", deploy web/api/worker/beat with `APP_RELEASE=sha-<7>`, and the MCP image; verify `/version.json`. No migrations, so no pre-upgrade dump is needed.
- [ ] **Step 4:** Verify in production: approve an agent's delete from Slack → the Brief/inbox row disappears and the feed shows `issue/deleted`; delegating with an agent token over the MCP is refused; a board in a workspace without agents makes one live-run request, then none for 5 minutes; an OAuth MCP connection can call `agent_run list`.
- [ ] **Step 5:** Record what was verified in the ledger and in a comment on PLAT-35.
