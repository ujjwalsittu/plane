# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Milestone and work item type helpers shared by the app and external APIs."""

# Python imports
import json

# Django imports
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

# Module imports
from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import Issue, IssueType, Milestone, ProjectIssueType
from plane.utils.supervision import source_for

_ACTIVE_ISSUE = Q(
    issues__deleted_at__isnull=True,
    issues__archived_at__isnull=True,
    issues__is_draft=False,
)


def milestone_queryset(slug, project_id):
    """Milestones of a project with the issue counts the progress views need."""
    return (
        Milestone.objects.filter(workspace__slug=slug, project_id=project_id)
        .annotate(
            total_issues=Count("issues", filter=_ACTIVE_ISSUE, distinct=True),
            completed_issues=Count("issues", filter=_ACTIVE_ISSUE & Q(issues__state__group="completed"), distinct=True),
            cancelled_issues=Count("issues", filter=_ACTIVE_ISSUE & Q(issues__state__group="cancelled"), distinct=True),
            started_issues=Count("issues", filter=_ACTIVE_ISSUE & Q(issues__state__group="started"), distinct=True),
            unstarted_issues=Count("issues", filter=_ACTIVE_ISSUE & Q(issues__state__group="unstarted"), distinct=True),
            backlog_issues=Count("issues", filter=_ACTIVE_ISSUE & Q(issues__state__group="backlog"), distinct=True),
        )
        .order_by("sort_order", "target_date", "created_at")
    )


def set_issues_milestone(request, slug, project_id, issue_ids, milestone, origin, source=None):
    """Point ``issue_ids`` (of this project) at ``milestone`` (or clear it with
    None), recording one activity per changed work item. Returns the ids that
    changed; unknown ids are ignored. ``source`` defaults to how ``request``
    was authenticated (an API key is "api")."""
    source = source or source_for(request)
    target_id = milestone.id if milestone else None
    issues = list(
        Issue.issue_objects.filter(workspace__slug=slug, project_id=project_id, pk__in=issue_ids).values(
            "id", "milestone_id"
        )
    )
    changed = [row for row in issues if row["milestone_id"] != target_id]
    if not changed:
        return []
    with transaction.atomic():
        Issue.objects.filter(pk__in=[row["id"] for row in changed]).update(
            milestone_id=target_id, updated_at=timezone.now(), updated_by=request.user
        )
    epoch = int(timezone.now().timestamp())
    for row in changed:
        issue_activity.delay(
            type="issue.activity.updated",
            requested_data=json.dumps({"milestone_id": target_id}, cls=DjangoJSONEncoder),
            actor_id=str(request.user.id),
            issue_id=str(row["id"]),
            project_id=str(project_id),
            current_instance=json.dumps({"milestone_id": row["milestone_id"]}, cls=DjangoJSONEncoder),
            epoch=epoch,
            notification=True,
            origin=origin,
            source=source,
        )
    return [row["id"] for row in changed]


def project_issue_types(slug, project_id):
    """Work item types linked to a project."""
    return IssueType.objects.filter(
        workspace__slug=slug,
        project_issue_types__project_id=project_id,
        project_issue_types__deleted_at__isnull=True,
    ).order_by("level", "created_at")


def link_issue_type(issue_type, project):
    """Make ``issue_type`` usable in ``project`` (idempotent)."""
    link = ProjectIssueType.all_objects.filter(project=project, issue_type=issue_type).first()
    if link is None:
        ProjectIssueType.objects.create(project=project, workspace_id=project.workspace_id, issue_type=issue_type)
    elif link.deleted_at is not None:
        link.deleted_at = None
        link.save(update_fields=["deleted_at"])


def unlink_issue_type(issue_type, project):
    """Remove ``issue_type`` from ``project``: its work items lose the type,
    and the type itself is deleted once no project uses it."""
    with transaction.atomic():
        Issue.objects.filter(project=project, type=issue_type).update(type=None)
        ProjectIssueType.objects.filter(project=project, issue_type=issue_type).delete()
        if not ProjectIssueType.objects.filter(issue_type=issue_type).exists():
            issue_type.delete()


def enable_milestones(project):
    """Creating a milestone turns the feature on, so it shows up in the app."""
    if not project.milestone_view:
        project.milestone_view = True
        project.save(update_fields=["milestone_view"])


def default_epic_flag(data):
    """A type named "Epic" is an epic unless the caller says otherwise."""
    if "is_epic" not in data and str(data.get("name", "")).strip().lower() == "epic":
        return {**data, "is_epic": True}
    return data
