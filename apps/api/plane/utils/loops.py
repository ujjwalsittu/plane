# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Loops: a project runs a cloud agent on a schedule or on workspace events, as a person (the loop's owner), with
the project's state as the brief. Each run is an ordinary cloud run with no work item, linked to its loop."""

import re
from datetime import timedelta, timezone as dt_timezone

from django.core.cache import cache
from django.db import IntegrityError
from django.db.models import Max
from django.utils import timezone

from plane.db.models import (
    AgentLoop,
    AgentRun,
    DecisionRequest,
    Issue,
    Milestone,
    ProjectMember,
    User,
    WorkspaceAgent,
    WorkspaceEvent,
    WorkspaceMember,
)
from plane.utils import agent_runs
from plane.utils.agents import ADMIN, MEMBER, AgentError, _clean_name, _uuid
from plane.utils.exception_logger import log_exception

TRIGGERS = ("schedule", "event")
EVERY = ("hour", "day", "week")
EVENT_TYPES = ("issue", "issue_comment", "decision", "approval", "milestone")
REASONS = ("schedule", "event", "manual")
COOLDOWN_MIN = 15
COOLDOWN_MAX = 10080
COOLDOWN_DEFAULT = 60
AT = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
# One sweep of due loops at a time; the lock outlives a crashed worker by at most this long
DUE_LOCK = "agent-loops:due"
DUE_LOCK_SECONDS = 120
# Matching events one sweep reads per loop, and how many of them the brief lists
EVENTS_READ_MAX = 500
BRIEF_EVENTS = 20
BRIEF_LIST_MAX = 20
STALE_AFTER = timedelta(days=5)
SKIPPED_OPEN = "Skipped: the previous run is still open"
MILESTONES_WITHIN = timedelta(days=14)
RUNS_MAX = 50


# --- Who may see and manage loops ---


def can_manage(project, user):
    """Project admins and workspace admins create, edit, pause and delete loops."""
    if ProjectMember.objects.filter(project=project, member=user, is_active=True, role=ADMIN).exists():
        return True
    return WorkspaceMember.objects.filter(
        workspace_id=project.workspace_id, member=user, is_active=True, role=ADMIN
    ).exists()


def require_manager(project, user):
    if not can_manage(project, user):
        raise AgentError("Only project admins and workspace admins can manage loops", 403)


def require_viewer(project, user):
    """Project members (role 15 or higher) and managers see a project's loops and their runs."""
    if can_manage(project, user):
        return
    if not ProjectMember.objects.filter(project=project, member=user, is_active=True, role__gte=MEMBER).exists():
        raise AgentError("Only project members can see this project's loops", 403)


# --- Validation ---


def _clean_trigger(value):
    if value not in TRIGGERS:
        raise AgentError("Trigger must be schedule or event", 400, "trigger")
    return value


def _clean_schedule(value):
    if not isinstance(value, dict) or value.get("every") not in EVERY:
        raise AgentError("Schedule must say every hour, day or week", 400, "schedule")
    every = value["every"]
    if every == "hour":
        return {"every": "hour"}
    at = value.get("at")
    if not isinstance(at, str) or not AT.match(at):
        raise AgentError("Schedule time must be HH:MM (UTC)", 400, "schedule")
    if every == "day":
        return {"every": "day", "at": at}
    weekday = value.get("weekday")
    if isinstance(weekday, bool) or not isinstance(weekday, int) or not 0 <= weekday <= 6:
        raise AgentError("Weekday must be 0 (Monday) to 6 (Sunday)", 400, "schedule")
    return {"every": "week", "at": at, "weekday": weekday}


def _clean_event_types(value):
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(v, str) for v in value)
        or not set(value) <= set(EVENT_TYPES)
    ):
        raise AgentError(f"Event types must be a non-empty subset of {', '.join(EVENT_TYPES)}", 400, "event_types")
    return sorted(set(value))


def _clean_cooldown(value):
    if isinstance(value, bool) or not isinstance(value, int) or not COOLDOWN_MIN <= value <= COOLDOWN_MAX:
        raise AgentError(f"Cooldown must be between {COOLDOWN_MIN} and {COOLDOWN_MAX} minutes", 400, "cooldown_minutes")
    return value


def _clean_agent(project, value):
    agent = WorkspaceAgent.objects.filter(workspace_id=project.workspace_id, pk=_uuid(value, "agent_id")).first()
    if agent is None or not agent.is_active:
        raise AgentError("That agent is not active in this workspace", 400, "agent_id")
    if not ProjectMember.objects.filter(project=project, member_id=agent.user_id, is_active=True).exists():
        raise AgentError(f"{agent.name} is not a member of this project", 400, "agent_id")
    return agent


