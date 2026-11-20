# P6 · Supervision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One cross-project screen and a Slack app that tell a person what's done, what's blocked and what needs them, with agent work told apart from human work.

**Architecture:** Backend features follow the P1–P5 pattern: logic in `plane/utils/<feature>.py`, external API views in `plane/api/views/<feature>.py` (SDK/MCP shapes, API-key auth) with session-auth app subclasses in `plane/app/views/<feature>.py`, routes in `plane/api/urls/<feature>.py` and `plane/app/urls/milestone.py`. The Brief is computed from live data on each request; the AI summary and Slack messages are built from the same `brief_for()` result. Background work runs on the existing Celery beat.

**Tech Stack:** Django 5 / DRF / Celery / Postgres (apps/api), React + MobX + SWR + `@makeplane/propel` (apps/web), Anthropic Python SDK (`anthropic`) for the AI summary, Slack Web API over `requests`.

**Spec:** `docs/superpowers/specs/2026-11-20-product-roadmap-design.md` (P6 items 1–7 and 8a). Plane work items: PLAT-27 to PLAT-34.

## Global Constraints

- New `.py`, `.ts`, `.tsx` files start with the repo's `COPYRIGHT.txt` header.
- Every new setting is stored **per workspace**, never instance-wide (shared multi-tenant hosting later). The only instance-wide config: `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` (default `claude-opus-5-5`), `SLACK_SIGNING_SECRET`.
- Agents vs people: `IssueActivity.source` is `"app"` (browser session) or `"api"` (API key, i.e. agents). An activity counts as an agent's when `source == "api"` or its actor has `is_bot=True` (e.g. the GitHub bot).
- "Open" means state group in `backlog, unstarted, started`. Stale means state group `started` with no `IssueActivity` for `STALE_DAYS = 7` days.
- A person only ever sees work items from projects where they are an active `ProjectMember`.
- Migrations: `uv run python manage.py makemigrations db -n <name>` (rewrites `migrations_lockfile.txt`; commit both).
- i18n: new strings go under a `supervision` key in `packages/i18n/src/locales/en/milestone.json`; the last task translates them into all 21 locales with the `translate` skill (never English copies).
- AI calls use the official `anthropic` SDK with `betas=["server-side-fallback-2026-07-01"]` and `fallbacks="default"` on `client.beta.messages.create`; never block a page on the AI call failing.
- Tests: `docker compose -f docker-compose-test.yml run --rm api-tests sh -c "pytest <path> -p no:cacheprovider --create-db -q"`; web: `pnpm turbo run check:types --filter=web`, `npx oxlint --deny-warnings <files>`, `pnpm exec oxfmt <files>`.
- Deploy per feature as in P1–P5: commit, push to `custom`, wait for "Custom images", run Coolify task `pre-upgrade-pgdump` when migrations are included, set `APP_RELEASE=sha-<7>`, deploy, verify `/version.json`.

## Review Focus

1. **Private projects:** a user who isn't a member of a project must see none of its items in the Brief, Slack brief, AI summary or decision lists — tested in Task 4 (`test_brief_hides_projects_user_is_not_in`).
2. **First visit:** with no saved last visit, "Done" covers the last 24 hours, not all history — Task 4 (`test_done_defaults_to_last_24h_on_first_visit`).
3. **Slack failures:** a revoked token (`invalid_auth`) or a person with no Slack account by email must not break the daily job for others; the connection is marked broken — Task 8 (`test_daily_brief_skips_broken_connection_and_unmatched_users`).
4. **Decision races:** answering twice, answering as someone who wasn't asked, or answering on a deleted work item returns 409/403/404 and records exactly one answer — Task 3 (`test_answer_rules`).
5. **Key rotation:** after `SECRET_KEY` changes, the stored Slack token can't be decrypted; settings must show "reconnect" and jobs skip that workspace instead of erroring — Task 7 (`test_connection_status_after_secret_key_change`).

---

### Task 1: Activity source (agent attribution, item 8a)

**Files:**

- Modify: `apps/api/plane/db/models/issue.py` (`IssueActivity`: add `source`)
- Modify: `apps/api/plane/bgtasks/issue_activities_task.py:1630` (`issue_activity` signature; set source before `bulk_create` at ~1710)
- Modify: every `issue_activity.delay(` in `apps/api/plane/api/views/{issue,intake,cycle,module,work_item_relation}.py` (25 call sites)
- Create migration: `db/migrations/0142_issueactivity_source.py`
- Test: `apps/api/plane/tests/contract/api/test_activity_source.py`

