# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Pages linked to a work item, shared by the app API (web) and the external API (SDK/MCP).

A link is visible when its page is visible to the caller: a public page of the project, or one
they own. Private pages of other people can't be linked and are left out of lists.
"""

# Django imports
from django.db.models import Q

# Module imports
from plane.db.models import IssuePage, Page


class WorkItemPageError(ValueError):
    def __init__(self, field, message, status_code=400):
        super().__init__(message)
        self.field = field
        self.message = message
        self.status_code = status_code


def visible_pages(user, project_id):
    return Page.objects.filter(
        project_pages__project_id=project_id,
        project_pages__deleted_at__isnull=True,
    ).filter(Q(owned_by=user) | Q(access=Page.PUBLIC_ACCESS))


def links_for(user, project_id, issue_id):
    return (
        IssuePage.objects.filter(project_id=project_id, issue_id=issue_id)
        .filter(page__in=visible_pages(user, project_id))
        .select_related("page")
        .order_by("created_at")
    )


def _iso(value):
    return value.isoformat() if value else None


def link_payload(link):
    page = link.page
    return {
        "id": str(link.id),
        "page": {
            "id": str(page.id),
            "name": page.name,
            "logo_props": page.logo_props,
            "access": page.access,
            "archived_at": _iso(page.archived_at),
            "is_global": False,
            "created_at": _iso(page.created_at),
            "updated_at": _iso(page.updated_at),
            "created_by": str(page.created_by_id) if page.created_by_id else None,
        },
        "issue": str(link.issue_id),
        "project": str(link.project_id),
        "workspace": str(link.workspace_id),
        "created_at": _iso(link.created_at),
        "updated_at": _iso(link.updated_at),
        "created_by": str(link.created_by_id) if link.created_by_id else None,
    }


def create_link(user, issue, page_id):
    """Link a page to a work item; linking the same page again returns the existing link."""
    if not page_id:
        raise WorkItemPageError("page_id", "page_id is required")
    page = visible_pages(user, issue.project_id).filter(pk=page_id).first()
    if page is None:
        raise WorkItemPageError("page_id", "Page not found in this project")
    existing = IssuePage.objects.filter(issue=issue, page=page).select_related("page").first()
    if existing:
        return existing, False
    link = IssuePage.objects.create(issue=issue, page=page, project_id=issue.project_id)
    return link, True