def _owner_is_member(project, user):
    return (
        user.is_active
        and not user.is_bot
        and ProjectMember.objects.filter(project=project, member=user, is_active=True, role__gte=MEMBER).exists()
    )


def _clean_owner(project, value):
    owner = User.objects.filter(pk=_uuid(value, "owner_id")).first()
    if owner is None or not _owner_is_member(project, owner):
        raise AgentError("The owner must be a person who is a member of this project", 400, "owner_id")
    return owner


def _newest_event_id(workspace_id):
    return WorkspaceEvent.objects.filter(workspace_id=workspace_id).aggregate(m=Max("id"))["m"] or 0


def _apply(loop, data, creating):
    """Validate and set the fields in `data` (all of them when creating)."""
    project = loop.project
    if creating or "name" in data:
        loop.name = _clean_name(data.get("name"))
    if creating or "agent_id" in data:
        loop.agent = _clean_agent(project, data.get("agent_id"))
    if "owner_id" in data:
        loop.owner = _clean_owner(project, data["owner_id"])
    if creating or "instructions" in data:
        loop.instructions = agent_runs._text(data.get("instructions"), "instructions", agent_runs.TEXT_MAX)
    if creating or "trigger" in data:
        loop.trigger = _clean_trigger(data.get("trigger"))
    if loop.trigger == "schedule" and (creating or "schedule" in data or "trigger" in data):
        loop.schedule = _clean_schedule(data.get("schedule", loop.schedule))
        loop.event_types = []
    if loop.trigger == "event" and (creating or "event_types" in data or "trigger" in data):
        loop.event_types = _clean_event_types(data.get("event_types", loop.event_types))
        loop.schedule = {}
    if "cooldown_minutes" in data:
        loop.cooldown_minutes = _clean_cooldown(data["cooldown_minutes"])
    if "is_active" in data:
        if not isinstance(data["is_active"], bool):
            raise AgentError("is_active must be true or false", 400, "is_active")
        loop.is_active = data["is_active"]


# --- Loops ---


def loops_for(project):
    return AgentLoop.objects.filter(project=project).select_related("agent__user", "owner", "project")


def create_loop(project, data, actor):
    """The creator owns the loop unless they pick another person in the project."""
    require_manager(project, actor)
    loop = AgentLoop(project=project, workspace_id=project.workspace_id, created_by=actor)
    _apply(loop, data, creating=True)
    if "owner_id" not in data:
        loop.owner = _clean_owner(project, actor.id)
    if AgentLoop.objects.filter(project=project, name=loop.name).exists():
        raise AgentError("A loop with this name already exists", 400, "name")
    # Event loops start from now; history from before the loop existed never triggers it
    loop.last_event_id = _newest_event_id(project.workspace_id)
    if loop.trigger == "schedule":
        loop.next_run_at = next_run_after(loop.schedule, timezone.now())
    try:
        loop.save()
    except IntegrityError:
        raise AgentError("A loop with this name already exists", 400, "name")
    return loop


def update_loop(loop, data, actor):
    require_manager(loop.project, actor)
    was_active, old_trigger, old_schedule = loop.is_active, loop.trigger, loop.schedule
    _apply(loop, data, creating=False)
    if AgentLoop.objects.filter(project=loop.project, name=loop.name).exclude(pk=loop.pk).exists():
        raise AgentError("A loop with this name already exists", 400, "name")
    resumed = loop.is_active and not was_active
    if resumed:
        # A paused loop comes back only with an active agent and an owner who is still in the project
        _clean_agent(loop.project, loop.agent_id)
        if not _owner_is_member(loop.project, loop.owner):
            raise AgentError("Pick an owner who is a member of this project", 400, "owner_id")
        loop.last_error = ""
    if loop.trigger == "schedule":
        if resumed or old_trigger != "schedule" or old_schedule != loop.schedule or loop.next_run_at is None:
            loop.next_run_at = next_run_after(loop.schedule, timezone.now())
    else:
        loop.next_run_at = None
        # Events that happened while the loop was paused (or before it listened to events) never trigger it
        if resumed or old_trigger != "event":
            loop.last_event_id = _newest_event_id(loop.workspace_id)
    loop.updated_by = actor
    try:
        loop.save()
    except IntegrityError:
        raise AgentError("A loop with this name already exists", 400, "name")
    return loop


def delete_loop(loop, actor):
    require_manager(loop.project, actor)
    loop.delete()


def _pause(loop, reason):
    loop.is_active = False
    loop.last_error = reason
    loop.save(update_fields=["is_active", "last_error", "updated_at"])


def pause_agent_loops(agent):
    """A deactivated agent's loops are paused, with the reason on each."""
    for loop in AgentLoop.objects.filter(agent=agent, is_active=True):
        _pause(loop, f"{agent.name} was deactivated")


