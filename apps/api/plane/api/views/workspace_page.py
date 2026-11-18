# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Workspace pages and collections for the SDK/MCP (and, via session subclasses, the web app)."""

# Python imports
from datetime import datetime

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.api.views.base import BaseAPIView
from plane.api.views.page import _clean_html
from plane.app.permissions import WorkspaceEntityPermission
from plane.app.views.page.base import unarchive_archive_page_and_descendants
from plane.bgtasks.page_transaction_task import page_transaction
from plane.db.models import Page, PageCollection, PageCollectionMember, PageCollectionPage, UserFavorite, Workspace
from plane.utils.workspace_pages import (
    WorkspacePageError,
    _is_admin,
    add_member,
    branch_payload,
    collection_payload,
    create_collection,
    delete_collection,
    file_page,
    member_payload,
    membership_payload,
    page_membership,
    require_edit,
    update_collection,
    visible_collections,
    workspace_page_payload,
    workspace_pages,
)

_PAGE_FIELDS = ("name", "access", "color", "logo_props", "is_locked", "external_id", "external_source")


def _data(request):
    return request.data if isinstance(request.data, dict) else {}


def _error(exc):
    return Response({exc.field: exc.message, "error": exc.message}, status=exc.status_code)


def _not_found(what):
    return Response({"error": f"{what} not found"}, status=status.HTTP_404_NOT_FOUND)


def _can_manage_page(user, page):
    return page.owned_by_id == user.id or _is_admin(user, page.workspace_id)


class _Base(BaseAPIView):
    permission_classes = [WorkspaceEntityPermission]
    model = Page

    def handle_exception(self, exc):
        if isinstance(exc, WorkspacePageError):
            return _error(exc)
        return super().handle_exception(exc)


# --- workspace pages ------------------------------------------------------------------------------


