# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Workspace event log: a durable, cursor-paged record of what changed, for agents that react instead of poll."""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from plane.db.models import Issue, ProjectMember, Webhook, WorkspaceEvent
from plane.utils.exception_logger import log_exception

RETENTION_DAYS = 30
MAX_LIMIT = 500
GUEST_ROLE = 5
# Events that are also sent to webhooks with the matching flag. The older kinds (issue, project, cycle, module,
# issue_comment) are sent by webhook_activity, which records them here too.
WEBHOOK_EVENTS = ("decision", "approval", "agent_run", "milestone")


def _dispatch_webhooks(workspace_id, event, action, entity_id, project_id, actor_id, data):
    from plane.bgtasks.webhook_task import webhook_send_task
    from plane.db.models import Workspace

    slug = Workspace.objects.filter(pk=workspace_id).values_list("slug", flat=True).first()
    if slug is None:
        return
    payload = {"id": str(entity_id), "project": str(project_id) if project_id else None, **data}
    activity = {
        "field": None,
        "new_value": None,
        "old_value": None,
        "actor": {"id": str(actor_id)} if actor_id else None,
    }
    for webhook_id in Webhook.objects.filter(workspace_id=workspace_id, is_active=True, **{event: True}).values_list(
        "id", flat=True
    ):
        try:
            webhook_send_task.delay(
                webhook_id=str(webhook_id),
                slug=slug,
                event=event,
                event_data=payload,
                action=action,
                current_site=getattr(settings, "WEB_URL", "") or "",
                activity=activity,
            )
        except Exception as exc:  # a broker hiccup must not break the change that caused the event
            log_exception(exc)


def emit_event(
    workspace_id, event, action, entity_id, project_id=None, actor=None, data=None, is_agent=None, issue_id=None
):
    """Write one event row. `is_agent` defaults to "the actor is a bot"; callers that know the request came in
    through an API key pass True. The four newer kinds are also sent to webhooks that opted in, after commit.

    Best effort: the feed must never break the change that caused the event. A failure is logged and the
    event dropped (None is returned); the insert runs in a savepoint so the caller's transaction survives."""
    try:
        data = data or {}
        actor_id = getattr(actor, "id", None)
        if is_agent is None:
            is_agent = bool(getattr(actor, "is_bot", False))
        with transaction.atomic():
            row = WorkspaceEvent.objects.create(
                workspace_id=workspace_id,
                project_id=project_id,
                issue_id=issue_id,
                event=event,
                action=action,
                entity_id=entity_id,
                actor_id=actor_id,
                is_agent=bool(is_agent),
                data=data,
            )
        if event in WEBHOOK_EVENTS:
            transaction.on_commit(
                lambda: _dispatch_webhooks(workspace_id, event, action, entity_id, project_id, actor_id, data)
            )
        return row
    except Exception as exc:
        log_exception(exc)
        return None


def event_payload(row):
    return {
        "id": row.id,
        "event": row.event,
        "action": row.action,
        "entity_id": str(row.entity_id),
        "project_id": str(row.project_id) if row.project_id else None,
        "actor_id": str(row.actor_id) if row.actor_id else None,
        "is_agent": row.is_agent,
        "data": row.data,
        "created_at": row.created_at.isoformat(),
    }


def events_after(workspace, user, after_id=0, types=None, project_id=None, limit=100):
    """Events newer than `after_id`, oldest first, for projects `user` is an active member of plus workspace-level
    rows (no project). Agents and people follow the same rule."""
    member_projects = ProjectMember.objects.filter(member=user, is_active=True, project__workspace=workspace).values(
        "project_id"
    )
    rows = WorkspaceEvent.objects.filter(workspace=workspace, id__gt=after_id).filter(
        Q(project_id__isnull=True) | Q(project_id__in=member_projects)
    )
    # A guest in a project that hides other people's work items only sees rows about items they created
    restricted = ProjectMember.objects.filter(
        member=user,
        is_active=True,
        role=GUEST_ROLE,
        project__workspace=workspace,
        project__guest_view_all_features=False,
    ).values("project_id")
    own_issues = Issue.all_objects.filter(created_by=user, project_id__in=restricted).values("id")
    rows = rows.exclude(Q(project_id__in=restricted) & Q(issue_id__isnull=False) & ~Q(issue_id__in=own_issues))
    if types:
        rows = rows.filter(event__in=types)
    if project_id:
        rows = rows.filter(project_id=project_id)
    limit = max(1, min(int(limit), MAX_LIMIT))
    return [event_payload(row) for row in rows.order_by("id")[:limit]]


def prune_events():
    """Drop events past the retention window."""
    cutoff = timezone.now() - timedelta(days=RETENTION_DAYS)
    deleted, _ = WorkspaceEvent.objects.filter(created_at__lt=cutoff).delete()
    return deleted


def emit_milestone_event(request, milestone, action):
    """A milestone changed through the app or the API. An API-key request counts as an agent's."""
    from plane.utils.supervision import source_for

    emit_event(
        milestone.workspace_id,
        "milestone",
        action,
        milestone.id,
        project_id=milestone.project_id,
        actor=request.user,
        is_agent=source_for(request) == "api" or bool(request.user.is_bot),
        data={"title": milestone.title},
    )