def _iso(value):
    return value.isoformat() if value else None


def loop_payload(loop):
    agent, owner = loop.agent, loop.owner
    last_run = AgentRun.objects.filter(loop=loop).order_by("-created_at").first()
    return {
        "id": str(loop.id),
        "project_id": str(loop.project_id),
        "name": loop.name,
        "agent": {
            "id": str(agent.id),
            "name": agent.name,
            "avatar_url": agent.user.avatar_url,
            "is_active": agent.is_active,
        },
        "owner": {"id": str(owner.id), "display_name": owner.display_name or owner.email},
        "instructions": loop.instructions,
        "trigger": loop.trigger,
        "schedule": loop.schedule,
        "event_types": loop.event_types,
        "cooldown_minutes": loop.cooldown_minutes,
        "is_active": loop.is_active,
        "next_run_at": _iso(loop.next_run_at),
        "last_run_at": _iso(loop.last_run_at),
        "last_error": loop.last_error,
        "last_run": {"id": str(last_run.id), "status": last_run.status, "created_at": _iso(last_run.created_at)}
        if last_run
        else None,
        "created_at": _iso(loop.created_at),
    }


# --- Schedules ---


def next_run_after(schedule, after):
    """The first slot strictly after `after` (UTC): the next full hour, the next `at`, or the next `weekday` at
    `at`."""
    after = after.astimezone(dt_timezone.utc)
    every = schedule.get("every")
    if every == "hour":
        return after.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    hour, minute = (int(part) for part in schedule["at"].split(":"))
    slot = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if every == "day":
        return slot if slot > after else slot + timedelta(days=1)
    if every == "week":
        slot += timedelta(days=(schedule["weekday"] - slot.weekday()) % 7)
        return slot if slot > after else slot + timedelta(days=7)
    raise ValueError(f"Unknown schedule: {every}")


# --- Brief ---


def _visible_issues(project, user):
    from plane.api.views.issue import visible_issue_q

    visible = Issue.issue_objects.filter(visible_issue_q(user)).values("id")
    return Issue.issue_objects.filter(project=project, pk__in=visible)


def _identifier(project, issue):
    return f"{project.identifier}-{issue.sequence_id}"


def _event_line(row, project, issues):
    line = f"- {row.created_at.strftime('%Y-%m-%d %H:%M')} {row.event} {row.action}"
    issue = issues.get(row.issue_id) if row.issue_id else None
    if issue is not None:
        line += f": {_identifier(project, issue)} {issue.name}"
    elif row.event == "milestone" and isinstance(row.data, dict) and row.data.get("title"):
        line += f": {row.data['title']}"
    return line


def build_loop_brief(loop, events):
    """The first message of a loop's session: where the project stands as the owner sees it, the events that
    triggered the run (event loops), then the loop's instructions."""
    from plane.utils.managed_agents import _clip, _person_name, _web_url

    project, owner = loop.project, loop.owner
    now = timezone.now()
    today = now.date()
    issues = _visible_issues(project, owner)
    open_items = issues.exclude(state__group__in=("completed", "cancelled"))
    in_progress = issues.filter(state__group="started")
    lines = [
        f"Loop: {loop.name}",
        f"Project: {project.name} ({project.identifier})",
        f"URL: {_web_url()}/{project.workspace.slug}/projects/{project.id}/issues/",
        "This run comes from a loop, not a single work item: comment on the work items you act on.",
        "",
        f"Open work items: {open_items.count()}",
        f"In progress: {in_progress.count()}",
        f"Stale (in progress, no update for {STALE_AFTER.days} days): "
        f"{in_progress.filter(updated_at__lt=now - STALE_AFTER).count()}",
    ]
    milestones = Milestone.objects.filter(
        project=project, target_date__gte=today, target_date__lte=today + MILESTONES_WITHIN
    ).order_by("target_date")[:BRIEF_LIST_MAX]
    lines += ["", f"Milestones due in the next {MILESTONES_WITHIN.days} days:"]
    lines += [f"- {m.title} ({m.target_date.isoformat()})" for m in milestones] or ["- none"]
    decisions = (
        DecisionRequest.objects.filter(project=project, status="open", issue__in=issues)
        .select_related("issue", "asked_user")
        .order_by("created_at")[:BRIEF_LIST_MAX]
    )
    lines += ["", "Open decision requests:"]
    lines += [
        f"- {_identifier(project, d.issue)}: {_clip(d.question, 300)} (asked of {_person_name(d.asked_user)})"
        for d in decisions
    ] or ["- none"]
    events = list(events)
    if events:
        shown = events[-BRIEF_EVENTS:]
        visible = {
            issue.id: issue
            for issue in issues.filter(pk__in=[row.issue_id for row in shown if row.issue_id]).only(
                "id", "name", "sequence_id"
            )
        }
        heading = f"Events that triggered this run ({len(events)}"
        heading += f", newest {len(shown)} shown):" if len(shown) < len(events) else "):"
        lines += ["", heading]
        lines += [_event_line(row, project, visible) for row in shown]
    lines += ["", "Instructions:", _clip(loop.instructions, agent_runs.TEXT_MAX) or "Review the project and report."]
    return "\n".join(lines)


