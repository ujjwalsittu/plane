# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Supervision: who did the work (an agent or a person) and what needs a human's attention."""

import uuid
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone


class SupervisionError(ValueError):
    def __init__(self, message, status_code=400, field="error"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.field = field


def source_for(request):
    """ "api" when the request came in with an API key (an agent), otherwise "app" (a person in the browser)."""
    from plane.api.middleware.api_authentication import APIKeyAuthentication

    return "api" if isinstance(getattr(request, "successful_authenticator", None), APIKeyAuthentication) else "app"


def is_agent_activity(activity):
    """An activity is an agent's when it came in through an API key or its actor is a bot user."""
    if activity.source == "api":
        return True
    return bool(activity.actor_id and activity.actor.is_bot)


# --- blocked and stale work items --------------------------------------------------------------

STALE_DAYS = 7
OPEN_GROUPS = ("backlog", "unstarted", "started")
DONE_GROUPS = ("completed", "cancelled")


def _iso(value):
    return value.isoformat() if value else None


def work_item_payload(issue):
    """The work item shape every supervision list shares."""
    project = issue.project
    state = issue.state
    return {
        "id": str(issue.id),
        "name": issue.name,
        "identifier": f"{project.identifier}-{issue.sequence_id}",
        "project_id": str(issue.project_id),
        "project_identifier": project.identifier,
        "state_group": state.group if state else None,
        "state_name": state.name if state else None,
        "priority": issue.priority,
        "target_date": _iso(issue.target_date),
        "milestone_id": str(issue.milestone_id) if issue.milestone_id else None,
    }


def _waiting_payload(row):
    user = row.waiting_on_user
    return {
        "id": str(row.id),
        "issue_id": str(row.issue_id),
        "waiting_on_user": str(row.waiting_on_user_id) if row.waiting_on_user_id else None,
        "waiting_on_name": (user.display_name or user.email) if user else None,
        "waiting_on_text": row.waiting_on_text,
        "note": row.note,
        "since": _iso(row.created_at),
    }


def waiting_payload(row):
    return _waiting_payload(row)


def set_waiting(issue, data, actor):
    """Mark `issue` as waiting on a workspace member or on free text, replacing any open row."""
    from plane.db.models import WorkItemWaiting, WorkspaceMember

    raw_user = data.get("waiting_on_user")
    text = data.get("waiting_on_text")
    text = text.strip() if isinstance(text, str) else ""
    note = data.get("note")
    note = note if isinstance(note, str) else ""
    if len(text) > 255:
        raise SupervisionError("waiting_on_text must be at most 255 characters", field="waiting_on_text")
    user_id = None
    if raw_user:
        try:
            user_id = uuid.UUID(str(raw_user))
        except ValueError:
            raise SupervisionError("waiting_on_user must be a user id", field="waiting_on_user")
        if not WorkspaceMember.objects.filter(
            workspace_id=issue.workspace_id, member_id=user_id, is_active=True
        ).exists():
            raise SupervisionError("waiting_on_user must be an active workspace member", field="waiting_on_user")
    if not user_id and not text:
        raise SupervisionError("Provide waiting_on_user or waiting_on_text", field="waiting_on_user")

    def _apply():
        with transaction.atomic():
            row = WorkItemWaiting.objects.select_for_update().filter(issue=issue, resolved_at__isnull=True).first()
            if row is None:
                row = WorkItemWaiting(issue=issue, project_id=issue.project_id, workspace_id=issue.workspace_id)
                row.created_by = actor
            row.waiting_on_user_id = user_id
            row.waiting_on_text = text
            row.note = note
            row.updated_by = actor
            row.save()
            return row

    try:
        return _apply()
    except IntegrityError:
        # A concurrent PUT inserted the open row first; retry, which now updates it.
        return _apply()


def clear_waiting(issue):
    """Resolve the open waiting row of `issue`, if any."""
    from plane.db.models import WorkItemWaiting

    WorkItemWaiting.objects.filter(issue=issue, resolved_at__isnull=True).update(resolved_at=timezone.now())


def blocked_items(workspace_id, user):
    """Open work items in the user's projects that are blocked, waiting or stale, with why.

    A `blocked_by` relation stores the blocked item as `issue` and the blocker as `related_issue`
    (the same reading the dependencies endpoint uses), so the blockers of X are the `related_issue`
    of rows where `issue` is X."""
    from plane.api.views.issue import visible_issue_q
    from plane.db.models import Issue, IssueActivity, IssueRelation, WorkItemWaiting

    items = {
        issue.id: issue
        for issue in Issue.issue_objects.filter(
            visible_issue_q(user), workspace_id=workspace_id, state__group__in=OPEN_GROUPS
        )
        .select_related("state", "project")
        .distinct()
    }
    reasons = {}

    def add(issue_id, kind, detail, since, hidden=False):
        reasons.setdefault(issue_id, []).append(
            {"kind": kind, "detail": detail, "since": _iso(since), "hidden": hidden}
        )

    relations = (
        IssueRelation.objects.filter(
            workspace_id=workspace_id,
            relation_type="blocked_by",
            issue_id__in=list(items),
            related_issue__archived_at__isnull=True,
            related_issue__deleted_at__isnull=True,
        )
        .exclude(related_issue__state__group__in=DONE_GROUPS)
        .select_related("related_issue", "related_issue__project")
        .order_by("created_at")
    )
    relations = list(relations)
    # Blocker titles are only disclosed for blockers the viewer can see.
    visible_blockers = set(
        Issue.issue_objects.filter(
            visible_issue_q(user), pk__in=[rel.related_issue_id for rel in relations]
        ).values_list("pk", flat=True)
    )
    for rel in relations:
        blocker = rel.related_issue
        if blocker.id in visible_blockers:
            detail = f"{blocker.project.identifier}-{blocker.sequence_id} {blocker.name}"
        else:
            detail = ""
        add(rel.issue_id, "blocked_by", detail, rel.created_at, hidden=not detail)

    waits = WorkItemWaiting.objects.filter(
        workspace_id=workspace_id, issue_id__in=list(items), resolved_at__isnull=True
    ).select_related("waiting_on_user")
    for row in waits:
        who = (row.waiting_on_user.display_name or row.waiting_on_user.email) if row.waiting_on_user else ""
        add(row.issue_id, "waiting_on", who or row.waiting_on_text, row.created_at)

    cutoff = timezone.now() - timedelta(days=STALE_DAYS)
    started = [issue_id for issue_id, issue in items.items() if issue.state.group == "started"]
    last_activity = dict(
        IssueActivity.objects.filter(issue_id__in=started)
        .values("issue_id")
        .annotate(last=Max("created_at"))
        .values_list("issue_id", "last")
    )
    for issue_id in started:
        last = last_activity.get(issue_id) or items[issue_id].created_at
        if last < cutoff:
            add(issue_id, "stale", f"No activity for {STALE_DAYS} days", last)

    return [{"issue": work_item_payload(items[issue_id]), "reasons": why} for issue_id, why in reasons.items()]
