# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Workspace-defined relation types between work items (beyond the built-in ones).

A definition has an outward label (shown on ``issue``) and an inward label (shown on
``related_issue``), e.g. "implements" / "implemented by".
"""

# Django imports
from django.db import models
from django.db.models import Q

# Module imports
from .base import BaseModel


class IssueRelationDefinition(BaseModel):
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="relation_definitions")
    name = models.CharField(max_length=255)
    outward = models.CharField(max_length=255)
    inward = models.CharField(max_length=255)
    color = models.CharField(max_length=32, blank=True, default="")
    sort_order = models.FloatField(default=65535)
    is_active = models.BooleanField(default=True)
    external_source = models.CharField(max_length=255, null=True, blank=True)
    external_id = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        verbose_name = "Work Item Relation Definition"
        verbose_name_plural = "Work Item Relation Definitions"
        db_table = "issue_relation_definitions"
        ordering = ("sort_order", "created_at")

    def __str__(self):
        return self.name


class IssueCustomRelation(BaseModel):
    """``issue`` <outward> ``related_issue``; seen from ``related_issue`` it reads <inward>."""

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="custom_relations")
    definition = models.ForeignKey(IssueRelationDefinition, on_delete=models.CASCADE, related_name="relations")
    issue = models.ForeignKey("db.Issue", on_delete=models.CASCADE, related_name="custom_relations_out")
    related_issue = models.ForeignKey("db.Issue", on_delete=models.CASCADE, related_name="custom_relations_in")

    class Meta:
        verbose_name = "Work Item Custom Relation"
        verbose_name_plural = "Work Item Custom Relations"
        db_table = "issue_custom_relations"
        constraints = [
            models.UniqueConstraint(
                fields=["definition", "issue", "related_issue"],
                condition=Q(deleted_at__isnull=True),
                name="issue_custom_relation_unique_when_deleted_at_null",
            )
        ]
