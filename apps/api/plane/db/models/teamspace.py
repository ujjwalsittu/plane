# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Teams (teamspaces): groups of workspace members, optionally scoped to a set of projects."""

# Django imports
from django.conf import settings
from django.db import models
from django.db.models import Q

# Module imports
from .base import BaseModel


class Teamspace(BaseModel):
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="teamspaces")
    name = models.CharField(max_length=255)
    description_html = models.TextField(blank=True, default="<p></p>")
    description_json = models.JSONField(default=dict, blank=True)
    description_stripped = models.TextField(blank=True, default="")
    logo_props = models.JSONField(default=dict, blank=True)
    lead = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="led_teamspaces"
    )

    class Meta:
        verbose_name = "Teamspace"
        verbose_name_plural = "Teamspaces"
        db_table = "teamspaces"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "name"],
                condition=Q(deleted_at__isnull=True),
                name="teamspace_unique_name_when_deleted_at_null",
            )
        ]

    def __str__(self):
        return self.name


class TeamspaceMember(BaseModel):
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="teamspace_members")
    teamspace = models.ForeignKey("db.Teamspace", on_delete=models.CASCADE, related_name="member_links")
    member = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="teamspace_links")

    class Meta:
        verbose_name = "Teamspace Member"
        verbose_name_plural = "Teamspace Members"
        db_table = "teamspace_members"
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["teamspace", "member"],
                condition=Q(deleted_at__isnull=True),
                name="teamspace_member_unique_when_deleted_at_null",
            )
        ]


class TeamspaceProject(BaseModel):
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="teamspace_projects")
    teamspace = models.ForeignKey("db.Teamspace", on_delete=models.CASCADE, related_name="project_links")
    project = models.ForeignKey("db.Project", on_delete=models.CASCADE, related_name="teamspace_links")

    class Meta:
        verbose_name = "Teamspace Project"
        verbose_name_plural = "Teamspace Projects"
        db_table = "teamspace_projects"
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["teamspace", "project"],
                condition=Q(deleted_at__isnull=True),
                name="teamspace_project_unique_when_deleted_at_null",
            )
        ]
