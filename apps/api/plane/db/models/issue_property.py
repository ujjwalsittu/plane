# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Custom work item properties: definitions, select options, per-work-item values, and which
work item types a property applies to.

A property belongs to a workspace and optionally a project (project-level). It applies to work
items of the types it is linked to through IssueTypeProperty; a property created on a type is
linked to it at creation.
"""

# Django imports
from django.db import models
from django.db.models import Q

# Module imports
from .base import BaseModel

PROPERTY_TYPES = ("TEXT", "DATETIME", "DECIMAL", "BOOLEAN", "OPTION", "RELATION", "URL", "EMAIL", "FILE")
RELATION_TYPES = ("ISSUE", "USER")


class IssueProperty(BaseModel):
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="issue_properties")
    project = models.ForeignKey(
        "db.Project", on_delete=models.CASCADE, related_name="issue_properties", null=True, blank=True
    )
    name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    logo_props = models.JSONField(default=dict, blank=True)
    sort_order = models.FloatField(default=65535)
    property_type = models.CharField(max_length=30)
    relation_type = models.CharField(max_length=30, null=True, blank=True)
    is_required = models.BooleanField(default=False)
    is_multi = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    default_value = models.JSONField(default=list, blank=True)
    settings = models.JSONField(default=dict, blank=True)
    validation_rules = models.JSONField(default=dict, blank=True)
    external_source = models.CharField(max_length=255, null=True, blank=True)
    external_id = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        verbose_name = "Work Item Property"
        verbose_name_plural = "Work Item Properties"
        db_table = "issue_properties"
        ordering = ("sort_order", "created_at")

    def __str__(self):
        return self.display_name


class IssuePropertyOption(BaseModel):
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="issue_property_options")
    property = models.ForeignKey(IssueProperty, on_delete=models.CASCADE, related_name="options")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    logo_props = models.JSONField(default=dict, blank=True)
    sort_order = models.FloatField(default=65535)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="children")
    external_source = models.CharField(max_length=255, null=True, blank=True)
    external_id = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        verbose_name = "Work Item Property Option"
        verbose_name_plural = "Work Item Property Options"
        db_table = "issue_property_options"
        ordering = ("sort_order", "created_at")

    def __str__(self):
        return self.name


class IssuePropertyValue(BaseModel):
    """One value of a property on a work item; multi-value properties have one row per value."""

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="issue_property_values")
    project = models.ForeignKey("db.Project", on_delete=models.CASCADE, related_name="issue_property_values")
    issue = models.ForeignKey("db.Issue", on_delete=models.CASCADE, related_name="property_values")
    property = models.ForeignKey(IssueProperty, on_delete=models.CASCADE, related_name="values")
    value_text = models.TextField(null=True, blank=True)
    value_boolean = models.BooleanField(null=True, blank=True)
    value_decimal = models.FloatField(null=True, blank=True)
    value_datetime = models.DateTimeField(null=True, blank=True)
    value_uuid = models.UUIDField(null=True, blank=True)
    value_option = models.ForeignKey(
        IssuePropertyOption, on_delete=models.CASCADE, null=True, blank=True, related_name="values"
    )
    external_source = models.CharField(max_length=255, null=True, blank=True)
    external_id = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        verbose_name = "Work Item Property Value"
        verbose_name_plural = "Work Item Property Values"
        db_table = "issue_property_values"
        ordering = ("created_at",)


class IssueTypeProperty(BaseModel):
    """Links a property to a work item type (optionally only within one project)."""

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="issue_type_properties")
    issue_type = models.ForeignKey("db.IssueType", on_delete=models.CASCADE, related_name="property_links")
    property = models.ForeignKey(IssueProperty, on_delete=models.CASCADE, related_name="type_links")

    class Meta:
        verbose_name = "Work Item Type Property"
        verbose_name_plural = "Work Item Type Properties"
        db_table = "issue_type_properties"
        constraints = [
            models.UniqueConstraint(
                fields=["issue_type", "property"],
                condition=Q(deleted_at__isnull=True),
                name="issue_type_property_unique_when_deleted_at_null",
            )
        ]
