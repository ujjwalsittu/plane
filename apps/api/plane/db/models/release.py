# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Releases: workspace-level sets of work items shipped together, with a version tag, labels and a
changelog."""

# Django imports
from django.conf import settings
from django.db import models
from django.db.models import Q

# Module imports
from .base import BaseModel


class ReleaseTag(BaseModel):
    """A version marker (e.g. v1.2.0), optionally tied to a git tag or commit."""

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="release_tags")
    version = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    commit_hash = models.CharField(max_length=64, blank=True, default="")
    git_tag = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = "Release Tag"
        verbose_name_plural = "Release Tags"
        db_table = "release_tags"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "version"],
                condition=Q(deleted_at__isnull=True),
                name="release_tag_unique_version_when_deleted_at_null",
            )
        ]


class ReleaseLabel(BaseModel):
    """A label in the workspace's release palette."""

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="release_labels")
    name = models.CharField(max_length=255)
    color = models.CharField(max_length=32, blank=True, default="")
    sort_order = models.FloatField(default=65535)

    class Meta:
        verbose_name = "Release Label"
        verbose_name_plural = "Release Labels"
        db_table = "release_labels"
        ordering = ("sort_order", "name")


class Release(BaseModel):
    UNRELEASED = "unreleased"
    RELEASED = "released"
    CANCELLED = "cancelled"
    STATUSES = (UNRELEASED, RELEASED, CANCELLED)

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="releases")
    name = models.CharField(max_length=255)
    description_html = models.TextField(blank=True, default="<p></p>")
    description_json = models.JSONField(default=dict, blank=True)
    description_stripped = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=[(s, s.title()) for s in STATUSES], default=UNRELEASED)
    # The date the release ships (shown as "Target date" in Plane's UI); target_date is kept separately.
    release_date = models.DateField(null=True, blank=True)
    target_date = models.DateField(null=True, blank=True)
    lead = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="led_releases"
    )
    tag = models.ForeignKey("db.ReleaseTag", on_delete=models.SET_NULL, null=True, blank=True, related_name="releases")
    is_prerelease = models.BooleanField(default=False)
    external_source = models.CharField(max_length=255, null=True, blank=True)
    external_id = models.CharField(max_length=255, null=True, blank=True)
    # Release notes, edited separately from the description.
    changelog_html = models.TextField(blank=True, default="<p></p>")
    changelog_json = models.JSONField(default=dict, blank=True)
    changelog_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Release"
        verbose_name_plural = "Releases"
        db_table = "releases"
        ordering = ("-created_at",)


class ReleaseLabelLink(BaseModel):
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="+")
    release = models.ForeignKey("db.Release", on_delete=models.CASCADE, related_name="label_links")
    label = models.ForeignKey("db.ReleaseLabel", on_delete=models.CASCADE, related_name="release_links")

    class Meta:
        db_table = "release_label_links"
        constraints = [
            models.UniqueConstraint(
                fields=["release", "label"],
                condition=Q(deleted_at__isnull=True),
                name="release_label_link_unique_when_deleted_at_null",
            )
        ]


class ReleaseWorkItem(BaseModel):
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="+")
    release = models.ForeignKey("db.Release", on_delete=models.CASCADE, related_name="work_item_links")
    issue = models.ForeignKey("db.Issue", on_delete=models.CASCADE, related_name="release_links")

    class Meta:
        db_table = "release_work_items"
        constraints = [
            models.UniqueConstraint(
                fields=["release", "issue"],
                condition=Q(deleted_at__isnull=True),
                name="release_work_item_unique_when_deleted_at_null",
            )
        ]
