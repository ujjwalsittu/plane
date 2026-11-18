# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Work logs (time tracking), shared by the external API (SDK/MCP) and the app API (web).
Durations are whole minutes."""

# Django imports
from django.db.models import Sum

# Module imports
from plane.app.permissions import ROLE
from plane.db.models import IssueWorkLog, ProjectMember

MAX_MINUTES = 60 * 24 * 7


class WorkLogError(ValueError):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def check_enabled(project):
    if not project.is_time_tracking_enabled:
        raise WorkLogError(
            "Time tracking is off for this project; turn it on in project settings "
            "(or project update is_time_tracking_enabled=true)"
        )


def _duration(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise WorkLogError("duration must be a whole number of minutes greater than 0")
    if value > MAX_MINUTES:
        raise WorkLogError("duration can't be more than a week (10080 minutes) in one entry")
    return value


def payload(log):
    return {
        "id": str(log.id),
        "issue_id": str(log.issue_id),
        "duration": log.duration,
        "description": log.description,
        "logged_by": str(log.logged_by_id),
        "project_id": str(log.project_id),
        "workspace_id": str(log.workspace_id),
        "created_by": str(log.created_by_id) if log.created_by_id else None,
        "updated_by": str(log.updated_by_id) if log.updated_by_id else None,
        "created_at": log.created_at.isoformat() if log.created_at else None,
        "updated_at": log.updated_at.isoformat() if log.updated_at else None,
    }


def create(user, issue, data):
    check_enabled(issue.project)
    return IssueWorkLog.objects.create(
        issue=issue,
        project_id=issue.project_id,
        logged_by=user,
        duration=_duration(data.get("duration")),
        description=str(data.get("description") or ""),
    )


def can_edit(user, log):
    if log.logged_by_id == user.id:
        return True
    return ProjectMember.objects.filter(
        project_id=log.project_id, member=user, role=ROLE.ADMIN.value, is_active=True
    ).exists()


def update(user, log, data):
    if not can_edit(user, log):
        raise WorkLogError("Only the person who logged the time or a project admin can change it", 403)
    if "duration" in data:
        log.duration = _duration(data.get("duration"))
    if "description" in data:
        log.description = str(data.get("description") or "")
    log.save()
    return log


def delete(user, log):
    if not can_edit(user, log):
        raise WorkLogError("Only the person who logged the time or a project admin can delete it", 403)
    log.delete()


def project_summary(project_id):
    """Total minutes per work item in a project."""
    rows = (
        IssueWorkLog.objects.filter(project_id=project_id, issue__deleted_at__isnull=True)
        .values("issue_id")
        .annotate(duration=Sum("duration"))
        .order_by("issue_id")
    )
    return [{"issue_id": str(row["issue_id"]), "duration": row["duration"]} for row in rows]
