# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Supervision: who or what a work item is waiting on."""

# Django imports
from django.conf import settings
from django.db import models
from django.db.models import Q

# Module imports
from .project import ProjectBaseModel


class WorkItemWaiting(ProjectBaseModel):
    """A work item waiting on a person or something outside the workspace. At most one row per work
    item is open (``resolved_at`` null)."""

    issue = models.ForeignKey("db.Issue", on_delete=models.CASCADE, related_name="waiting_on_rows")
    waiting_on_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    waiting_on_text = models.CharField(max_length=255, blank=True, default="")
    note = models.TextField(blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Work Item Waiting"
        verbose_name_plural = "Work Item Waiting"
        db_table = "work_item_waiting"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["issue"],
                condition=Q(resolved_at__isnull=True, deleted_at__isnull=True),
                name="work_item_waiting_one_open_per_issue",
            )
        ]
