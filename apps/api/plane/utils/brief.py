# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The Brief: what needs a person, what is blocked, and what got done since they last looked."""

from collections import defaultdict
from html import unescape
from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import Count, Q
from django.utils import timezone
from django.utils.html import strip_tags

from plane.utils.decisions import decisions_for
from plane.utils.project_health import finish_from_counts, health_for, project_counts
from plane.utils.supervision import OPEN_GROUPS, blocked_items, is_agent_activity, work_item_payload

MENTION_SENDER = "in_app:issue_activities:mentioned"
MENTION_DAYS = 14
DEFAULT_WINDOW_HOURS = 24
MILESTONE_WINDOW_DAYS = 7
EXCERPT_LENGTH = 160
PROJECT_UPDATE_DAYS = 30


def _iso(value):
    return value.isoformat() if value else None


def _visible_issues(user, workspace_id):
    """Work items `user` may see in the workspace (a subquery, so joins never duplicate rows)."""
    from plane.api.views.issue import visible_issue_q
    from plane.db.models import Issue

    visible = Issue.issue_objects.filter(visible_issue_q(user)).values("id")
    return Issue.issue_objects.filter(workspace_id=workspace_id, id__in=visible)


FALLBACK_ZONE = "Asia/Kolkata"


def zone_for(user):
    """The person's timezone for everything date-based (the Brief and its Slack messages).

    Plane's ``user_timezone`` defaults to "UTC" and few people change it, so exactly "UTC" is treated as
    unset and means Asia/Kolkata (our team is in India). Anything empty or unknown does too."""
    name = user.user_timezone
    if not name or name == "UTC":
        name = FALLBACK_ZONE
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return ZoneInfo(FALLBACK_ZONE)


def _local_date(user, now):
    """Today's date in the person's own timezone."""
    return now.astimezone(zone_for(user)).date()


def _since(workspace_id, user, since):
    from plane.db.models import BriefVisit

    if since is not None:
        return since
    visit = BriefVisit.objects.filter(workspace_id=workspace_id, user=user).first()
    if visit is not None and visit.last_seen_at is not None:
        return visit.last_seen_at
    return timezone.now() - timedelta(hours=DEFAULT_WINDOW_HOURS)


def _needs_me(workspace_id, user, now):
    from plane.db.models import Issue, Notification

    visible = _visible_issues(user, workspace_id).filter(state__group__in=OPEN_GROUPS)
    wanted = []  # (issue_id, why, decision_id)
    wanted += [
        (pk, "assigned", None)
        for pk in visible.filter(issue_assignee__assignee=user, issue_assignee__deleted_at__isnull=True).values_list(
            "id", flat=True
        )
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
        .order_by()
        .values_list("entity_identifier", flat=True)
        .distinct()
    )
    wanted += [(pk, "mentioned", None) for pk in mentioned]
    decisions = decisions_for(workspace_id, user)
    # Oldest decision first, so the oldest one wins when an item has several.
    decisions.sort(key=lambda decision: decision["created_at"])
    wanted += [(decision["issue"]["id"], "decision", decision["id"]) for decision in decisions]

    # One row per work item: decision > mentioned > assigned; the first of a kind wins.
    rank = {"decision": 0, "mentioned": 1, "assigned": 2}
    best = {}
    for pk, why, decision_id in wanted:
        key = str(pk)
        if key not in best or rank[why] < rank[best[key][1]]:
            best[key] = (pk, why, decision_id)
    wanted = list(best.values())

    ids = {pk for pk, _, _ in wanted}
    issues = {
        str(issue.id): issue
        for issue in Issue.issue_objects.filter(id__in=ids).select_related("state", "project", "milestone")
    }
    today = _local_date(user, now)
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
            mine=Count(
                "id",
                filter=Q(
                    state__group__in=OPEN_GROUPS,
                    issue_assignee__assignee=user,
                    issue_assignee__deleted_at__isnull=True,
                ),
                distinct=True,
            ),
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


def _excerpt(html):
    text = " ".join(unescape(strip_tags(html or "")).split())
    return text if len(text) <= EXCERPT_LENGTH else text[: EXCERPT_LENGTH - 1].rstrip() + "\u2026"


def _projects(workspace_id, user, now, today):
    """Projects the person is in that have open work or a recent update, with health and predicted finish.

    Four queries however many projects there are: members, grouped counts, latest updates, the rows."""
    from plane.db.models import Project, ProjectMember, ProjectUpdate

    member_of = ProjectMember.objects.filter(
        workspace_id=workspace_id, member=user, is_active=True, project__deleted_at__isnull=True
    ).values("project_id")
    projects = list(
        Project.objects.filter(workspace_id=workspace_id, id__in=member_of, archived_at__isnull=True).order_by(
            "identifier"
        )
    )
    ids = [project.id for project in projects]
    counts = project_counts(_visible_issues(user, workspace_id), ids, now)
    # The latest update per project, however old (one query); recency only decides who stays in the strip.
    latest = {
        update.project_id: update
        for update in ProjectUpdate.objects.filter(workspace_id=workspace_id, project_id__in=ids)
        .order_by("project_id", "-created_at")
        .distinct("project_id")
        .select_related("created_by")
    }
    recent_cutoff = now - timedelta(days=PROJECT_UPDATE_DAYS)
    rows = []
    for project in projects:
        open_count, done = counts.get(project.id, (0, 0))
        update = latest.get(project.id)
        if not open_count and (update is None or update.created_at < recent_cutoff):
            continue
        predicted = finish_from_counts(open_count, done, today)
        by = update.created_by if update else None
        rows.append(
            {
                "id": str(project.id),
                "identifier": project.identifier,
                "name": project.name,
                "health": health_for(update, predicted, project.target_date),
                "latest_update": None
                if update is None
                else {
                    "health": update.health,
                    "excerpt": _excerpt(update.body_html),
                    "created_at": _iso(update.created_at),
                    "by": {
                        "display_name": (by.display_name or by.email.split("@")[0]) if by else None,
                        "is_agent": update.source == "api" or bool(by and by.is_bot),
                    },
                },
                "predicted_finish": _iso(predicted),
                "target_date": _iso(project.target_date),
            }
        )
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
        "milestones_due": _milestones_due(workspace_id, user, _local_date(user, now)),
        "projects": _projects(workspace_id, user, now, _local_date(user, now)),
    }


def mark_seen(workspace_id, user):
    from plane.db.models import BriefVisit

    visit, _ = BriefVisit.objects.update_or_create(
        workspace_id=workspace_id, user=user, defaults={"last_seen_at": timezone.now()}
    )
    return visit
