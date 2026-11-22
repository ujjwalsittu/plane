# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Run log: what an agent (or a person's own Claude Code session) did on a work item."""

from datetime import timedelta
from urllib.parse import urlparse

from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.utils import timezone

from plane.db.models import AgentRun, AgentRunStep, GitHubWorkItemLink
from plane.utils.agents import AgentError, agent_for_user

LIVE_WINDOW = timedelta(minutes=10)
TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")
LIVE_STATUSES = ("running", "queued")
OPEN_STATUSES = ("queued", "running", "waiting")
STEP_KINDS = {k for k, _ in AgentRunStep.KIND_CHOICES}
TITLE_MAX = 255
TEXT_MAX = 20000
EVENT_ID_MAX = 255
COST_MAX_CENTS = 2_000_000_000


def on_run_changed(run, action):
    """Hook called on create ("created"), each step ("step") and finish ("finished"): one feed event each.
    A step event carries only the run's step count and status, never step text, to keep the feed small."""
    from plane.utils.events import emit_event

    data = {"issue_id": _id(run.issue_id), "loop_id": _id(run.loop_id), "status": run.status, "kind": run.kind}
    if action == "step":
        data["steps"] = run.steps.count()
    elif action == "finished":
        data["cost_cents"] = run.cost_cents
    emit_event(
        run.workspace_id,
        "agent_run",
        action,
        run.id,
        project_id=run.project_id,
        actor=run.actor,
        data=data,
        issue_id=run.issue_id,
    )


def _id(value):
    return str(value) if value else None


