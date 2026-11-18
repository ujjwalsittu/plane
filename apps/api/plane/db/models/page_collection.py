# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Collections: workspace-level folders for workspace pages (pages not tied to a project).

A public collection is visible to everyone in the workspace; a private one to its owner and
its members. A page is filed in at most one collection.
"""

# Django imports
from django.conf import settings
from django.db import models
from django.db.models import Q

# Module imports
from .base import BaseModel


class PageCollection(BaseModel):
    PUBLIC = 0
    PRIVATE = 1

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="page_collections")
    name = models.CharField(max_length=255)
    owned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="page_collections")
    access = models.PositiveSmallIntegerField(default=PUBLIC)
    logo_props = models.JSONField(default=dict, blank=True)
    sort_order = models.FloatField(default=65535)

    class Meta:
        verbose_name = "Page Collection"
        verbose_name_plural = "Page Collections"
        db_table = "page_collections"
        ordering = ("sort_order", "created_at")

    def __str__(self):
        return self.name


class PageCollectionPage(BaseModel):
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="page_collection_pages")
    collection = models.ForeignKey(PageCollection, on_delete=models.CASCADE, related_name="page_links")
    page = models.ForeignKey("db.Page", on_delete=models.CASCADE, related_name="collection_links")
    sort_order = models.FloatField(default=65535)

    class Meta:
        verbose_name = "Page Collection Page"
        verbose_name_plural = "Page Collection Pages"
        db_table = "page_collection_pages"
        ordering = ("sort_order", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=["page"],
                condition=Q(deleted_at__isnull=True),
                name="page_collection_page_one_collection_per_page",
            )
        ]


class PageCollectionMember(BaseModel):
    VIEW = 0
    COMMENT = 1
    EDIT = 2

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="page_collection_members")
    collection = models.ForeignKey(PageCollection, on_delete=models.CASCADE, related_name="members")
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="page_collection_memberships"
    )
    access = models.PositiveSmallIntegerField(default=VIEW)

    class Meta:
        verbose_name = "Page Collection Member"
        verbose_name_plural = "Page Collection Members"
        db_table = "page_collection_members"
        constraints = [
            models.UniqueConstraint(
                fields=["collection", "member"],
                condition=Q(deleted_at__isnull=True),
                name="page_collection_member_unique_when_deleted_at_null",
            )
        ]