**Interfaces:**

- Produces: `IssueActivity.source: CharField(max_length=8, default="app")`; `issue_activity(..., source="app")`; `plane.utils.supervision.is_agent_activity(activity) -> bool` (`source == "api"` or `activity.actor.is_bot`); `plane.utils.supervision.SupervisionError(message, status_code=400, field="error")` (same shape as `ReleaseError`, used by Tasks 2–4 and 7).

- [ ] **Step 1: Write the failing test** `test_api_key_writes_are_marked_api` (create/update a work item through `/api/v1/...` with `api_key_client` and through `/api/workspaces/...` with `session_client`, run the activity task synchronously by monkeypatching `issue_activity.delay` to call the function, assert the API-created activities have `source == "api"` and the session ones `source == "app"`); and `test_bot_actor_is_agent` (activity by a user with `is_bot=True` → `is_agent_activity` is True).
- [ ] **Step 2:** Run it; expect FAIL (no `source` field).
- [ ] **Step 3:** Add the field and migration; add `source="app"` kwarg to `issue_activity` and set `activity.source = source` on every object before `bulk_create`. Confirm all 25 call sites use keyword arguments only (`grep -n "issue_activity.delay(" -A1`), then add `source="api",` as the first argument in each. Add `is_agent_activity` in a new `apps/api/plane/utils/supervision.py`.
- [ ] **Step 4:** Run the test; expect PASS. Run the full suite; expect all pass.
- [ ] **Step 5: Commit** `feat: record whether work item activity came from an agent or a person (PLAT-34)`

### Task 2: Blocked: waiting on and stale items (item 3)

**Files:**

- Create: `apps/api/plane/db/models/supervision.py` (`WorkItemWaiting`), register in `db/models/__init__.py`
- Modify: `apps/api/plane/utils/supervision.py`
- Create: `apps/api/plane/api/views/supervision.py`, `apps/api/plane/api/urls/supervision.py`, `apps/api/plane/app/views/supervision.py`; routes in `plane/app/urls/milestone.py`
- Test: `apps/api/plane/tests/contract/api/test_waiting_and_blocked.py`

**Interfaces:**

- Produces: model `WorkItemWaiting(workspace, project, issue, waiting_on_user: FK User null, waiting_on_text: CharField(255, blank), note: TextField(blank), resolved_at: DateTimeField null)` — at most one open row per issue (unique on `issue` where `resolved_at` is null and `deleted_at` is null).
- `set_waiting(issue, data, actor) -> WorkItemWaiting` (`waiting_on_user` must be an active workspace member, or `waiting_on_text` non-empty; one of them required → `SupervisionError(400)`), `clear_waiting(issue) -> None`.
- `blocked_items(workspace_id, user) -> list[dict]`, each `{"issue": <work item payload>, "reasons": [{"kind": "blocked_by"|"waiting_on"|"stale", "detail": str, "since": iso}]}` covering open items in the user's projects that have an open `blocked_by` relation to a not-completed/cancelled item, an open `WorkItemWaiting`, or are stale.
- Endpoints: `GET/PUT/DELETE /api/v1/workspaces/<slug>/projects/<project_id>/work-items/<issue_id>/waiting/` (+ app twin `/api/workspaces/.../issues/<issue_id>/waiting/`).
- Work item payload (shared): `{"id","name","identifier","project_id","project_identifier","state_group","state_name","priority","target_date","milestone_id"}` from `plane.utils.supervision.work_item_payload(issue)`.

- [ ] **Step 1: Write the failing tests** `test_waiting_on_person_and_external`, `test_waiting_requires_target`, `test_blocked_by_relation_listed_until_blocker_done`, `test_stale_after_seven_days` (set `IssueActivity.created_at` back 8 days), `test_completed_items_never_blocked`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement model, migration `0143_workitemwaiting`, helpers and views.
- [ ] **Step 4:** Run; expect PASS.
- [ ] **Step 5: Commit** `feat: waiting on, blocked-by and stale work items (PLAT-29)`

### Task 3: Decision requests (item 4)

**Files:**