def _text(value, field, limit, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise AgentError(f"{field} must be a string", 400, field)
    value = value.strip()
    if required and not value:
        raise AgentError(f"{field} is required", 400, field)
    if len(value) > limit:
        raise AgentError(f"{field} is too long", 400, field)
    return value


def _url(value):
    value = _text(value, "external_url", 1000)
    if value and urlparse(value).scheme not in ("http", "https"):
        raise AgentError("external_url must be an http(s) link", 400, "external_url")
    return value


def _cost(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= COST_MAX_CENTS:
        raise AgentError("cost_cents must be a whole number of cents", 400, "cost_cents")
    return value


def _touch(run, now):
    AgentRun.objects.filter(pk=run.pk).update(last_event_at=now)
    run.last_event_at = now


def start_external_run(issue, actor, data):
    """Record a run reported from outside (an agent's own loop or a Claude Code session) as running now."""
    now = timezone.now()
    run = AgentRun.objects.create(
        project=issue.project,
        issue=issue,
        agent=agent_for_user(actor),
        actor=actor,
        kind="external",
        status="running",
        title=_text(data.get("title"), "title", TITLE_MAX) or issue.name[:TITLE_MAX],
        instructions=_text(data.get("instructions"), "instructions", TEXT_MAX),
        external_session_id=_text(data.get("external_session_id"), "external_session_id", 255),
        external_url=_url(data.get("external_url")),
        started_at=now,
        last_event_at=now,
        created_by=actor,
    )
    on_run_changed(run, "created")
    return run


def add_step(run, kind, text, data=None, external_event_id=""):
    """Append a step. Returns None when the external event id was already recorded."""
    if kind not in STEP_KINDS:
        raise AgentError("Invalid step kind", 400, "kind")
    text = _text(text, "text", TEXT_MAX)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise AgentError("data must be an object", 400, "data")
    external_event_id = _text(external_event_id, "external_event_id", EVENT_ID_MAX)
    now = timezone.now()
    for _ in range(3):
        try:
            with transaction.atomic():
                # The run row lock serialises concurrent writers so seq stays gapless, and a finished run
                # takes no more steps even when the finish lands between the caller's check and this write
                locked = AgentRun.objects.select_for_update().get(pk=run.pk)
                if locked.status in TERMINAL_STATUSES:
                    raise AgentError("The run has already finished", 409, "status")
                steps = AgentRunStep.objects.filter(run=run)
                if external_event_id and steps.filter(external_event_id=external_event_id).exists():
                    return None
                seq = (steps.aggregate(m=Max("seq"))["m"] or 0) + 1
                step = AgentRunStep.objects.create(
                    run=run, seq=seq, kind=kind, text=text, data=data, external_event_id=external_event_id
                )
            break
        except IntegrityError:
            continue
    else:
        raise AgentError("Could not record the step, try again", 409)
    _touch(run, now)
    on_run_changed(run, "step")
    return step


def finish_run(run, status, summary="", error="", cost_cents=None):
    if status not in TERMINAL_STATUSES:
        raise AgentError("Status must be succeeded, failed or cancelled", 400, "status")
    summary = _text(summary, "summary", TEXT_MAX)
    error = _text(error, "error", TEXT_MAX)
    cost = _cost(cost_cents)
    with transaction.atomic():
        # Under the run row lock, so two finishers (the sync and a person cancelling) can't both win
        if AgentRun.objects.select_for_update().get(pk=run.pk).status in TERMINAL_STATUSES:
            raise AgentError("The run has already finished", 409, "status")
        now = timezone.now()
        run.status = status
        run.ended_at = now
        run.last_event_at = now
        run.summary = summary
        run.error = error
        fields = ["status", "ended_at", "last_event_at", "summary", "error", "updated_at"]
        if cost is not None:
            run.cost_cents = cost
            fields.append("cost_cents")
        run.save(update_fields=fields)
    on_run_changed(run, "finished")
    return run


MANAGED_FIELDS = {"delegated_by", "external_session_id", "external_url", "status", "input_tokens", "output_tokens"}
PATCH_STATUSES = ("running", "waiting")


def close_external_runs(agent):
    """Cancel the open external runs the agent reported (its session is gone with it); returns how many closed."""
    closed = 0
    for run in AgentRun.objects.filter(kind="external", actor_id=agent.user_id, status__in=OPEN_STATUSES):
        try:
            finish_run(run, "cancelled", summary="Cancelled because the agent was deactivated")
        except AgentError:
            continue  # finished concurrently
        closed += 1
    return closed


def update_managed_run(run, **fields):
    """Plane's own writes to a cloud run (no actor check): delegated_by, external_session_id, external_url, a
    non-terminal status, token totals and cost_cents. A status change touches last_event_at and is one feed
    event. Finishing goes through finish_run."""
    cost_given = "cost_cents" in fields
    cost = _cost(fields.pop("cost_cents", None))
    unknown = set(fields) - MANAGED_FIELDS
    if unknown:
        raise AgentError(f"Unknown run fields: {', '.join(sorted(unknown))}", 400)
    if "status" in fields and fields["status"] not in OPEN_STATUSES:
        raise AgentError("Use finish_run to end a run", 400, "status")
    with transaction.atomic():
        locked = AgentRun.objects.select_for_update().get(pk=run.pk)
        if locked.status in TERMINAL_STATUSES:
            raise AgentError("The run has already finished", 409, "status")
        changed = "status" in fields and fields["status"] != locked.status
        update = ["updated_at"]
        for name, value in fields.items():
            setattr(run, name, value)
            update.append(name)
        if cost_given:
            run.cost_cents = cost
            update.append("cost_cents")
        if changed:
            run.last_event_at = timezone.now()
            update.append("last_event_at")
        run.save(update_fields=update)
    if changed:
        on_run_changed(run, "updated")
    return run


def reopen_run(run):
    """A succeeded cloud run that got a follow-up is running again."""
    with transaction.atomic():
        if AgentRun.objects.select_for_update().get(pk=run.pk).status != "succeeded":
            raise AgentError("Only a succeeded run can be reopened", 409, "status")
        now = timezone.now()
        run.status = "running"
        run.ended_at = None
        run.last_event_at = now
        run.save(update_fields=["status", "ended_at", "last_event_at", "updated_at"])
    on_run_changed(run, "updated")
    return run


def update_run(run, data, actor):
    """Apply the reporter's PATCH. Only the run's actor may write."""
    if run.actor_id != actor.id:
        raise AgentError("Only the run's reporter can change it", 403)
    new_status = data.get("status")
    if new_status is not None and new_status not in (*PATCH_STATUSES, *TERMINAL_STATUSES):
        raise AgentError("Status must be running, waiting, succeeded, failed or cancelled", 400, "status")
    if new_status in TERMINAL_STATUSES:
        return finish_run(
            run,
            new_status,
            summary=data.get("summary", run.summary),
            error=data.get("error", run.error),
            cost_cents=data.get("cost_cents"),
        )
    if run.status in TERMINAL_STATUSES:
        raise AgentError("The run has already finished", 409, "status")
    fields = ["updated_at"]
    if new_status in PATCH_STATUSES and new_status != run.status:
        run.status = new_status
        run.last_event_at = timezone.now()
        fields += ["status", "last_event_at"]
    if "summary" in data:
        run.summary = _text(data["summary"], "summary", TEXT_MAX)
        fields.append("summary")
    if "error" in data:
        run.error = _text(data["error"], "error", TEXT_MAX)
        fields.append("error")
    if "external_url" in data:
        run.external_url = _url(data["external_url"])
        fields.append("external_url")
    if "cost_cents" in data:
        run.cost_cents = _cost(data["cost_cents"])
        fields.append("cost_cents")
    run.save(update_fields=fields)
    return run


def is_live(run, now=None):
    if run.status not in LIVE_STATUSES:
        return False
    last = run.last_event_at or run.started_at
    return last is not None and (now or timezone.now()) - last <= LIVE_WINDOW


def _links(run):
    # A loop's run has no work item, so no work item links to show
    if run.started_at is None or run.issue_id is None:
        return []
    since = Q(github_created_at__gte=run.started_at) | Q(github_created_at__isnull=True, created_at__gte=run.started_at)
    rows = GitHubWorkItemLink.objects.filter(
        since, issue_id=run.issue_id, kind__in=[GitHubWorkItemLink.PULL_REQUEST, GitHubWorkItemLink.COMMIT]
    ).order_by("github_created_at", "created_at")
    return [
        {"kind": row.kind, "ref": row.ref, "title": row.title, "url": row.url, "repository": row.repository_full_name}
        for row in rows
    ]


def _person(user):
    return {"id": str(user.id), "display_name": user.display_name or user.email}


def step_payload(step):
    return {
        "id": str(step.id),
        "seq": step.seq,
        "kind": step.kind,
        "text": step.text,
        "data": step.data,
        "external_event_id": step.external_event_id,
        "created_at": step.created_at.isoformat(),
    }


def run_payload(run, steps=False):
    agent = run.agent
    started, ended = run.started_at, run.ended_at
    if started:
        duration = int(((ended or run.last_event_at or started) - started).total_seconds())
    else:
        duration = None
    payload = {
        "id": str(run.id),
        "issue_id": _id(run.issue_id),
        "loop_id": _id(run.loop_id),
        "project_id": str(run.project_id),
        "kind": run.kind,
        "status": run.status,
        "title": run.title,
        "agent": {"id": str(agent.id), "name": agent.name, "avatar_url": agent.user.avatar_url} if agent else None,
        "actor": {
            "id": str(run.actor_id),
            "display_name": run.actor.display_name or run.actor.email,
            "is_agent": bool(run.actor.is_bot),
        },
        "delegated_by": _person(run.delegated_by) if run.delegated_by_id else None,
        "started_at": started.isoformat() if started else None,
        "ended_at": ended.isoformat() if ended else None,
        "duration_seconds": duration,
        "cost_cents": run.cost_cents,
        "summary": run.summary,
        "error": run.error,
        "external_url": run.external_url,
        "is_live": is_live(run),
        "links": _links(run),
    }
    if steps:
        payload["steps"] = [step_payload(s) for s in run.steps.order_by("seq")]
    return payload


def runs_for_loop(loop):
    return AgentRun.objects.filter(loop=loop).select_related("agent__user", "actor", "delegated_by")


def runs_for_issue(issue):
    return AgentRun.objects.filter(issue=issue).select_related("agent__user", "actor", "delegated_by")


def live_runs_for(issue_ids):
    """The newest live run per work item, as {issue_id: run_payload}, for list and Brief badges."""
    cutoff = timezone.now() - LIVE_WINDOW
    rows = (
        AgentRun.objects.filter(issue_id__in=list(issue_ids), status__in=LIVE_STATUSES)
        .filter(Q(last_event_at__gte=cutoff) | Q(last_event_at__isnull=True, started_at__gte=cutoff))
        .select_related("agent__user", "actor", "delegated_by")
        .order_by("-created_at")
    )
    live = {}
    for run in rows:
        live.setdefault(str(run.issue_id), run_payload(run))
    return live
