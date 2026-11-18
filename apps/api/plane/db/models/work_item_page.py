# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db import models
from django.db.models import Q

# Module imports
from .project import ProjectBaseModel


class IssuePage(ProjectBaseModel):
    """A project page linked to a work item (shown on the work item; read by the SDK/MCP)."""

    issue = models.ForeignKey("db.Issue", on_delete=models.CASCADE, related_name="issue_pages")
    page = models.ForeignKey("db.Page", on_delete=models.CASCADE, related_name="issue_links")

    class Meta:
        verbose_name = "Work Item Page"
        verbose_name_plural = "Work Item Pages"
        db_table = "issue_pages"
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["issue", "page"],
                condition=Q(deleted_at__isnull=True),
                name="issue_page_unique_issue_page_when_deleted_at_null",
            )
        ]

    def __str__(self):
        return f"{self.issue_id} -> {self.page_id}"
