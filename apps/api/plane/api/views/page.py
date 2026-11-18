# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""External API (``/api/v1``) for project pages, in the shapes the Plane SDK and
MCP server use.

Content is written as HTML. A page's editor works on a collaborative (Yjs)
document stored in ``description_binary``; when that is empty the live server
builds it from ``description_html`` the next time the page opens. So a page
created here has no binary, and an HTML update clears the binary, so the
editor shows the new content instead of the stored document.

Workspace pages (a wiki) and work item ↔ page links are not part of this
edition; their routes answer with a clear 400.
"""

# Python imports
from datetime import datetime

# Django imports
from django.db.models import Q

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.api.views.base import BaseAPIView
from plane.app.permissions import ProjectEntityPermission, ProjectPagePermission
from plane.app.serializers import PageSerializer
from plane.app.views.page.base import unarchive_archive_page_and_descendants
from plane.bgtasks.page_transaction_task import page_transaction
from plane.db.models import Issue, Page, ProjectMember, UserFavorite
from plane.utils.content_validator import validate_html_content
from plane.utils.markdown import looks_like_markdown, to_html
from plane.utils.work_item_pages import WorkItemPageError, create_link, link_payload, links_for

ADMIN = 20

_UPDATABLE = ("name", "access", "color", "is_locked", "logo_props", "view_props", "external_id", "external_source")


def page_payload(page):
    return {
        "id": str(page.id),
        "name": page.name,
        "description_html": page.description_html,
        "description_stripped": page.description_stripped,
        "owned_by": str(page.owned_by_id),
        "workspace": str(page.workspace_id),
        "projects": [str(pid) for pid in page.projects.values_list("id", flat=True)],
        "access": page.access,
        "color": page.color,
        "is_locked": page.is_locked,
        "archived_at": page.archived_at.isoformat() if page.archived_at else None,
        "parent_id": str(page.parent_id) if page.parent_id else None,
        "logo_props": page.logo_props,
        "external_id": page.external_id,
        "external_source": page.external_source,
        "created_at": page.created_at.isoformat() if page.created_at else None,
        "updated_at": page.updated_at.isoformat() if page.updated_at else None,
        # Collections are a workspace-pages feature; project pages are in none.
        "collection_id": None,
        "page_collection_id": None,
    }


def project_pages(request, slug, project_id):
    """Pages of a project the caller may see: public ones and their own."""
    return (
        Page.objects.filter(
            workspace__slug=slug,
            project_pages__project_id=project_id,
            project_pages__deleted_at__isnull=True,
        )
        .filter(Q(owned_by=request.user) | Q(access=Page.PUBLIC_ACCESS))
        .select_related("workspace")
        .distinct()
    )


def _clean_html(data):
    """The sanitised description_html of a request, or an error Response."""
    html = data.get("description_html")
    markdown = data.get("description_markdown")
    if markdown is not None or looks_like_markdown(html):
        if markdown is not None and not isinstance(markdown, str):
            return None, Response({"description_markdown": "Must be a string"}, status=status.HTTP_400_BAD_REQUEST)
        html = to_html(html, markdown)
    if html is None:
        return None, None
    if not isinstance(html, str):
        return None, Response({"description_html": "Must be a string of HTML"}, status=status.HTTP_400_BAD_REQUEST)
    is_valid, error, sanitized = validate_html_content(html)
    if not is_valid:
        return None, Response({"description_html": error}, status=status.HTTP_400_BAD_REQUEST)
    return (sanitized if sanitized is not None else html) or "<p></p>", None


def _can_manage(request, page, project_id):
    """Owner or project admin -- who may archive and delete, as in the app."""
    if page.owned_by_id == request.user.id:
        return True
    return ProjectMember.objects.filter(project_id=project_id, member=request.user, role=ADMIN, is_active=True).exists()


class ProjectPageListCreateAPIEndpoint(BaseAPIView):
    permission_classes = [ProjectPagePermission]
    model = Page

    def get(self, request, slug, project_id):
        queryset = project_pages(request, slug, project_id)
        archived = request.GET.get("archived", "false").lower() == "true"
        queryset = queryset.filter(archived_at__isnull=not archived)
        external_id = request.GET.get("external_id")
        external_source = request.GET.get("external_source")
        if external_id and external_source:
            queryset = queryset.filter(external_id=external_id, external_source=external_source)
        return self.paginate(
            request=request,
            queryset=queryset.order_by("sort_order", "created_at"),
            on_results=lambda pages: [page_payload(page) for page in pages],
        )

    def post(self, request, slug, project_id):
        data = request.data if isinstance(request.data, dict) else {}
        if not str(data.get("name") or "").strip():
            return Response({"name": "Name is required"}, status=status.HTTP_400_BAD_REQUEST)
        if data.get("collection_id"):
            return Response(
                {"collection_id": "Collections hold workspace pages only; omit project_id to create one"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        html, error = _clean_html(data)
        if error:
            return error

        external_source, external_id = data.get("external_source"), data.get("external_id")
        if external_source and external_id:
            existing = project_pages(request, slug, project_id).filter(
                external_source=external_source, external_id=external_id
            )
            if existing.exists():
                return Response(
                    {"error": "A page with this external id already exists", "id": str(existing.first().id)},
                    status=status.HTTP_409_CONFLICT,
                )

        payload = {key: data[key] for key in _UPDATABLE if key in data}
        payload["name"] = str(data["name"]).strip()
        parent_id = data.get("parent_id") or data.get("parent")
        if parent_id:
            if not project_pages(request, slug, project_id).filter(pk=parent_id).exists():
                return Response(
                    {"parent_id": "Parent page not found in this project"}, status=status.HTTP_404_NOT_FOUND
                )
            payload["parent"] = parent_id

        serializer = PageSerializer(
            data=payload,
            context={
                "project_id": project_id,
                "owned_by_id": request.user.id,
                "description_json": {},
                "description_binary": None,
                "description_html": html or "<p></p>",
            },
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        page = serializer.save()
        # PageSerializer does not take these; set them on the new row.
        extra = {key: payload[key] for key in ("is_locked", "external_id", "external_source") if key in payload}
        if extra:
            Page.objects.filter(pk=page.pk).update(**extra)
        page_transaction.delay(new_description_html=html or "<p></p>", old_description_html=None, page_id=page.id)
        return Response(page_payload(Page.objects.get(pk=page.pk)), status=status.HTTP_201_CREATED)


class ProjectPageDetailAPIEndpoint(BaseAPIView):
    permission_classes = [ProjectPagePermission]
    model = Page

    def get(self, request, slug, project_id, page_id):
        page = project_pages(request, slug, project_id).get(pk=page_id)
        return Response(page_payload(page), status=status.HTTP_200_OK)

    def put(self, request, slug, project_id, page_id):
        page = project_pages(request, slug, project_id).get(pk=page_id)
        data = request.data if isinstance(request.data, dict) else {}
        unlocking = data.get("is_locked") is False
        if page.is_locked and not unlocking:
            return Response({"error": "Page is locked"}, status=status.HTTP_400_BAD_REQUEST)
        if "access" in data and data["access"] != page.access and page.owned_by_id != request.user.id:
            return Response(
                {"error": "Access cannot be updated since this page is owned by someone else"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        html, error = _clean_html(data)
        if error:
            return error

        fields = []
        for key in _UPDATABLE:
            if key in data and data[key] is not None:
                value = str(data[key]).strip() if key == "name" else data[key]
                if key == "name" and not value:
                    return Response({"name": "Name cannot be empty"}, status=status.HTTP_400_BAD_REQUEST)
                setattr(page, key, value)
                fields.append(key)
        old_html = page.description_html
        if html is not None and html != old_html:
            page.description_html = html
            # Let the live server rebuild the editor document from the new HTML.
            page.description_binary = None
            page.description_json = {}
            fields += ["description_html", "description_binary", "description_json", "description_stripped"]
        if fields:
            page.save(update_fields=sorted(set(fields + ["updated_at", "updated_by"])))
        if html is not None and html != old_html:
            page_transaction.delay(new_description_html=html, old_description_html=old_html, page_id=page.id)
        return Response(page_payload(page), status=status.HTTP_200_OK)

    def delete(self, request, slug, project_id, page_id):
        page = project_pages(request, slug, project_id).get(pk=page_id)
        if page.archived_at is None:
            return Response(
                {"error": "The page should be archived before deleting"}, status=status.HTTP_400_BAD_REQUEST
            )
        if not _can_manage(request, page, project_id):
            return Response({"error": "Only admin or owner can delete the page"}, status=status.HTTP_403_FORBIDDEN)
        Page.objects.filter(parent_id=page_id, project_pages__project_id=project_id).update(parent=None)
        page.delete()
        UserFavorite.objects.filter(entity_type="page", entity_identifier=page_id, workspace__slug=slug).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectPageArchiveAPIEndpoint(BaseAPIView):
    """POST archives a page (and its sub-pages); DELETE restores it."""

    permission_classes = [ProjectPagePermission]
    model = Page

    def post(self, request, slug, project_id, page_id):
        page = project_pages(request, slug, project_id).get(pk=page_id)
        if not _can_manage(request, page, project_id):
            return Response(
                {"error": "Only the owner or admin can archive the page"}, status=status.HTTP_400_BAD_REQUEST
            )
        UserFavorite.objects.filter(entity_type="page", entity_identifier=page_id, workspace__slug=slug).delete()
        unarchive_archive_page_and_descendants(page_id, datetime.now())
        return Response(status=status.HTTP_204_NO_CONTENT)

    def delete(self, request, slug, project_id, page_id):
        page = project_pages(request, slug, project_id).get(pk=page_id)
        if not _can_manage(request, page, project_id):
            return Response(
                {"error": "Only the owner or admin can un archive the page"}, status=status.HTTP_400_BAD_REQUEST
            )
        if page.parent_id and page.parent.archived_at:
            page.parent = None
            page.save(update_fields=["parent"])
        unarchive_archive_page_and_descendants(page_id, None)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _work_item(slug, project_id, issue_id):
    return Issue.issue_objects.filter(workspace__slug=slug, project_id=project_id, pk=issue_id).first()


class WorkItemPageListCreateAPIEndpoint(BaseAPIView):
    """Pages linked to a work item (SDK: client.work_items.pages)."""

    permission_classes = [ProjectEntityPermission]
    model = Page

    def get(self, request, slug, project_id, issue_id):
        if not _work_item(slug, project_id, issue_id):
            return Response({"error": "Work item not found"}, status=status.HTTP_404_NOT_FOUND)
        return self.paginate(
            request=request,
            queryset=links_for(request.user, project_id, issue_id),
            on_results=lambda links: [link_payload(link) for link in links],
        )

    def post(self, request, slug, project_id, issue_id):
        issue = _work_item(slug, project_id, issue_id)
        if not issue:
            return Response({"error": "Work item not found"}, status=status.HTTP_404_NOT_FOUND)
        data = request.data if isinstance(request.data, dict) else {}
        try:
            link, created = create_link(request.user, issue, data.get("page_id"))
        except WorkItemPageError as exc:
            return Response({exc.field: exc.message, "error": exc.message}, status=exc.status_code)
        return Response(link_payload(link), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class WorkItemPageDetailAPIEndpoint(BaseAPIView):
    permission_classes = [ProjectEntityPermission]
    model = Page

    def get(self, request, slug, project_id, issue_id, work_item_page_id):
        link = links_for(request.user, project_id, issue_id).filter(pk=work_item_page_id).first()
        if not link:
            return Response({"error": "Page link not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(link_payload(link), status=status.HTTP_200_OK)

    def delete(self, request, slug, project_id, issue_id, work_item_page_id):
        link = links_for(request.user, project_id, issue_id).filter(pk=work_item_page_id).first()
        if not link:
            return Response({"error": "Page link not found"}, status=status.HTTP_404_NOT_FOUND)
        link.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
