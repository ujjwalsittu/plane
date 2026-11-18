# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Workspace pages (pages not attached to any project) and collections, shared by the external
API (SDK/MCP) and the app API (web)."""

# Python imports
from datetime import datetime

# Django imports
from django.db import transaction
from django.db.models import Exists, OuterRef, Q

# Module imports
from plane.app.permissions import ROLE
from plane.db.models import (
    Page,
    PageCollection,
    PageCollectionMember,
    PageCollectionPage,
    ProjectPage,
    WorkspaceMember,
)


class WorkspacePageError(ValueError):
    def __init__(self, message, status_code=400, field="error"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.field = field


def _iso(value):
    return value.isoformat() if value else None


def _is_admin(user, workspace_id):
    return WorkspaceMember.objects.filter(
        workspace_id=workspace_id, member=user, role=ROLE.ADMIN.value, is_active=True
    ).exists()


# --- collections ----------------------------------------------------------------------------------


def visible_collections(user, workspace_slug):
    member = PageCollectionMember.objects.filter(collection=OuterRef("pk"), member=user)
    return (
        PageCollection.objects.filter(workspace__slug=workspace_slug)
        .annotate(is_member=Exists(member))
        .filter(Q(access=PageCollection.PUBLIC) | Q(owned_by=user) | Q(is_member=True))
    )


def collection_access(user, collection):
    """2 edit, 1 comment, 0 view; owners and workspace admins can edit; public ones are editable
    by every workspace member unless a membership says otherwise."""
    if collection.owned_by_id == user.id or _is_admin(user, collection.workspace_id):
        return PageCollectionMember.EDIT
    membership = PageCollectionMember.objects.filter(collection=collection, member=user).first()
    if membership:
        return membership.access
    return PageCollectionMember.EDIT if collection.access == PageCollection.PUBLIC else PageCollectionMember.VIEW


def require_edit(user, collection):
    if collection_access(user, collection) < PageCollectionMember.EDIT:
        raise WorkspacePageError("You need edit access to this collection", status_code=403)


def collection_payload(collection, user):
    return {
        "id": str(collection.id),
        "name": collection.name,
        "owned_by_id": str(collection.owned_by_id),
        "access": collection.access,
        "current_user_access": collection_access(user, collection),
        "has_pages": collection.page_links.exists(),
        "is_default": False,
        "is_global": False,
        "logo_props": collection.logo_props,
        "sort_order": collection.sort_order,
        "workspace": str(collection.workspace_id),
        "created_at": _iso(collection.created_at),
        "updated_at": _iso(collection.updated_at),
        "created_by": str(collection.created_by_id) if collection.created_by_id else None,
        "updated_by": str(collection.updated_by_id) if collection.updated_by_id else None,
    }


def create_collection(user, workspace, data):
    name = str(data.get("name") or "").strip()
    if not name:
        raise WorkspacePageError("name is required", field="name")
    access = data.get("access", PageCollection.PUBLIC)
    if access not in (PageCollection.PUBLIC, PageCollection.PRIVATE):
        raise WorkspacePageError("access is 0 (public) or 1 (private)", field="access")
    return PageCollection.objects.create(
        workspace=workspace,
        name=name[:255],
        owned_by=user,
        access=access,
        logo_props=data.get("logo_props") if isinstance(data.get("logo_props"), dict) else {},
    )


def update_collection(user, collection, data):
    require_edit(user, collection)
    if "access" in data and data["access"] is not None and data["access"] != collection.access:
        raise WorkspacePageError("A collection's access is fixed when it is created", field="access")
    if "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            raise WorkspacePageError("name can't be empty", field="name")
        collection.name = name[:255]
    if isinstance(data.get("logo_props"), dict):
        collection.logo_props = data["logo_props"]
    if data.get("sort_order") is not None:
        collection.sort_order = float(data["sort_order"])
    collection.save()
    return collection


@transaction.atomic
def delete_collection(user, collection, archive_pages=True):
    """Pages of a private collection are always archived; otherwise per archive_pages."""
    if collection.owned_by_id != user.id and not _is_admin(user, collection.workspace_id):
        raise WorkspacePageError("Only the collection's owner or a workspace admin can delete it", 403)
    page_ids = list(collection.page_links.values_list("page_id", flat=True))
    if archive_pages or collection.access == PageCollection.PRIVATE:
        Page.objects.filter(pk__in=page_ids, archived_at__isnull=True).update(archived_at=datetime.now())
    # Soft deletion doesn't cascade right away; unfile the pages and drop memberships now.
    collection.page_links.all().delete()
    collection.members.all().delete()
    collection.delete()


# --- workspace pages ------------------------------------------------------------------------------


def workspace_pages(user, workspace_slug):
    """Pages of the workspace not attached to a project, that ``user`` may see."""
    in_project = ProjectPage.objects.filter(page=OuterRef("pk"), deleted_at__isnull=True)
    hidden_collections = PageCollection.objects.filter(workspace__slug=workspace_slug).exclude(
        pk__in=visible_collections(user, workspace_slug).values("id")
    )
    return (
        Page.objects.filter(workspace__slug=workspace_slug)
        .annotate(in_project=Exists(in_project))
        .filter(in_project=False)
        .filter(Q(owned_by=user) | Q(access=Page.PUBLIC_ACCESS))
        .exclude(collection_links__collection__in=hidden_collections)
        .distinct()
    )


def page_membership(page):
    return PageCollectionPage.objects.filter(page=page).first()


def workspace_page_payload(page):
    membership = page_membership(page)
    return {
        "id": str(page.id),
        "name": page.name,
        "description_html": page.description_html,
        "description_stripped": page.description_stripped,
        "owned_by": str(page.owned_by_id),
        "workspace": str(page.workspace_id),
        "projects": [],
        "access": page.access,
        "color": page.color,
        "is_locked": page.is_locked,
        "archived_at": _iso(page.archived_at),
        "parent_id": str(page.parent_id) if page.parent_id else None,
        "logo_props": page.logo_props,
        "external_id": page.external_id,
        "external_source": page.external_source,
        "created_at": _iso(page.created_at),
        "updated_at": _iso(page.updated_at),
        "collection_id": str(membership.collection_id) if membership else None,
        "page_collection_id": str(membership.id) if membership else None,
    }


def file_page(page, collection, sort_order=None):
    """Put a page in a collection (moving it if it is in another one); returns the membership."""
    membership = page_membership(page)
    if membership:
        if membership.collection_id != collection.id:
            membership.collection = collection
            membership.save(update_fields=["collection", "updated_at"])
        return membership
    if sort_order is None:
        last = collection.page_links.order_by("-sort_order").first()
        sort_order = (last.sort_order + 1000) if last else 1000
    return PageCollectionPage.objects.create(
        workspace_id=page.workspace_id, collection=collection, page=page, sort_order=sort_order
    )


def membership_payload(membership):
    return {
        "id": str(membership.id),
        "collection": str(membership.collection_id),
        "page": str(membership.page_id),
        "workspace": str(membership.workspace_id),
        "sort_order": membership.sort_order,
        "created_at": _iso(membership.created_at),
        "updated_at": _iso(membership.updated_at),
        "created_by": str(membership.created_by_id) if membership.created_by_id else None,
        "updated_by": str(membership.updated_by_id) if membership.updated_by_id else None,
    }


def branch_payload(membership):
    """A collection's page as the SDK's CollectionBranchPage."""
    return {
        "page_collection_id": str(membership.id),
        "collection_id": str(membership.collection_id),
        "parent_id": str(membership.page.parent_id) if membership.page.parent_id else None,
        "sort_order": membership.sort_order,
        "page": workspace_page_payload(membership.page),
    }


def member_payload(member):
    return {
        "id": str(member.id),
        "collection": str(member.collection_id),
        "member": str(member.member_id),
        "access": member.access,
        "workspace": str(member.workspace_id),
        "created_at": _iso(member.created_at),
        "updated_at": _iso(member.updated_at),
        "created_by": str(member.created_by_id) if member.created_by_id else None,
        "updated_by": str(member.updated_by_id) if member.updated_by_id else None,
    }


def add_member(user, collection, data):
    require_edit(user, collection)
    member_id = data.get("member")
    access = data.get("access")
    if access not in (PageCollectionMember.VIEW, PageCollectionMember.COMMENT, PageCollectionMember.EDIT):
        raise WorkspacePageError("access is 0 (view), 1 (comment) or 2 (edit)", field="access")
    if not WorkspaceMember.objects.filter(
        workspace_id=collection.workspace_id, member_id=member_id, is_active=True
    ).exists():
        raise WorkspacePageError("That user is not a member of this workspace", field="member")
    member, _ = PageCollectionMember.objects.update_or_create(
        workspace_id=collection.workspace_id, collection=collection, member_id=member_id, defaults={"access": access}
    )
    return member
