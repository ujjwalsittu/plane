# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""A project's home-page overview: rich text, linked pages and tags.

Shared by the app API (web) and the external API so both read and write it
the same way.
"""

# Django imports
from django.db.models import Prefetch, Q

# Module imports
from plane.db.models import Page, Project, ProjectTag
from plane.utils.content_validator import validate_html_content
from plane.utils.markdown import to_html


class OverviewError(ValueError):
    def __init__(self, field, message):
        super().__init__(message)
        self.field = field
        self.message = message


def tag_payload(tag):
    return {"id": str(tag.id), "name": tag.name, "color": tag.color}


def workspace_tags_payload(workspace_slug):
    """All of a workspace's project tags, each with the ids of the projects carrying it."""
    tags = (
        ProjectTag.objects.filter(workspace__slug=workspace_slug)
        .order_by("name")
        .prefetch_related(Prefetch("projects", queryset=Project.objects.filter(deleted_at__isnull=True).only("id")))
    )
    return [{**tag_payload(tag), "project_ids": [str(p.id) for p in tag.projects.all()]} for tag in tags]


def visible_project_pages(user, project):
    return Page.objects.filter(
        workspace_id=project.workspace_id,
        project_pages__project_id=project.id,
        project_pages__deleted_at__isnull=True,
    ).filter(Q(owned_by=user) | Q(access=Page.PUBLIC_ACCESS))


def overview_payload(user, project):
    linked_ids = [str(pid) for pid in (project.overview_page_ids or [])]
    pages = {str(p.id): p for p in visible_project_pages(user, project).filter(pk__in=linked_ids)}
    return {
        "project_id": str(project.id),
        "overview_html": project.overview_html or "<p></p>",
        # Linked pages in the order they were linked; ones the viewer cannot see are left out.
        "linked_pages": [
            {
                "id": pid,
                "name": pages[pid].name,
                "access": pages[pid].access,
                "archived_at": pages[pid].archived_at.isoformat() if pages[pid].archived_at else None,
            }
            for pid in linked_ids
            if pid in pages
        ],
        "overview_page_ids": linked_ids,
        "tags": [tag_payload(t) for t in project.tags.filter(deleted_at__isnull=True).order_by("name")],
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }


def update_overview(user, project: Project, data):
    """Apply overview_html / overview_markdown, overview_page_ids and tag_ids.
    Raises OverviewError on invalid input."""
    fields = []
    if "overview_html" in data or "overview_markdown" in data:
        html = to_html(data.get("overview_html"), data.get("overview_markdown"))
        if html is not None and not isinstance(html, str):
            raise OverviewError("overview_html", "Must be a string of HTML")
        is_valid, error, sanitized = validate_html_content(html or "")
        if not is_valid:
            raise OverviewError("overview_html", error)
        project.overview_html = (sanitized if sanitized is not None else html) or "<p></p>"
        fields.append("overview_html")

    if "overview_page_ids" in data:
        ids = data.get("overview_page_ids") or []
        if not isinstance(ids, list):
            raise OverviewError("overview_page_ids", "Must be a list of page ids")
        ids = [str(i) for i in ids]
        found = {str(pk) for pk in visible_project_pages(user, project).filter(pk__in=ids).values_list("id", flat=True)}
        missing = [i for i in ids if i not in found]
        if missing:
            raise OverviewError("overview_page_ids", f"Pages not found in this project: {', '.join(missing)}")
        project.overview_page_ids = list(dict.fromkeys(ids))
        fields.append("overview_page_ids")

    if fields:
        project.save(update_fields=fields + ["updated_at", "updated_by"])

    if "tag_ids" in data:
        ids = data.get("tag_ids") or []
        if not isinstance(ids, list):
            raise OverviewError("tag_ids", "Must be a list of tag ids")
        tags = list(ProjectTag.objects.filter(workspace_id=project.workspace_id, pk__in=ids))
        if len(tags) != len(set(map(str, ids))):
            raise OverviewError("tag_ids", "Some tags were not found in this workspace")
        project.tags.set(tags)


def create_tag(workspace_id, data):
    name = str(data.get("name") or "").strip()
    if not name:
        raise OverviewError("name", "Name is required")
    if ProjectTag.objects.filter(workspace_id=workspace_id, name__iexact=name).exists():
        raise OverviewError("name", f"A project tag named '{name}' already exists")
    return ProjectTag.objects.create(
        workspace_id=workspace_id, name=name[:255], color=str(data.get("color") or "")[:255]
    )


def update_tag(tag, data):
    if "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            raise OverviewError("name", "Name cannot be empty")
        if ProjectTag.objects.filter(workspace_id=tag.workspace_id, name__iexact=name).exclude(pk=tag.pk).exists():
            raise OverviewError("name", f"A project tag named '{name}' already exists")
        tag.name = name[:255]
    if "color" in data:
        tag.color = str(data.get("color") or "")[:255]
    tag.save()
    return tag
