# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.conf import settings
from django.db import models

# Module imports
from .project import ProjectBaseModel


class IssueWorkLog(ProjectBaseModel):
    """Time spent on a work item, in minutes."""

    issue = models.ForeignKey("db.Issue", on_delete=models.CASCADE, related_name="work_logs")
    logged_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="work_logs")
    duration = models.PositiveIntegerField()
    description = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Work Item Work Log"
        verbose_name_plural = "Work Item Work Logs"
        db_table = "issue_work_logs"
        ordering = ("-created_at",)
