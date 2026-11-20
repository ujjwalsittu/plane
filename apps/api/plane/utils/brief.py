# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The Brief: what needs a person, what is blocked, and what got done since they last looked."""

from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from plane.utils.decisions import decisions_for
from plane.utils.supervision import OPEN_GROUPS, blocked_items, is_agent_activity, work_item_payload

MENTION_SENDER = "in_app:issue_activities:mentioned"
MENTION_DAYS = 14
DEFAULT_WINDOW_HOURS = 24
MILESTONE_WINDOW_DAYS = 7


def _iso(value):
    return value.isoformat() if value else None


def _visible_issues(user, workspace_id):
    """Work items `user` may see in the workspace (a subquery, so joins never duplicate rows)."""
    from plane.api.views.issue import visible_issue_q
    from plane.db.models import Issue

    visible = Issue.issue_objects.filter(visible_issue_q(user)).values("id")
    return Issue.issue_objects.filter(workspace_id=workspace_id, id__in=visible)


def _since(workspace_id, user, since):
    from plane.db.models import BriefVisit

    if since is not None:
        return since
    visit = BriefVisit.objects.filter(workspace_id=workspace_id, user=user).first()
    if visit is not None:
        return visit.last_seen_at
    return timezone.now() - timedelta(hours=DEFAULT_WINDOW_HOURS)


def _needs_me(workspace_id, user, now):
    from plane.db.models import Issue, Notification

    visible = _visible_issues(user, workspace_id).filter(state__group__in=OPEN_GROUPS)
    wanted = []  # (issue_id, why, decision_id)
    wanted += [
        (pk, "assigned", None) for pk in visible.filter(issue_assignee__assignee=user).values_list("id", flat=True)
    ]
    mentioned = (
        Notification.objects.filter(
            workspace_id=workspace_id,
            receiver=user,
            sender=MENTION_SENDER,
            read_at__isnull=True,
            created_at__gte=now - timedelta(days=MENTION_DAYS),
            entity_identifier__in=visible.values("id"),
        )
        .values_list("entity_identifier", flat=True)
        .distinct()
    )
    wanted += [(pk, "mentioned", None) for pk in mentioned]
    decisions = decisions_for(workspace_id, user)
    wanted += [(decision["issue"]["id"], "decision", decision["id"]) for decision in decisions]

    ids = {pk for pk, _, _ in wanted}
    issues = {
        str(issue.id): issue
        for issue in Issue.issue_objects.filter(id__in=ids).select_related("state", "project", "milestone")
    }
    today = now.date()
    rows = []
    for pk, why, decision_id in wanted:
        issue = issues.get(str(pk))
        if issue is None:
            continue
        due = issue.target_date or (issue.milestone.target_date if issue.milestone else None)
        rows.append(
            {
                "issue": work_item_payload(issue),
                "why": why,
                "decision_id": decision_id,
                "due": _iso(due),
                "overdue": bool(due and due < today and issue.state.group in OPEN_GROUPS),
            }
        )
    # Overdue first, then soonest due, undated last (ISO dates sort as text).
    rows.sort(key=lambda row: (not row["overdue"], row["due"] is None, row["due"] or ""))
    return rows


def _done(workspace_id, user, since):
    from plane.db.models import IssueActivity, State

    completed_states = State.objects.filter(workspace_id=workspace_id, group="completed").values("id")
    finished = _visible_issues(user, workspace_id).filter(state__group="completed").values("id")
    activities = (
        IssueActivity.objects.filter(
            workspace_id=workspace_id,
            field="state",
            created_at__gt=since,
            new_identifier__in=completed_states,
            issue_id__in=finished,
        )
        .select_related("actor", "issue", "issue__project", "issue__state")
        .order_by("created_at")
    )
    latest = {}
    for activity in activities:  # ascending, so the last write per item is its latest completion
        latest[activity.issue_id] = activity
    groups = defaultdict(list)
    for activity in sorted(latest.values(), key=lambda a: a.created_at, reverse=True):
        actor = activity.actor
        groups[activity.issue.project].append(
            {
                "issue": work_item_payload(activity.issue),
                "completed_at": _iso(activity.created_at),
                "by": {
                    "id": str(actor.id) if actor else None,
                    "display_name": (actor.display_name or actor.email.split("@")[0]) if actor else None,
                    "is_agent": is_agent_activity(activity),
                },
            }
        )
    return [
        {"project_id": str(project.id), "project_identifier": project.identifier, "items": items}
        for project, items in sorted(groups.items(), key=lambda pair: pair[0].identifier)
    ]


def _milestones_due(workspace_id, user, today):
    from plane.db.models import Milestone

    milestones = {
        m.id: m
        for m in Milestone.objects.filter(
            workspace_id=workspace_id, target_date__lte=today + timedelta(days=MILESTONE_WINDOW_DAYS)
        ).select_related("project")
    }
    counts = {
        row["milestone_id"]: row
        for row in _visible_issues(user, workspace_id)
        .filter(milestone_id__in=list(milestones))
        .values("milestone_id")
        .annotate(
            total=Count("id", distinct=True),
            open=Count("id", filter=Q(state__group__in=OPEN_GROUPS), distinct=True),
            mine=Count("id", filter=Q(state__group__in=OPEN_GROUPS, issue_assignee__assignee=user), distinct=True),
        )
    }
    rows = []
    for milestone_id, milestone in milestones.items():
        count = counts.get(milestone_id)
        if not count or not count["open"]:
            continue
        rows.append(
            {
                "id": str(milestone.id),
                "title": milestone.title,
                "project_identifier": milestone.project.identifier,
                "target_date": _iso(milestone.target_date),
                "open": count["open"],
                "total": count["total"],
                "assigned_to_me_open": count["mine"],
            }
        )
    rows.sort(key=lambda row: (row["target_date"], row["title"]))
    return rows


def brief_for(workspace_id, user, since=None):
    now = timezone.now()
    since = _since(workspace_id, user, since)
    return {
        "since": _iso(since),
        "generated_at": _iso(now),
        "needs_me": _needs_me(workspace_id, user, now),
        "blocked": blocked_items(workspace_id, user),
        "done": _done(workspace_id, user, since),
        "milestones_due": _milestones_due(workspace_id, user, now.date()),
    }


def mark_seen(workspace_id, user):
    from plane.db.models import BriefVisit

    visit, _ = BriefVisit.objects.update_or_create(
        workspace_id=workspace_id, user=user, defaults={"last_seen_at": timezone.now()}
    )
    return visit
