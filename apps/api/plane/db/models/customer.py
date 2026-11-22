# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Customers: the companies a workspace serves, their custom properties, the requests they raise and the
work items those link to. Shapes follow the official Plane SDK (plane.models.customers)."""

# Django imports
from django.db import models
from django.db.models import Q

# Module imports
from .base import BaseModel


class Customer(BaseModel):
    # The stages and contract statuses the SDK's MCP tools render; both are stored free-form.
    STAGES = ("lead", "sales_qualified_lead", "contract_negotiation", "closed_won", "closed_lost")
    CONTRACT_STATUSES = ("active", "pre_contract", "signed", "inactive")

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="customers")
    name = models.CharField(max_length=255)
    description = models.JSONField(default=dict, blank=True)
    description_html = models.TextField(blank=True, default="<p></p>")
    description_stripped = models.TextField(blank=True, default="")
    email = models.CharField(max_length=255, null=True, blank=True)
    website_url = models.CharField(max_length=800, null=True, blank=True)
    logo_props = models.JSONField(default=dict, blank=True)
    logo_asset = models.ForeignKey("db.FileAsset", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    # The customer's industry ("Industry" in Plane); the website goes in website_url.
    domain = models.CharField(max_length=255, null=True, blank=True)
    employees = models.PositiveIntegerField(null=True, blank=True)
    stage = models.CharField(max_length=255, null=True, blank=True)
    contract_status = models.CharField(max_length=255, null=True, blank=True)
    revenue = models.CharField(max_length=255, null=True, blank=True)
    external_source = models.CharField(max_length=255, null=True, blank=True)
    external_id = models.CharField(max_length=255, null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Customer"
        verbose_name_plural = "Customers"
        db_table = "customers"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "name"],
                condition=Q(deleted_at__isnull=True),
                name="customer_name_unique_when_deleted_at_null",
            ),
            models.UniqueConstraint(
                fields=["workspace", "external_source", "external_id"],
                condition=Q(deleted_at__isnull=True, external_source__isnull=False, external_id__isnull=False),
                name="customer_external_unique_when_deleted_at_null",
            ),
        ]


class CustomerProperty(BaseModel):
    TEXT = "TEXT"
    DATETIME = "DATETIME"
    DECIMAL = "DECIMAL"
    BOOLEAN = "BOOLEAN"
    OPTION = "OPTION"
    RELATION = "RELATION"
    URL = "URL"
    EMAIL = "EMAIL"
    FILE = "FILE"
    PROPERTY_TYPES = (TEXT, DATETIME, DECIMAL, BOOLEAN, OPTION, RELATION, URL, EMAIL, FILE)
    RELATION_TYPES = ("ISSUE", "USER")

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="customer_properties")
    # A slug of display_name, unique in the workspace.
    name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    logo_props = models.JSONField(default=dict, blank=True)
    sort_order = models.FloatField(default=65535)
    property_type = models.CharField(max_length=16, choices=[(t, t) for t in PROPERTY_TYPES])
    relation_type = models.CharField(max_length=16, choices=[(t, t) for t in RELATION_TYPES], null=True, blank=True)
    is_required = models.BooleanField(default=False)
    default_value = models.JSONField(default=list, blank=True)
    settings = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    is_multi = models.BooleanField(default=False)
    validation_rules = models.JSONField(default=dict, blank=True)
    external_source = models.CharField(max_length=255, null=True, blank=True)
    external_id = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        verbose_name = "Customer Property"
        verbose_name_plural = "Customer Properties"
        db_table = "customer_properties"
        ordering = ("sort_order", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "name"],
                condition=Q(deleted_at__isnull=True),
                name="customer_property_name_unique_when_deleted_at_null",
            )
        ]


class CustomerPropertyOption(BaseModel):
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="+")
    property = models.ForeignKey("db.CustomerProperty", on_delete=models.CASCADE, related_name="options")
    name = models.CharField(max_length=255)
    sort_order = models.FloatField(default=65535)
    description = models.TextField(blank=True, default="")
    logo_props = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    external_source = models.CharField(max_length=255, null=True, blank=True)
    external_id = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        verbose_name = "Customer Property Option"
        verbose_name_plural = "Customer Property Options"
        db_table = "customer_property_options"
        ordering = ("sort_order", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=["property", "name"],
                condition=Q(deleted_at__isnull=True),
                name="customer_property_option_unique_when_deleted_at_null",
            )
        ]


class CustomerPropertyValue(BaseModel):
    """One value of a customer's property, always a string (dates as YYYY-MM-DD, booleans as True/False,
    options and relations as UUIDs); a multi property has one row per value."""

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="+")
    customer = models.ForeignKey("db.Customer", on_delete=models.CASCADE, related_name="property_values")
    property = models.ForeignKey("db.CustomerProperty", on_delete=models.CASCADE, related_name="values")
    value = models.TextField()
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Customer Property Value"
        verbose_name_plural = "Customer Property Values"
        db_table = "customer_property_values"
        ordering = ("sort_order", "created_at")


class CustomerRequest(BaseModel):
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="+")
    customer = models.ForeignKey("db.Customer", on_delete=models.CASCADE, related_name="requests")
    name = models.CharField(max_length=255)
    description = models.JSONField(default=dict, blank=True)
    description_html = models.TextField(blank=True, default="<p></p>")
    description_stripped = models.TextField(blank=True, default="")
    link = models.CharField(max_length=800, null=True, blank=True)

    class Meta:
        verbose_name = "Customer Request"
        verbose_name_plural = "Customer Requests"
        db_table = "customer_requests"
        ordering = ("-created_at",)


class CustomerRequestIssue(BaseModel):
    """A work item linked to a customer, directly or through one of its requests."""

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="+")
    customer = models.ForeignKey("db.Customer", on_delete=models.CASCADE, related_name="issue_links")
    customer_request = models.ForeignKey(
        "db.CustomerRequest", on_delete=models.CASCADE, null=True, blank=True, related_name="issue_links"
    )
    issue = models.ForeignKey("db.Issue", on_delete=models.CASCADE, related_name="customer_links")

    class Meta:
        verbose_name = "Customer Request Issue"
        verbose_name_plural = "Customer Request Issues"
        db_table = "customer_request_issues"
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["customer", "issue"],
                condition=Q(deleted_at__isnull=True, customer_request__isnull=True),
                name="customer_issue_unique_when_deleted_at_null",
            ),
            models.UniqueConstraint(
                fields=["customer", "customer_request", "issue"],
                condition=Q(deleted_at__isnull=True, customer_request__isnull=False),
                name="customer_request_issue_unique_when_deleted_at_null",
            ),
        ]