- Modify: `apps/api/plane/db/models/supervision.py` (`DecisionRequest`)
- Create: `apps/api/plane/utils/decisions.py`
- Modify: `apps/api/plane/api/views/supervision.py`, `api/urls/supervision.py`, `app/views/supervision.py`, `app/urls/milestone.py`
- Test: `apps/api/plane/tests/contract/api/test_decisions.py`

**Interfaces:**

- Produces: `DecisionRequest(workspace, project, issue, asked_user FK User, question TextField, options JSONField(list[str], may be empty = free text), status CharField in ("open","answered","withdrawn"), answer TextField, answered_by FK User null, answered_at null, source CharField(8) like activity)`.
- `create_decision(issue, data, actor, source) -> DecisionRequest` (`asked_user` must be a project member; `question` required; `options` ≤ 10 strings), `answer_decision(decision, user, answer: str) -> DecisionRequest` (only `asked_user` → 403; non-open → 409; when `options` non-empty the answer must be one of them → 400), `withdraw_decision(decision, user)`.
- On answer: create an `IssueComment` on the work item by the answerer: `<p>Decision: <strong>{answer}</strong></p><p>{question}</p>`, and an `IssueActivity` with `field="decision"`. Fire `on_decision_created(decision)` hook (Task 8 subscribes) after create.
- `decisions_for(workspace_id, user, status="open") -> list[dict]` (`{"id","question","options","status","asked_user","requested_by","created_at","source","issue": work item payload}`).
- Endpoints: `GET/POST /api/v1/workspaces/<slug>/projects/<project_id>/work-items/<issue_id>/decisions/`, `POST .../decisions/<id>/answer/`, `POST .../decisions/<id>/withdraw/`; app twins; and `GET /api/workspaces/<slug>/decisions/?status=open` (mine).
- Today's convention counts too: the Brief's "Needs me" (Task 4) lists open items assigned to the user, so OSMG M1 items appear without migration.

- [ ] **Step 1: Write the failing tests** `test_agent_asks_and_person_answers` (API key creates with options `["Yes","No"]`, session user answers `"Yes"`, assert comment created and status `answered`), and `test_answer_rules` (second answer → 409; other user → 403; answer not in options → 400; deleted issue → 404).
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement model (migration `0144_decisionrequest`), helpers, views.
- [ ] **Step 4:** Run; expect PASS.
- [ ] **Step 5: Commit** `feat: decision requests on work items (PLAT-30)`

### Task 4: Brief API (item 1)

**Files:**

- Modify: `apps/api/plane/db/models/supervision.py` (`BriefVisit`)
- Create: `apps/api/plane/utils/brief.py`
- Modify: `apps/api/plane/app/views/supervision.py`, `app/urls/milestone.py`
- Test: `apps/api/plane/tests/contract/app/test_brief.py`

**Interfaces:**

