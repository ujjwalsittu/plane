# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""GitHub App integration: a workspace's app installations, the repositories linked to its
projects, and the webhook deliveries GitHub sends. The app's own credentials (id, private key,
webhook secret) live in server environment variables, never in the database."""

# Django imports
from django.db import models
from django.db.models import Q

# Module imports
from .base import BaseModel
from .project import ProjectBaseModel


class GitHubInstallation(BaseModel):
    """An installation of the GitHub App on a user or organization account, claimed by one
    workspace."""

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="github_installations")
    installation_id = models.BigIntegerField()
    account_login = models.CharField(max_length=255)
    account_id = models.BigIntegerField(null=True, blank=True)
    # "User" or "Organization"
    account_type = models.CharField(max_length=32, blank=True, default="")
    account_avatar_url = models.URLField(max_length=1000, blank=True, default="")
    # "all" or "selected"
    repository_selection = models.CharField(max_length=32, blank=True, default="")
    suspended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "GitHub Installation"
        verbose_name_plural = "GitHub Installations"
        db_table = "github_installations"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["installation_id"],
                condition=Q(deleted_at__isnull=True),
                name="github_installation_unique_when_deleted_at_null",
            )
        ]


class GitHubRepositoryLink(ProjectBaseModel):
    """A repository of an installation linked to a project; references to the project's work
    items in that repository's branches, PRs and commits are picked up."""

    installation = models.ForeignKey("db.GitHubInstallation", on_delete=models.CASCADE, related_name="repository_links")
    repository_id = models.BigIntegerField()
    full_name = models.CharField(max_length=255)
    html_url = models.URLField(max_length=1000, blank=True, default="")
    default_branch = models.CharField(max_length=255, blank=True, default="")
    is_private = models.BooleanField(default=False)

    class Meta:
        verbose_name = "GitHub Repository Link"
        verbose_name_plural = "GitHub Repository Links"
        db_table = "github_repository_links"
        ordering = ("full_name",)
        constraints = [
            models.UniqueConstraint(
                fields=["project", "repository_id"],
                condition=Q(deleted_at__isnull=True),
                name="github_repository_link_unique_project_repository_when_deleted_at_null",
            )
        ]


class GitHubWebhookDelivery(models.Model):
    """A webhook delivery as received. Deliveries are keyed by GitHub's delivery id so a
    redelivery is processed once; the worker retries failures."""

    PENDING = "pending"
    PROCESSED = "processed"
    FAILED = "failed"
    STATUS_CHOICES = ((PENDING, "Pending"), (PROCESSED, "Processed"), (FAILED, "Failed"))

    delivery_id = models.CharField(max_length=100, unique=True)
    event = models.CharField(max_length=100)
    action = models.CharField(max_length=100, blank=True, default="")
    installation_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PENDING)
    attempts = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True, default="")
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "GitHub Webhook Delivery"
        verbose_name_plural = "GitHub Webhook Deliveries"
        db_table = "github_webhook_deliveries"
        ordering = ("-received_at",)