class WorkspacePageListCreateAPIEndpoint(_Base):
    def get(self, request, slug):
        archived = request.GET.get("archived", "false").lower() == "true"
        queryset = workspace_pages(request.user, slug).filter(archived_at__isnull=not archived)
        if request.GET.get("collection_id"):
            queryset = queryset.filter(collection_links__collection_id=request.GET["collection_id"])
        external_id, external_source = request.GET.get("external_id"), request.GET.get("external_source")
        if external_id and external_source:
            queryset = queryset.filter(external_id=external_id, external_source=external_source)
        return self.paginate(
            request=request,
            queryset=queryset.order_by("sort_order", "created_at"),
            on_results=lambda pages: [workspace_page_payload(page) for page in pages],
        )

    def post(self, request, slug):
        data = _data(request)
        name = str(data.get("name") or "").strip()
        if not name:
            return Response({"name": "name is required"}, status=status.HTTP_400_BAD_REQUEST)
        html, error = _clean_html(data)
        if error:
            return error
        workspace = Workspace.objects.get(slug=slug)

        parent = None
        if data.get("parent_id") or data.get("parent"):
            parent = workspace_pages(request.user, slug).filter(pk=data.get("parent_id") or data.get("parent")).first()
            if parent is None:
                return _not_found("Parent page")
        collection = None
        if data.get("collection_id"):
            if parent is not None:
                return Response(
                    {"error": "Pass parent_id or collection_id, not both; a sub-page takes its parent's collection"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            collection = visible_collections(request.user, slug).filter(pk=data["collection_id"]).first()
            if collection is None:
                return _not_found("Collection")
            require_edit(request.user, collection)
        elif parent is not None:
            membership = page_membership(parent)
            collection = membership.collection if membership else None

        access = data.get("access", Page.PUBLIC_ACCESS)
        if access not in (Page.PUBLIC_ACCESS, Page.PRIVATE_ACCESS):
            return Response({"access": "access is 0 (public) or 1 (private)"}, status=status.HTTP_400_BAD_REQUEST)
        page = Page.objects.create(
            workspace=workspace,
            owned_by=request.user,
            name=name[:255],
            description_html=html or "<p></p>",
            access=access,
            parent=parent,
            **{
                key: data[key]
                for key in ("color", "logo_props", "is_locked", "external_id", "external_source")
                if key in data
            },
        )
        if collection is not None:
            file_page(page, collection)
        page_transaction.delay(new_description_html=page.description_html, old_description_html=None, page_id=page.id)
        return Response(workspace_page_payload(page), status=status.HTTP_201_CREATED)


class WorkspacePageDetailAPIEndpoint(_Base):
    def _page(self, request, slug, page_id):
        return workspace_pages(request.user, slug).filter(pk=page_id).first()

    def _check_collection_edit(self, request, page):
        membership = page_membership(page)
        if membership:
            require_edit(request.user, membership.collection)

    def get(self, request, slug, page_id):
        page = self._page(request, slug, page_id)
        return Response(workspace_page_payload(page)) if page else _not_found("Page")

    def put(self, request, slug, page_id):
        page = self._page(request, slug, page_id)
        if page is None:
            return _not_found("Page")
        self._check_collection_edit(request, page)
        data = _data(request)
        if page.is_locked and data.get("is_locked") is not False:
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
        for key in _PAGE_FIELDS:
            if key in data and data[key] is not None:
                value = str(data[key]).strip() if key == "name" else data[key]
                if key == "name" and not value:
                    return Response({"name": "Name cannot be empty"}, status=status.HTTP_400_BAD_REQUEST)
                setattr(page, key, value)
                fields.append(key)
        old_html = page.description_html
        if html is not None and html != old_html:
            page.description_html = html
            page.description_binary = None
            page.description_json = {}
            fields += ["description_html", "description_binary", "description_json", "description_stripped"]
        if fields:
            page.save(update_fields=sorted(set(fields + ["updated_at", "updated_by"])))
        if html is not None and html != old_html:
            page_transaction.delay(new_description_html=html, old_description_html=old_html, page_id=page.id)
        return Response(workspace_page_payload(page), status=status.HTTP_200_OK)

    patch = put

    def delete(self, request, slug, page_id):
        page = self._page(request, slug, page_id)
        if page is None:
            return _not_found("Page")
        if page.archived_at is None:
            return Response({"error": "The page should be archived before deleting"}, status=400)
        if not _can_manage_page(request.user, page):
            return Response({"error": "Only admin or owner can delete the page"}, status=status.HTTP_403_FORBIDDEN)
        Page.objects.filter(parent_id=page.id).update(parent=None)
        page.delete()
        UserFavorite.objects.filter(entity_type="page", entity_identifier=page_id, workspace__slug=slug).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkspacePageArchiveAPIEndpoint(_Base):
    def post(self, request, slug, page_id):
        page = workspace_pages(request.user, slug).filter(pk=page_id).first()
        if page is None:
            return _not_found("Page")
        if not _can_manage_page(request.user, page):
            return Response({"error": "Only the owner or admin can archive the page"}, status=400)
        unarchive_archive_page_and_descendants(page_id, datetime.now())
        return Response(status=status.HTTP_204_NO_CONTENT)

    def delete(self, request, slug, page_id):
        page = workspace_pages(request.user, slug).filter(pk=page_id).first()
        if page is None:
            return _not_found("Page")
        if not _can_manage_page(request.user, page):
            return Response({"error": "Only the owner or admin can restore the page"}, status=400)
        unarchive_archive_page_and_descendants(page_id, None)
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- collections ----------------------------------------------------------------------------------


class CollectionListCreateAPIEndpoint(_Base):
    model = PageCollection

    def get(self, request, slug):
        collections = visible_collections(request.user, slug)
        return Response([collection_payload(c, request.user) for c in collections])

    def post(self, request, slug):
        collection = create_collection(request.user, Workspace.objects.get(slug=slug), _data(request))
        return Response(collection_payload(collection, request.user), status=status.HTTP_201_CREATED)


class _CollectionMixin:
    def _collection(self, request, slug, collection_id):
        return visible_collections(request.user, slug).filter(pk=collection_id).first()


class CollectionDetailAPIEndpoint(_CollectionMixin, _Base):
    model = PageCollection

    def get(self, request, slug, collection_id):
        collection = self._collection(request, slug, collection_id)
        return Response(collection_payload(collection, request.user)) if collection else _not_found("Collection")

    def patch(self, request, slug, collection_id):
        collection = self._collection(request, slug, collection_id)
        if collection is None:
            return _not_found("Collection")
        return Response(collection_payload(update_collection(request.user, collection, _data(request)), request.user))

    def delete(self, request, slug, collection_id):
        collection = self._collection(request, slug, collection_id)
        if collection is None:
            return _not_found("Collection")
        archive = request.GET.get("archive_pages", "true").lower() != "false"
        delete_collection(request.user, collection, archive_pages=archive)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CollectionPageListAddAPIEndpoint(_CollectionMixin, _Base):
    model = PageCollectionPage

    def get(self, request, slug, collection_id):
        collection = self._collection(request, slug, collection_id)
        if collection is None:
            return _not_found("Collection")
        visible = workspace_pages(request.user, slug).values("id")
        memberships = collection.page_links.filter(page_id__in=visible, page__archived_at__isnull=True).select_related(
            "page"
        )
        parent_id = request.GET.get("parent_id")
        memberships = memberships.filter(page__parent_id=parent_id) if parent_id else memberships
        if request.GET.get("search"):
            memberships = memberships.filter(page__name__icontains=request.GET["search"])
        return self.paginate(
            request=request,
            queryset=memberships.order_by("sort_order", "created_at"),
            on_results=lambda rows: [branch_payload(row) for row in rows],
        )

    def post(self, request, slug, collection_id):
        collection = self._collection(request, slug, collection_id)
        if collection is None:
            return _not_found("Collection")
        require_edit(request.user, collection)
        data = _data(request)
        page_ids = [str(pid) for pid in data.get("page_ids") or []]
        if not page_ids:
            return Response({"page_ids": "page_ids is required"}, status=status.HTTP_400_BAD_REQUEST)
        pages = {str(p.id): p for p in workspace_pages(request.user, slug).filter(pk__in=page_ids)}
        missing = [pid for pid in page_ids if pid not in pages]
        if missing:
            return Response(
                {"error": f"Workspace pages not found: {', '.join(missing)}"}, status=status.HTTP_404_NOT_FOUND
            )
        orders = data.get("sort_orders") if isinstance(data.get("sort_orders"), dict) else {}
        memberships = [file_page(pages[pid], collection, sort_order=orders.get(pid)) for pid in page_ids]
        return Response([membership_payload(m) for m in memberships], status=status.HTTP_201_CREATED)


class CollectionPageSearchAPIEndpoint(_CollectionMixin, _Base):
    """Workspace pages that could be filed in the collection, matched by name."""

    def get(self, request, slug, collection_id):
        collection = self._collection(request, slug, collection_id)
        if collection is None:
            return _not_found("Collection")
        pages = workspace_pages(request.user, slug).filter(archived_at__isnull=True)
        if request.GET.get("search"):
            pages = pages.filter(name__icontains=request.GET["search"])
        return Response(
            [
                {
                    "id": str(page.id),
                    "name": page.name,
                    "collection_id": str(m.collection_id) if (m := page_membership(page)) else None,
                    "logo_props": page.logo_props,
                }
                for page in pages.order_by("name")[:50]
            ]
        )


class CollectionPageDetailAPIEndpoint(_CollectionMixin, _Base):
    model = PageCollectionPage

    def _membership(self, request, slug, collection_id, page_collection_id):
        collection = self._collection(request, slug, collection_id)
        if collection is None:
            return None, None
        return collection, collection.page_links.filter(pk=page_collection_id).select_related("page").first()

    def patch(self, request, slug, collection_id, page_collection_id):
        collection, membership = self._membership(request, slug, collection_id, page_collection_id)
        if membership is None:
            return _not_found("Collection page")
        require_edit(request.user, collection)
        data = _data(request)
        if data.get("collection"):
            target = visible_collections(request.user, slug).filter(pk=data["collection"]).first()
            if target is None:
                return _not_found("Target collection")
            require_edit(request.user, target)
            membership.collection = target
        if data.get("sort_order") is not None:
            membership.sort_order = float(data["sort_order"])
        membership.save()
        return Response(membership_payload(membership))

    def delete(self, request, slug, collection_id, page_collection_id):
        collection, membership = self._membership(request, slug, collection_id, page_collection_id)
        if membership is None:
            return _not_found("Collection page")
        require_edit(request.user, collection)
        membership.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CollectionMemberListAddAPIEndpoint(_CollectionMixin, _Base):
    model = PageCollectionMember

    def get(self, request, slug, collection_id):
        collection = self._collection(request, slug, collection_id)
        if collection is None:
            return _not_found("Collection")
        return Response([member_payload(m) for m in collection.members.all()])

    def post(self, request, slug, collection_id):
        collection = self._collection(request, slug, collection_id)
        if collection is None:
            return _not_found("Collection")
        member = add_member(request.user, collection, _data(request))
        return Response(member_payload(member), status=status.HTTP_201_CREATED)


class CollectionMemberDetailAPIEndpoint(_CollectionMixin, _Base):
    model = PageCollectionMember

    def _member(self, request, slug, collection_id, member_id):
        collection = self._collection(request, slug, collection_id)
        if collection is None:
            return None, None
        return collection, collection.members.filter(pk=member_id).first()

    def patch(self, request, slug, collection_id, member_id):
        collection, member = self._member(request, slug, collection_id, member_id)
        if member is None:
            return _not_found("Collection member")
        access = _data(request).get("access")
        if access not in (PageCollectionMember.VIEW, PageCollectionMember.COMMENT, PageCollectionMember.EDIT):
            return Response({"access": "access is 0 (view), 1 (comment) or 2 (edit)"}, status=400)
        require_edit(request.user, collection)
        member.access = access
        member.save(update_fields=["access", "updated_at"])
        return Response(member_payload(member))

    def delete(self, request, slug, collection_id, member_id):
        collection, member = self._member(request, slug, collection_id, member_id)
        if member is None:
            return _not_found("Collection member")
        require_edit(request.user, collection)
        member.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
