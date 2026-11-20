# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Templates: the reusable shape of a work item, a page or a project."""

# Django imports
from django.db import models

# Module imports
from .base import BaseModel


class Template(BaseModel):
    WORK_ITEM = "workitem"
    PAGE = "page"
    PROJECT = "project"
    KINDS = (WORK_ITEM, PAGE, PROJECT)

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="templates")
    # Null for a workspace template; set for one that belongs to a single project.
    project = models.ForeignKey("db.Project", on_delete=models.CASCADE, null=True, blank=True, related_name="templates")
    kind = models.CharField(max_length=16, choices=[(k, k.title()) for k in KINDS])
    name = models.CharField(max_length=255)
    # The template's own summary, not the templated body.
    description_html = models.TextField(blank=True, default="<p></p>")
    description_stripped = models.TextField(blank=True, default="")
    logo_props = models.JSONField(default=dict, blank=True)
    # What gets templated: the fields a work item, page or project created from it starts with.
    template_data = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Template"
        verbose_name_plural = "Templates"
        db_table = "templates"
        ordering = ("name", "-created_at")
        indexes = [models.Index(fields=["workspace", "kind"], name="template_workspace_kind_idx")]

    def __str__(self):
        return f"{self.kind}: {self.name}"