# --- Running ---


def run_loop(loop, reason, events=()):
    """Start the loop's cloud run as its owner. A deactivated agent or an owner no longer in the project pauses the
    loop; a refused start (limit reached, not set up) is recorded on the loop, which stays active."""
    from plane.utils.managed_agents import start_managed_session

    if reason not in REASONS:
        raise ValueError(f"Unknown reason: {reason}")
    agent, owner, project = loop.agent, loop.owner, loop.project
    if not agent.is_active:
        _pause(loop, f"{agent.name} was deactivated")
        return None
    if not _owner_is_member(project, owner):
        _pause(loop, "The loop's owner is no longer a member of this project")
        return None
    try:
        run = start_managed_session(
            project,
            agent,
            owner,
            loop.name,
            build_loop_brief(loop, events),
            loop=loop,
            instructions=loop.instructions,
        )
    except AgentError as exc:
        loop.last_error = exc.message
        loop.save(update_fields=["last_error", "updated_at"])
        return None
    loop.last_run_at = timezone.now()
    loop.last_error = ""
    loop.save(update_fields=["last_run_at", "last_error", "updated_at"])
    return run


def run_now(loop, actor):
    """A manager starts the loop now; refused while one of its runs is still open."""
    require_manager(loop.project, actor)
    if AgentRun.objects.filter(loop=loop, status__in=agent_runs.OPEN_STATUSES).exists():
        raise AgentError("A run of this loop is still open", 409, "status")
    run = run_loop(loop, "manual")
    if run is None:
        raise AgentError(loop.last_error or "The loop could not start", 400)
    return run


def _due_loops():
    return AgentLoop.objects.filter(
        is_active=True, project__deleted_at__isnull=True, project__archived_at__isnull=True
    ).select_related("agent__user", "owner", "project__workspace")


def run_due_loops():
    """The beat task: start every schedule loop whose slot has come and every event loop past its cooldown that has
    new matching events. One sweep at a time."""
    if not cache.add(DUE_LOCK, 1, DUE_LOCK_SECONDS):
        return
    try:
        now = timezone.now()
        for loop in _due_loops().filter(trigger="schedule", next_run_at__lte=now):
            try:
                # Advanced first, so a run that fails part way is never started again; missed slots are not replayed
                loop.next_run_at = next_run_after(loop.schedule, now)
                loop.save(update_fields=["next_run_at", "updated_at"])
                if _has_open_run(loop):
                    # The slot is skipped, not queued
                    loop.last_error = SKIPPED_OPEN
                    loop.save(update_fields=["last_error", "updated_at"])
                    continue
                run_loop(loop, "schedule")
            except Exception as exc:
                log_exception(exc)
        for loop in _due_loops().filter(trigger="event"):
            try:
                _run_event_loop(loop, now)
            except Exception as exc:
                log_exception(exc)
    finally:
        cache.delete(DUE_LOCK)


def _has_open_run(loop):
    return AgentRun.objects.filter(loop=loop, status__in=agent_runs.OPEN_STATUSES).exists()


def _run_event_loop(loop, now):
    if loop.last_run_at and now - loop.last_run_at < timedelta(minutes=loop.cooldown_minutes):
        return
    # The cursor stays put, so the events are picked up once the open run ends
    if _has_open_run(loop):
        return
    newer = WorkspaceEvent.objects.filter(
        workspace_id=loop.workspace_id, project_id=loop.project_id, id__gt=loop.last_event_id
    )
    # Filtered in SQL, so a busy feed of other events (agent_run steps, the loop's own agent) never crowds out a match
    matching = list(
        newer.filter(event__in=loop.event_types).exclude(actor_id=loop.agent.user_id).order_by("id")[:EVENTS_READ_MAX]
    )
    # The cursor moves to the newest matching row, or past everything newer when nothing matched
    cursor = matching[-1].id if matching else newer.aggregate(m=Max("id"))["m"]
    if cursor is None:
        return
    loop.last_event_id = cursor
    loop.save(update_fields=["last_event_id", "updated_at"])
    if matching:
        run_loop(loop, "event", matching)
