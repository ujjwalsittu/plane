# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Initiatives: workspace-level goals that group projects and work items (e.g. epics) and roll up
their progress."""

# Django imports
from django.conf import settings
from django.db import models
from django.db.models import Q

# Module imports
from .base import BaseModel


class Initiative(BaseModel):
    DRAFT = "DRAFT"
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    STATES = (DRAFT, PLANNED, ACTIVE, COMPLETED, CLOSED)

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="initiatives")
    name = models.CharField(max_length=255)
    description_html = models.TextField(blank=True, default="<p></p>")
    description_stripped = models.TextField(blank=True, default="")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    logo_props = models.JSONField(default=dict)
    state = models.CharField(max_length=16, choices=[(s, s.title()) for s in STATES], default=DRAFT)
    lead = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="led_initiatives"
    )
    sort_order = models.FloatField(default=65535)

    class Meta:
        verbose_name = "Initiative"
        verbose_name_plural = "Initiatives"
        db_table = "initiatives"
        ordering = ("sort_order", "-created_at")


class InitiativeProject(BaseModel):
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="+")
    initiative = models.ForeignKey("db.Initiative", on_delete=models.CASCADE, related_name="project_links")
    project = models.ForeignKey("db.Project", on_delete=models.CASCADE, related_name="initiative_links")

    class Meta:
        verbose_name = "Initiative Project"
        verbose_name_plural = "Initiative Projects"
        db_table = "initiative_projects"
        constraints = [
            models.UniqueConstraint(
                fields=["initiative", "project"],
                condition=Q(deleted_at__isnull=True),
                name="initiative_project_unique_when_deleted_at_null",
            )
        ]


class InitiativeWorkItem(BaseModel):
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="+")
    initiative = models.ForeignKey("db.Initiative", on_delete=models.CASCADE, related_name="work_item_links")
    issue = models.ForeignKey("db.Issue", on_delete=models.CASCADE, related_name="initiative_links")

    class Meta:
        verbose_name = "Initiative Work Item"
        verbose_name_plural = "Initiative Work Items"
        db_table = "initiative_work_items"
        constraints = [
            models.UniqueConstraint(
                fields=["initiative", "issue"],
                condition=Q(deleted_at__isnull=True),
                name="initiative_work_item_unique_when_deleted_at_null",
            )
        ]
