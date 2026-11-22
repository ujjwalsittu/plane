# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Cloud agents on Claude Managed Agents: one environment per workspace, and for every Plane agent a matching
Managed Agents agent plus a vault holding its Plane API token for the Plane MCP server. Nothing here runs until a
workspace admin sets cloud agents up (the workspace's environment id is set)."""

import json
import re
import time
from contextlib import contextmanager
from datetime import timedelta
from urllib.parse import urlparse

import anthropic
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from plane.db.models import (
    AgentRun,
    APIToken,
    DecisionRequest,
    GitHubRepositoryLink,
    GitHubWorkItemLink,
    IssueComment,
    ProjectMember,
    WorkspaceAgent,
    WorkspaceAIConfig,
)
from plane.utils import agent_runs, github_app
from plane.utils.agents import MEMBER, AgentError, _require_admin
from plane.utils.ai_config import agent_cloud_ready, anthropic_client_for, check_spend, get_config, model_for
from plane.utils.exception_logger import log_exception

MCP_SERVER_NAME = "plane"
ERROR_PREFIX = "cloud_agents"
ALWAYS_ALLOW = {"type": "always_allow"}
# The setup endpoint runs in the request, so each of its calls is short and not retried.
SETUP_TIMEOUT_SECONDS = 10

AGENT_SYSTEM_PROMPT = """You work for the {workspace} workspace in Plane, through the Plane MCP tools.

- The work item in your first message is your brief. Read it, its comments and its links before you start.
- Post progress as comments on that work item, so the people following it can see where things stand.
- When you need a person's choice, create a decision request on the work item and stop until it is answered.
- Risky actions may answer `approval_required`. Note it in a comment and move on to other work; never retry it.
- Mounted repositories are under `/workspace`. Push a branch and open the pull request through the GitHub REST API;
  the git proxy authenticates those requests for you.
- Finish with a short summary of what changed and what is left."""


def _mcp_url():
    return getattr(settings, "PLANE_MCP_URL", "") or ""


def _client(workspace, client=None):
    if client is not None:
        return client
    client = anthropic_client_for(workspace)
    if client is None:
        raise AgentError("Add a Claude API key before setting up cloud agents", 400, ERROR_PREFIX)
    return client


def _plane_host():
    return urlparse(settings.WEB_URL or settings.APP_BASE_URL or "").hostname or ""


def _tools():
    return [
        {
            "type": "agent_toolset_20260401",
            "default_config": {"enabled": True, "permission_policy": ALWAYS_ALLOW},
            "configs": [
                {"name": "web_search", "enabled": False},
                {"name": "web_fetch", "enabled": False},
            ],
        },
        {
            "type": "mcp_toolset",
            "mcp_server_name": MCP_SERVER_NAME,
            "default_config": {"permission_policy": ALWAYS_ALLOW},
        },
    ]


def ensure_environment(workspace, client=None):
    """The workspace's cloud environment id, created on first use."""
    config = get_config(workspace)
    if config.ma_environment_id:
        return config.ma_environment_id
    hosts = [host for host in (_plane_host(), "api.github.com", "github.com") if host]
    environment = _client(workspace, client).beta.environments.create(
        name=f"plane-{workspace.slug}",
        config={
            "type": "cloud",
            "networking": {
                "type": "limited",
                "allow_package_managers": True,
                "allow_mcp_servers": True,
                "allowed_hosts": hosts,
            },
        },
    )
    config.ma_environment_id = environment.id
    config.save(update_fields=["ma_environment_id", "updated_at"])
    return environment.id


def sync_ma_agent(agent, client=None):
    """Create or update the agent's Managed Agents agent."""
    workspace = agent.workspace
    params = {
        "name": agent.name,
        "model": model_for(workspace),
        "system": AGENT_SYSTEM_PROMPT.format(workspace=workspace.name),
        "mcp_servers": [{"type": "url", "name": MCP_SERVER_NAME, "url": _mcp_url()}],
        "tools": _tools(),
    }
    agents_api = _client(workspace, client).beta.agents
    # No version on update: Plane owns this agent, so the latest definition always wins.
    remote = agents_api.update(agent.ma_agent_id, **params) if agent.ma_agent_id else agents_api.create(**params)
    agent.ma_agent_id = remote.id
    agent.ma_agent_version = remote.version
    agent.save(update_fields=["ma_agent_id", "ma_agent_version", "updated_at"])


def sync_vault(agent, token, client=None):
    """Put the agent's Plane token in its vault as the one credential for the Plane MCP server, replacing any
    earlier one (credential keys can't change, so the old credential is archived, which purges its secret).
    `ma_vault_token_id` is cleared first and set only once the new credential exists, so a failure part way
    never leaves the vault looking current."""
    vaults = _client(agent.workspace, client).beta.vaults
    token_id = APIToken.objects.filter(token=token).values_list("id", flat=True).first()
    agent.ma_vault_token_id = None
    agent.save(update_fields=["ma_vault_token_id", "updated_at"])
    if not agent.ma_vault_id:
        vault = vaults.create(display_name=f"plane-{agent.workspace.slug}-{agent.name}")
        agent.ma_vault_id = vault.id
        agent.save(update_fields=["ma_vault_id", "updated_at"])
    else:
        for credential in vaults.credentials.list(agent.ma_vault_id):
            if getattr(credential.auth, "type", "") == "static_bearer":
                vaults.credentials.archive(credential.id, vault_id=agent.ma_vault_id)
    vaults.credentials.create(
        agent.ma_vault_id, auth={"type": "static_bearer", "mcp_server_url": _mcp_url(), "token": token}
    )
    agent.ma_vault_token_id = token_id
    agent.save(update_fields=["ma_vault_token_id", "updated_at"])


def archive_ma_agent(agent, client=None):
    """A deactivated agent can't start new cloud sessions, and its vault (and token) is purged."""
    beta = _client(agent.workspace, client).beta
    if agent.ma_agent_id:
        beta.agents.archive(agent.ma_agent_id)
    if agent.ma_vault_id:
        beta.vaults.archive(agent.ma_vault_id)
    agent.ma_vault_token_id = None
    agent.save(update_fields=["ma_vault_token_id", "updated_at"])


def active_token(agent):
    """The agent's current API token row (id and token), or None."""
    return APIToken.objects.filter(user_id=agent.user_id, is_active=True).order_by("-created_at").first()


def _is_set_up(workspace):
    return WorkspaceAIConfig.objects.filter(workspace=workspace).exclude(ma_environment_id="").exists()


def _record_error(workspace, agent, exc):
    log_exception(exc)
    config = get_config(workspace)
    # The class name only: an error message is never allowed to carry a token into the settings payload.
    config.last_error = f"{ERROR_PREFIX}: could not sync {agent.name} ({type(exc).__name__})"
    config.save(update_fields=["last_error", "updated_at"])


def sync_agent(agent):
    """Bring the Managed Agents side in line with the agent as stored (the background task). A no-op until cloud
    agents are set up. The agent and vault steps run independently, so an agent-update failure never keeps a
    rotated token out of the vault. Errors are logged and recorded on the workspace's AI config."""
    if not _is_set_up(agent.workspace):
        return
    if not agent.is_active:
        try:
            archive_ma_agent(agent)
        except Exception as exc:
            _record_error(agent.workspace, agent, exc)
        return
    try:
        sync_ma_agent(agent)
    except Exception as exc:
        _record_error(agent.workspace, agent, exc)
    token = active_token(agent)
    if token is not None and agent.ma_vault_token_id != token.id:
        try:
            sync_vault(agent, token.token)
        except Exception as exc:
            _record_error(agent.workspace, agent, exc)


def queue_sync(agent):
    """Sync after the current transaction commits, in Celery, with only the agent id as the task argument."""
    if not _is_set_up(agent.workspace):
        return
    from plane.bgtasks.cloud_agents_task import sync_cloud_agent

    agent_id = str(agent.id)
    transaction.on_commit(lambda: sync_cloud_agent.delay(agent_id))


def setup_cloud_agents(workspace, actor):
    """Create the workspace environment (once) and sync every active agent with its current token. Runs in the
    request (an explicit admin action that reports errors), with a short timeout per call."""
    _require_admin(workspace, actor)
    if not _mcp_url():
        raise AgentError("PLANE_MCP_URL is not configured on this instance", 400, ERROR_PREFIX)
    client = _client(workspace).with_options(timeout=SETUP_TIMEOUT_SECONDS, max_retries=0)
    try:
        ensure_environment(workspace, client)
    except Exception as exc:
        log_exception(exc)
        raise AgentError(f"Could not create the cloud environment ({type(exc).__name__})", 400, ERROR_PREFIX)
    for agent in WorkspaceAgent.objects.filter(workspace=workspace, is_active=True).select_related("workspace"):
        try:
            sync_ma_agent(agent, client)
            token = active_token(agent)
            if token is not None and agent.ma_vault_token_id != token.id:
                sync_vault(agent, token.token, client)
        except Exception as exc:
            _record_error(workspace, agent, exc)
            raise AgentError(f"Could not set up {agent.name} ({type(exc).__name__})", 400, ERROR_PREFIX)
    config = get_config(workspace)
    if config.last_error.startswith(ERROR_PREFIX):
        config.last_error = ""
        config.save(update_fields=["last_error", "updated_at"])
    return config


# --- Delegated runs: a person hands a work item to a cloud agent; Plane starts a session and follows it. ---

SESSION_URL = "https://platform.claude.com/workspaces/default/sessions/{}"
MAX_REPOS = 3
BRIEF_COMMENTS = 10
BRIEF_TEXT_MAX = 8000
COMMENT_MAX = 1500
TOOL_INPUT_MAX = 200
STALL_AFTER = timedelta(hours=6)
UNSTARTED_AFTER = timedelta(minutes=5)
SYNC_LOCK_SECONDS = 300
# How long a follow-up or cancel waits for an in-flight sync of the same run before giving up with a 409
LOCK_WAIT_SECONDS = 5
DENY_MESSAGE = "Nobody is watching this session to approve tool calls. Do this another way, or note it in a comment."
PR_URL = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+")
PUSH_REMOTE = re.compile(r"^To (https://github\.com/\S+?)(?:\.git)?\s*$", re.MULTILINE)
PUSH_REF = re.compile(
    r"^\s*[ +*!=-]?\s*(\[new branch\]|[0-9a-f]{7,40}\.\.\.?[0-9a-f]{7,40})\s+(\S+)\s+->\s+(\S+)", re.MULTILINE
)


def _web_url():
    return (settings.WEB_URL or settings.APP_BASE_URL or "").rstrip("/")


def _identifier(issue):
    return f"{issue.project.identifier}-{issue.sequence_id}"


def _require_person(user):
    """Cloud runs cost money: only people start or continue them (cancelling stays open to agents)."""
    if user.is_bot:
        raise AgentError("Only people can start or continue cloud runs", 403, "agent_id")


def _require_member(project, user):
    """Delegating, following up and cancelling need project role member (15) or higher."""
    if not ProjectMember.objects.filter(project=project, member=user, is_active=True, role__gte=MEMBER).exists():
        raise AgentError("Only project members can work with cloud agents here", 403)


def _clip(value, limit):
    value = (value or "").strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _person_name(user):
    return (user.display_name or user.email) if user else "someone"


def build_brief(issue, instructions):
    """The first message of a delegated session: the work item as the agent should see it, then the person's
    instructions."""
    state = issue.state
    lines = [
        f"Work item {_identifier(issue)}: {issue.name}",
        f"URL: {_web_url()}/{issue.workspace.slug}/browse/{_identifier(issue)}/",
        f"State: {state.name} ({state.group})" if state else "State: none",
        f"Priority: {issue.priority or 'none'}",
        f"Start date: {issue.start_date.isoformat() if issue.start_date else 'none'}",
        f"Due date: {issue.target_date.isoformat() if issue.target_date else 'none'}",
        f"Milestone: {issue.milestone.title if issue.milestone_id else 'none'}",
        "",
        "Description:",
        _clip(issue.description_stripped, BRIEF_TEXT_MAX) or "(none)",
    ]
    comments = list(
        IssueComment.objects.filter(issue=issue).select_related("actor").order_by("-created_at")[:BRIEF_COMMENTS]
    )
    if comments:
        lines += ["", f"Latest comments (oldest first, up to {BRIEF_COMMENTS}):"]
        for comment in reversed(comments):
            when = comment.created_at.strftime("%Y-%m-%d")
            lines.append(f"- {_person_name(comment.actor)} on {when}: {_clip(comment.comment_stripped, COMMENT_MAX)}")
    decisions = DecisionRequest.objects.filter(issue=issue, status="open").select_related("asked_user")
    if decisions:
        lines += ["", "Open decision requests:"]
        lines += [f"- {_clip(d.question, COMMENT_MAX)} (asked of {_person_name(d.asked_user)})" for d in decisions]
    prs = GitHubWorkItemLink.objects.filter(issue=issue, kind=GitHubWorkItemLink.PULL_REQUEST)
    if prs:
        lines += ["", "Linked pull requests:"]
        lines += [f"- {pr.repository_full_name}#{pr.ref} {pr.title} {pr.url}".rstrip() for pr in prs]
    lines += ["", "Instructions:", _clip(instructions, BRIEF_TEXT_MAX) or "Work on this item as described above."]
    return "\n".join(lines)


def _repository_resources(project):
    """One github_repository resource per linked repository (at most three), each with an installation token
    minted now. No GitHub App, or no linked repositories, means no resources."""
    if not github_app.is_configured():
        return []
    links = (
        GitHubRepositoryLink.objects.filter(project=project, installation__suspended_at__isnull=True)
        .select_related("installation")
        .order_by("full_name")[:MAX_REPOS]
    )
    resources, fresh = [], set()
    for link in links:
        installation_id = link.installation.installation_id
        try:
            if installation_id not in fresh:
                # A fresh token: the cached one may be most of its hour old already.
                github_app.forget_installation_token(installation_id)
                fresh.add(installation_id)
            token = github_app.installation_token(installation_id)
        except github_app.GitHubAppError as exc:
            log_exception(exc)
            continue
        resources.append(
            {
                "type": "github_repository",
                "url": link.html_url or f"https://github.com/{link.full_name}",
                "authorization_token": token,
                "mount_path": f"/workspace/{link.full_name.split('/')[-1]}",
            }
        )
    return resources


def _api_error(action, exc):
    code = getattr(exc, "status_code", None)
    return f"Could not {action} ({type(exc).__name__}{f' {code}' if code else ''})"


def start_managed_run(issue, agent, delegated_by, instructions=""):
    """Delegate a work item to a cloud agent. Refusals raise AgentError and create nothing; once the run exists,
    an Anthropic error marks it failed (no retry)."""
    project, workspace = issue.project, issue.workspace
    _require_person(delegated_by)
    _require_member(project, delegated_by)
    instructions = agent_runs._text(instructions, "instructions", agent_runs.TEXT_MAX)
    if agent.workspace_id != workspace.id or not agent.is_active:
        raise AgentError("That agent is not active in this workspace", 400, "agent_id")
    if not ProjectMember.objects.filter(project=project, member_id=agent.user_id, is_active=True).exists():
        raise AgentError(f"{agent.name} is not a member of this project", 400, "agent_id")
    config = WorkspaceAIConfig.objects.filter(workspace=workspace).first()
    client = anthropic_client_for(workspace)
    if client is None or config is None or not config.ma_environment_id or not agent_cloud_ready(agent):
        raise AgentError("Cloud agents are not set up for this workspace", 400, ERROR_PREFIX)
    check_spend(workspace, agent.run_budget_cents)

    now = timezone.now()
    run = AgentRun.objects.create(
        project=project,
        issue=issue,
        agent=agent,
        actor=agent.user,
        delegated_by=delegated_by,
        kind="managed",
        status="queued",
        title=issue.name[: agent_runs.TITLE_MAX],
        instructions=instructions,
        started_at=now,
        last_event_at=now,
        created_by=delegated_by,
    )
    agent_runs.on_run_changed(run, "created")
    client = client.with_options(max_retries=0)
    try:
        session = client.beta.sessions.create(
            agent={"type": "agent", "id": agent.ma_agent_id, "version": agent.ma_agent_version},
            environment_id=config.ma_environment_id,
            vault_ids=[agent.ma_vault_id],
            title=f"{_identifier(issue)}: {issue.name}"[:200],
            metadata={"plane_run_id": str(run.id), "plane_workspace": workspace.slug},
            budget={"type": "limit", "max_list_cost": {"amount": str(agent.run_budget_cents), "currency": "USD"}},
            resources=_repository_resources(project),
        )
        agent_runs.update_managed_run(run, external_session_id=session.id, external_url=SESSION_URL.format(session.id))
        client.beta.sessions.events.send(
            session.id,
            events=[{"type": "user.message", "content": [{"type": "text", "text": build_brief(issue, instructions)}]}],
        )
    except Exception as exc:
        # Anything that goes wrong once the run exists fails it (class name and status code only), so no run is
        # ever left queued without a session.
        log_exception(exc)
        agent_runs.finish_run(run, "failed", error=_api_error("start the cloud session", exc))
    return run


def _block_text(content):
    return "\n".join(block.text for block in content or [] if getattr(block, "type", "") == "text").strip()


def _short_input(value):
    try:
        text = json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(value)
    return _clip(text, TOOL_INPUT_MAX)


def _result_steps(event):
    """Commit and PR steps read out of a tool result: git pushes and pull request links."""
    text = _block_text(event.content)
    if not text:
        return []
    steps = []
    remotes = PUSH_REMOTE.findall(text)
    if remotes:
        repository = remotes[0].removeprefix("https://github.com/")
        for range_, _src, dst in PUSH_REF.findall(text):
            data = {"repository": repository, "branch": dst, "range": range_}
            key = f"push:{repository}:{dst}:{range_}"[: agent_runs.EVENT_ID_MAX]
            steps.append(("commit", f"Pushed {dst} to {repository}", data, key))
    for url in dict.fromkeys(PR_URL.findall(text)):
        # Keyed by the URL, so a PR the agent looks at again is recorded once per run
        steps.append(("pr", f"Pull request {url}", {"url": url}, f"pr:{url}"[: agent_runs.EVENT_ID_MAX]))
    return steps


def _event_steps(event):
    """(kind, text, data, external_event_id) for each run-log step an event becomes."""
    kind = event.type
    if kind == "agent.message":
        text = _block_text(event.content)
        return [("message", text, {}, event.id)] if text else []
    if kind in ("agent.tool_use", "agent.mcp_tool_use"):
        name = event.name if kind == "agent.tool_use" else f"{event.mcp_server_name}.{event.name}"
        short = _short_input(event.input)
        return [("tool", f"{name} {short}", {"name": name, "input": short}, event.id)]
    if kind == "session.error":
        error = event.error
        message = getattr(error, "message", "") or getattr(error, "type", "error")
        return [("error", _clip(message, agent_runs.TEXT_MAX), {"type": getattr(error, "type", "")}, event.id)]
    if kind in ("agent.tool_result", "agent.mcp_tool_result"):
        return _result_steps(event)
    return []


def _send(client, run, events):
    client.beta.sessions.events.send(run.external_session_id, events=events)


def _finish_quietly(run, status, **kwargs):
    """Finish unless something else (a cancel, an overlapping sync) already did."""
    try:
        agent_runs.finish_run(run, status, **kwargs)
    except AgentError as exc:
        if exc.status_code != 409:
            raise


def _add_step_quietly(run, kind, text, data, key):
    try:
        return agent_runs.add_step(run, kind, text, data, key)
    except AgentError as exc:
        if exc.status_code != 409:
            raise
        return None


@contextmanager
def _run_lock(run, wait=0):
    """The per-run lock the sync holds. Follow-ups and cancels take it too (waiting up to `wait` seconds), so a
    sync working from an event list read before a follow-up can never finish the run the follow-up reopened."""
    key = f"agent-run-sync:{run.id}"
    deadline = time.monotonic() + wait
    while not cache.add(key, 1, SYNC_LOCK_SECONDS):
        if time.monotonic() >= deadline:
            raise AgentError("The run is syncing with its session, try again in a moment", 409, "status")
        time.sleep(0.2)
    try:
        yield
    finally:
        cache.delete(key)


def sync_run(run):
    """Bring a cloud run up to date with its session: new events become steps, then the session's status, cost
    and token totals are copied over. Safe to run again: steps are keyed by event id. Skipped while another
    sync, a follow-up or a cancel holds the run."""
    if not run.external_session_id or run.status in agent_runs.TERMINAL_STATUSES:
        return
    try:
        with _run_lock(run):
            _sync_run(run)
    except AgentError as exc:
        if exc.status_code != 409:
            raise


def _interrupt_quietly(run):
    """Best effort: the run ends in Plane whatever Anthropic says."""
    if not run.external_session_id:
        return
    try:
        client = anthropic_client_for(run.workspace)
        if client is not None:
            _send(client, run, [{"type": "user.interrupt"}])
    except Exception as exc:
        log_exception(exc)


def end_stalled_run(run):
    """Decided from Plane's own data, so a run whose sync keeps failing (no key, a revoked key, Anthropic down)
    still ends: a queued or running cloud run with nothing new for 6 hours fails. Waiting runs wait on a person."""
    run.refresh_from_db()
    if run.kind != "managed" or run.status not in ("queued", "running"):
        return False
    last = run.last_event_at or run.started_at or run.created_at
    if timezone.now() - last < STALL_AFTER:
        return False
    _interrupt_quietly(run)
    _finish_quietly(run, "failed", error="No progress for 6 hours")
    return True


def fail_unstarted_runs():
    """Queued cloud runs that never got a session (the request died part way) fail after 5 minutes."""
    cutoff = timezone.now() - UNSTARTED_AFTER
    for run in AgentRun.objects.filter(kind="managed", status="queued", external_session_id="", created_at__lt=cutoff):
        _finish_quietly(run, "failed", error="The cloud session never started")


def _sync_run(run):
    client = anthropic_client_for(run.workspace)
    if client is None:
        return
    session_id = run.external_session_id
    try:
        events = list(client.beta.sessions.events.list(session_id, order="asc", limit=100))
        session = client.beta.sessions.retrieve(session_id)
    except anthropic.NotFoundError:
        _finish_quietly(run, "failed", error="Session no longer exists")
        return

    seen = set(run.steps.exclude(external_event_id="").values_list("external_event_id", flat=True))
    last_message, last_idle, last_user_at, terminated = "", None, -1, False
    for index, event in enumerate(events):
        if event.type == "agent.message":
            last_message = _block_text(event.content) or last_message
        elif event.type == "session.status_idle":
            last_idle = (index, event)
        elif event.type in ("user.message", "user.interrupt"):
            last_user_at = index
        elif event.type == "session.status_terminated":
            terminated = True
        for kind, text, data, key in _event_steps(event):
            if key in seen:
                continue
            seen.add(key)
            _add_step_quietly(run, kind, text, data, key)
    run.refresh_from_db()
    if run.status in agent_runs.TERMINAL_STATUSES:
        return

    usage = session.usage
    cost = int(usage.list_cost.amount) if usage and usage.list_cost else None
    totals = {"input_tokens": (usage.input_tokens or 0) if usage else 0}
    totals["output_tokens"] = (usage.output_tokens or 0) if usage else 0
    if cost is not None:
        totals["cost_cents"] = cost
    if session.status in ("running", "rescheduling") and run.status == "queued":
        totals["status"] = "running"
    try:
        agent_runs.update_managed_run(run, **totals)
    except AgentError as exc:
        if exc.status_code != 409:
            raise
        return
    # An idle only counts when it came after the last message Plane sent (a follow-up not yet picked up).
    stop = last_idle[1].stop_reason if last_idle and last_idle[0] > last_user_at else None
    stop_type = getattr(stop, "type", "")

    if session.status == "terminated" or terminated:
        if stop_type == "end_turn":
            _finish_quietly(run, "succeeded", summary=last_message, cost_cents=cost)
        else:
            _finish_quietly(run, "failed", error="The session ended", cost_cents=cost)
        return
    if session.status == "idle" and stop_type == "end_turn":
        _finish_quietly(run, "succeeded", summary=last_message, cost_cents=cost)
        return
    if session.status == "idle" and stop_type == "budget_reached":
        _finish_quietly(run, "failed", error="Run budget reached", cost_cents=cost)
        return
    if session.status == "idle" and stop_type in ("retries_exhausted", "refusal"):
        error = "The session stopped after repeated errors" if stop_type == "retries_exhausted" else "Claude declined"
        _finish_quietly(run, "failed", error=error, cost_cents=cost)
        return
    if session.status == "idle" and stop_type == "requires_action":
        key = f"{last_idle[1].id}:requires_action"
        if key not in seen:
            deny = {"type": "user.tool_confirmation", "result": "deny", "deny_message": DENY_MESSAGE}
            _send(client, run, [{**deny, "tool_use_id": event_id} for event_id in stop.event_ids])
            text = "A tool call asked for approval; Plane denied it because cloud runs are unattended"
            _add_step_quietly(run, "error", text, {"event_ids": list(stop.event_ids)}, key)


def _require_managed(run, session=True):
    if run.kind != "managed" or (session and not run.external_session_id):
        raise AgentError("Only cloud runs can be steered from Plane", 400, "run")


def send_follow_up(run, user, text):
    """Send the session another message: only after the run succeeded or while it waits. It runs again."""
    _require_person(user)
    _require_member(run.project, user)
    _require_managed(run)
    text = agent_runs._text(text, "text", agent_runs.TEXT_MAX, required=True)
    with _run_lock(run, wait=LOCK_WAIT_SECONDS):
        run.refresh_from_db()
        return _send_follow_up(run, user, text)


def _send_follow_up(run, user, text):
    if run.status not in ("succeeded", "waiting"):
        raise AgentError("Follow-ups go to a run that has finished well or is waiting", 409, "status")
    check_spend(run.workspace)
    client = anthropic_client_for(run.workspace)
    if client is None:
        raise AgentError("Cloud agents are not set up for this workspace", 400, ERROR_PREFIX)
    try:
        _send(client, run, [{"type": "user.message", "content": [{"type": "text", "text": text}]}])
    except anthropic.APIError as exc:
        log_exception(exc)
        raise AgentError(_api_error("reach the cloud session", exc), 502)
    if run.status == "succeeded":
        agent_runs.reopen_run(run)
    else:
        agent_runs.update_managed_run(run, status="running")
    agent_runs.add_step(run, "status", f"Follow-up from {_person_name(user)}", {"text": text})
    return run


def cancel_run(run, user):
    """Stop the session (if it ever started) and mark the run cancelled."""
    _require_member(run.project, user)
    _require_managed(run, session=False)
    with _run_lock(run, wait=LOCK_WAIT_SECONDS):
        run.refresh_from_db()
        return _cancel_run(run, user)


def _cancel_run(run, user):
    if run.status in agent_runs.TERMINAL_STATUSES:
        raise AgentError("The run has already finished", 409, "status")
    client = anthropic_client_for(run.workspace) if run.external_session_id else None
    if client is not None:
        try:
            _send(client, run, [{"type": "user.interrupt"}])
        except anthropic.NotFoundError:
            pass
        except anthropic.APIError as exc:
            log_exception(exc)
            raise AgentError(_api_error("stop the cloud session", exc), 502)
    return agent_runs.finish_run(run, "cancelled", summary=f"Cancelled by {_person_name(user)}")


def cancel_agent_runs(agent):
    """A deactivated agent's open cloud runs are cancelled now; their sessions are interrupted in the background
    (independently of the archive the deactivation also queues)."""
    runs = AgentRun.objects.filter(agent=agent, kind="managed", status__in=agent_runs.OPEN_STATUSES)
    session_ids = []
    for run in runs:
        try:
            agent_runs.finish_run(run, "cancelled", summary="Cancelled because the agent was deactivated")
        except AgentError:
            continue
        if run.external_session_id:
            session_ids.append(run.external_session_id)
    if session_ids:
        from plane.bgtasks.agent_runs_task import interrupt_sessions

        workspace_id = str(agent.workspace_id)
        transaction.on_commit(lambda: interrupt_sessions.delay(workspace_id, session_ids))


def interrupt_sessions(workspace, session_ids):
    client = anthropic_client_for(workspace)
    if client is None:
        return
    for session_id in session_ids:
        try:
            client.beta.sessions.events.send(session_id, events=[{"type": "user.interrupt"}])
        except anthropic.APIError as exc:
            log_exception(exc)