- Consumes: `blocked_items`, `decisions_for`, `work_item_payload`, `is_agent_activity`.
- Produces: `BriefVisit(workspace, user, last_seen_at)` (unique per workspace+user); `brief_for(workspace_id, user, since=None) -> dict`:
  ```
  {"since": iso, "generated_at": iso,
   "needs_me": [{"issue": payload, "why": "assigned"|"mentioned"|"decision", "decision_id": str|None, "due": iso|None, "overdue": bool}],
   "blocked": [... from blocked_items],
   "done": [{"project_id","project_identifier","items": [{"issue": payload, "completed_at": iso, "by": {"id","display_name","is_agent": bool}}]}],
   "milestones_due": [{"id","title","project_identifier","target_date","open": int,"total": int,"assigned_to_me_open": int}]}
  ```
  `needs_me` order: overdue first, then by due date (item target date, else its milestone's), nulls last. "mentioned" = unread `Notification` rows of mention type for the user in the last 14 days. `done` = items whose state moved into the completed group after `since`, using the completing `IssueActivity` (actor + `is_agent_activity`). `since` defaults to `BriefVisit.last_seen_at`, else now − 24h. `milestones_due` = milestones with `target_date` within the next 7 days (or overdue) that have open items.
- Endpoints: `GET /api/workspaces/<slug>/brief/` → `brief_for(...)`; `POST /api/workspaces/<slug>/brief/seen/` → sets `last_seen_at=now`.

- [ ] **Step 1: Write the failing tests** `test_needs_me_orders_overdue_first`, `test_done_marks_agent_vs_person`, `test_done_defaults_to_last_24h_on_first_visit`, `test_seen_moves_the_window`, `test_milestones_due_within_week`, `test_brief_hides_projects_user_is_not_in`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement model (migration `0145_briefvisit`), `brief_for`, views.
- [ ] **Step 4:** Run; expect PASS.
- [ ] **Step 5: Commit** `feat: Brief API: needs me, blocked, done since last visit (PLAT-27)`

### Task 5: Brief page (web, items 1 and 8a)

**Files:**

- Create: `apps/web/services/supervision.service.ts`, `apps/web/components/brief/{root,needs-me,blocked,done,milestones-due,decision-answer}.tsx`, route files under `apps/web/app/(all)/[workspaceSlug]/(projects)/brief/` (layout, header, page)
- Modify: `apps/web/app/routes/core.ts`, `packages/constants/src/workspace.ts` (sidebar item `brief`, all roles, first in the pinned list), `apps/web/components/workspace/sidebar/{helper,sidebar-item}.tsx`, `packages/types/src/milestone.ts` (`TBrief`, `TDecisionRequest`, `TBlockedItem`), `packages/i18n/src/locales/en/milestone.json` (`supervision`)
- Test: type check + lint (apps/web has no unit runner for pages)

**Interfaces:**

- Consumes: Task 3 and 4 endpoints.
- Produces: `SupervisionService` with `getBrief(slug)`, `markSeen(slug)`, `answerDecision(slug, projectId, issueId, decisionId, answer)`, `setWaiting(...)`, `clearWaiting(...)`.

- [ ] **Step 1:** Build the page: milestones-due strip on top; three columns (Needs me, Blocked, Done) stacking on narrow screens; each row links to `/{slug}/browse/{identifier}/`; Done rows show an "Agent" or "Person" badge; decision rows answer inline (option buttons or a text field). "Mark all as seen" calls `markSeen` and refetches. Empty states per column.
- [ ] **Step 2:** Run `pnpm exec oxfmt`, `npx oxlint --deny-warnings` on the new files and `pnpm turbo run check:types --filter=web`; expect clean.
- [ ] **Step 3:** Check in the browser against local or production data: OSMG M1 items appear in Needs me, ordered by milestone date.
- [ ] **Step 4: Commit** `feat: Brief page (PLAT-27, PLAT-34)`

### Task 6: Waiting on and decisions on the work item (web, items 3 and 4)

**Files:**

- Create: `apps/web/components/issues/issue-detail-widgets/supervision/root.tsx`
- Modify: the work item detail widgets list (where the GitHub widget from P3 is registered)
- Test: type check + lint

- [ ] **Step 1:** Widget shows: current "waiting on" (person or text, note, since) with set/clear; open decision requests with answer controls for the asked person; "Ask for a decision" form (person, question, optional options).
- [ ] **Step 2:** Format, lint, type check; expect clean.
- [ ] **Step 3: Commit** `feat: waiting on and decision requests on the work item (PLAT-29, PLAT-30)`

### Task 7: Slack connection (item 6, part 1)

**Files:**

- Modify: `apps/api/plane/db/models/supervision.py` (`SlackConnection`, `SlackUserLink`)
- Create: `apps/api/plane/utils/slack_app.py`
- Modify: `apps/api/plane/settings/common.py` (`SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")`)
- Create: settings endpoints in `apps/api/plane/app/views/supervision.py`; web settings page `apps/web/app/(all)/[workspaceSlug]/(settings)/settings/(workspace)/slack/page.tsx` + `components/integration/slack/root.tsx` (admins only, like `settings/github`)
- Test: `apps/api/plane/tests/unit/utils/test_slack_app.py`

**Interfaces:**

- Produces: `SlackConnection(workspace unique, team_id, team_name, bot_token_encrypted, status in ("ok","broken"), last_error)`; `SlackUserLink(workspace, user, slack_user_id)`.
- `connect(workspace, bot_token) -> SlackConnection` (calls `auth.test`; stores `encrypt_data(token)`), `bot_token(connection) -> str | None` (`decrypt_data`; empty → mark `broken` with `last_error="reconnect"` and return None), `slack_call(connection, method, **params) -> dict` (POST `https://slack.com/api/{method}`, bearer token, 10 s timeout; `ok:false` with `invalid_auth|token_revoked|account_inactive` → mark broken), `link_users(connection) -> int` (match workspace members by email with `users.lookupByEmail`), `dm(connection, user, blocks, text) -> bool` (`conversations.open` + `chat.postMessage`; False when unlinked), `verify_signature(headers, body: bytes) -> bool` (Slack v0 HMAC-SHA256 over `v0:{timestamp}:{body}`, reject if older than 5 minutes).
- Endpoints: `GET/PUT/DELETE /api/workspaces/<slug>/slack/` (status, team, linked user count; PUT `{bot_token}` connects and links users).

- [ ] **Step 1: Write the failing tests** (mock `requests.post`): `test_connect_stores_encrypted_token`, `test_revoked_token_marks_broken`, `test_link_users_by_email`, `test_verify_signature_rejects_old_or_wrong`, `test_connection_status_after_secret_key_change` (override `SECRET_KEY` after connect → `bot_token` returns None and status becomes `broken`).
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement models (migration `0146_slack`), helpers, endpoints, settings page.
- [ ] **Step 4:** Run; expect PASS.
- [ ] **Step 5: Commit** `feat: per-workspace Slack connection (PLAT-32)`

### Task 8: Slack brief, alerts and decisions (item 6, part 2)

**Files:**

- Create: `apps/api/plane/bgtasks/supervision_task.py`
- Modify: `apps/api/plane/celery.py` (beat: `send-slack-briefs` hourly at minute 0; `send-milestone-alerts` daily 03:30 UTC)
- Modify: `apps/api/plane/utils/decisions.py` (`on_decision_created` → `notify_decision.delay(decision_id)`)
- Create: `apps/api/plane/app/views/slack_interactivity.py`; route `POST /api/slack/interactivity/` (no session auth; `verify_signature` required)
- Modify: `apps/api/plane/db/models/supervision.py` (`BriefVisit.slack_sent_on: DateField null`)
- Test: `apps/api/plane/tests/unit/bgtasks/test_supervision_task.py`

**Interfaces:**

- Consumes: `brief_for`, `dm`, `answer_decision`, `verify_signature`.
- Produces: `send_slack_briefs()` (every hour; for each `ok` connection and linked user whose local time — `User.user_timezone`, default `Asia/Kolkata` — is 09:xx and `slack_sent_on != today`: DM a brief with counts and the top 5 of each list, links to `/{slug}/brief`; set `slack_sent_on`); `send_milestone_alerts()` (DM each linked member with open items in milestones due tomorrow or overdue); `notify_decision(decision_id)` (DM the asked user with the question and one button per option, `action_id="decision:{id}:{index}"`; free-text decisions get an "Answer in Plane" link; also create a `Notification` for the asked user with `entity_name="decision"`, `sender="decision"`, `entity_identifier=decision.issue_id`, which Task 11's priority inbox reads).
- Interactivity: a button click calls `answer_decision` as the linked Plane user and replaces the message with "Answered: {answer}"; an unlinked Slack user gets an ephemeral "link your account" reply.

- [ ] **Step 1: Write the failing tests** `test_daily_brief_sent_once_at_9_local`, `test_daily_brief_skips_broken_connection_and_unmatched_users`, `test_milestone_alert_due_tomorrow`, `test_decision_dm_has_option_buttons`, `test_interactivity_answers_decision` (signed payload), `test_interactivity_rejects_bad_signature`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement tasks, beat entries, interactivity view, migration `0147_briefvisit_slack_sent_on`.
- [ ] **Step 4:** Run; expect PASS; then full suite.
- [ ] **Step 5: Commit** `feat: Slack daily brief, milestone alerts and decision answers (PLAT-32)`

### Task 9 (stretch): AI summary on the Brief (item 2)

**Files:**

- Modify: `apps/api/pyproject.toml` / `uv.lock` (`uv add anthropic==<latest 1.x>`)
- Create: `apps/api/plane/utils/brief_summary.py`
- Modify: `apps/api/plane/app/views/supervision.py` (`GET /api/workspaces/<slug>/brief/summary/`), `apps/web/components/brief/summary.tsx`
- Test: `apps/api/plane/tests/unit/utils/test_brief_summary.py`

**Interfaces:**

- Consumes: `brief_for`.
- Produces: `summarize(brief: dict) -> {"text": str, "item_ids": [str]}` — `anthropic.Anthropic()` (key from `ANTHROPIC_API_KEY`), `client.beta.messages.create(model=settings.CLAUDE_MODEL, max_tokens=1024, output_config={"effort": "low"}, betas=["server-side-fallback-2026-07-01"], fallbacks="default", system=<fixed instructions>, messages=[{"role":"user","content": <brief as compact JSON>}])`. Check `stop_reason`; on `refusal` or any `anthropic.APIError` return `None`. Cache per `(user, workspace, since, generated_at hour)` in Django cache for 1 hour. Summary text is 3–5 sentences, mentions items by identifier only from the brief.
- Endpoint returns `{"text": null}` when no key is configured or the call failed; the web shows nothing in that case.

- [ ] **Step 1: Write the failing tests** (mock the SDK client): `test_summary_uses_configured_model_and_low_effort`, `test_summary_none_on_refusal_or_error`, `test_summary_cached_for_an_hour`, `test_no_key_returns_none`.
- [ ] **Step 2–4:** Run (FAIL), implement, run (PASS).
- [ ] **Step 5: Commit** `feat: AI summary on the Brief (PLAT-28)`

### Task 10 (stretch): Project updates and health (item 5)

**Files:**

- Modify: `apps/api/plane/db/models/supervision.py` (`ProjectUpdate`)
- Create: `apps/api/plane/utils/project_health.py`
- Modify: supervision views/urls (external `GET/POST /api/v1/workspaces/<slug>/projects/<project_id>/updates/`, app twin), Brief payload gains `"projects": [{"id","identifier","health","latest_update","predicted_finish"}]`, web Brief strip
- Test: `apps/api/plane/tests/contract/api/test_project_updates.py`

**Interfaces:**

- Produces: `ProjectUpdate(workspace, project, health in ("on_track","at_risk","off_track"), body_html, source, created_by)`; `predicted_finish(project) -> date | None` = today + open items ÷ (items completed in the last 14 days ÷ 14); None when nothing completed in 14 days. `health` shown is the latest update's; when there's none, `at_risk` if `predicted_finish` is after the project target date, else `on_track`.

- [ ] **Step 1: Write the failing tests** `test_agent_posts_update_with_health`, `test_predicted_finish_from_recent_throughput`, `test_no_throughput_no_prediction`, `test_health_falls_back_to_prediction`.
- [ ] **Step 2–4:** Run (FAIL), implement (migration `0148_projectupdate`), run (PASS).
- [ ] **Step 5: Commit** `feat: project updates, health and predicted finish (PLAT-31)`

### Task 11 (stretch): Priority inbox (item 7)

**Files:**

- Modify: the app notifications list view (`apps/api/plane/app/views/notification/base.py`) to accept `?priority=action` returning unread, unsnoozed notifications that are mentions, assignments, or decision requests (Task 8 also creates a `Notification` with `entity_name="decision"` for each request), newest first
- Modify: web notifications sidebar to add a "Needs action" tab first
- Test: `apps/api/plane/tests/contract/app/test_priority_inbox.py`

- [ ] **Step 1: Write the failing test** `test_action_tab_lists_mentions_assignments_decisions_only`.
- [ ] **Step 2–4:** Run (FAIL), implement, run (PASS); format, lint and type check the web change.
- [ ] **Step 5: Commit** `feat: priority inbox (PLAT-33)`

### Task 12: Translate, verify and ship

**Files:**

- Modify: `packages/i18n/src/locales/<21 locales>/milestone.json` (`supervision` key)

- [ ] **Step 1:** Translate every `supervision` string into all 21 locales with the `translate` skill and the validator used in P5 (`check_i18n.py`); `pnpm --filter=@plane/i18n sync:check` passes.
- [ ] **Step 2:** Full backend suite and web type check pass.
- [ ] **Step 3:** Deploy with the Global Constraints procedure (migrations 0142–0148 → backup first).
- [ ] **Step 4:** Verify in production:
  - The Brief shows OSMG M1 items in Needs me.
  - A decision requested through the API appears in the Brief and as a Slack DM.
  - Answering it in Slack adds a comment on the item.
  - Done shows agent badges for MCP-made changes.
  - Connect Slack via the settings page with the internal app's bot token (needs `SLACK_SIGNING_SECRET` in Coolify; ask the user to create the Slack app and paste the token and secret).
- [ ] **Step 5:** Mark PLAT-27…34 Done as each lands; stretch items not finished by 2026-12-18 move to the P7 milestone.
