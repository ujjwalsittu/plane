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


class GitHubPullRequest(BaseModel):
    """A pull request in a linked repository, kept current from webhooks."""

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="github_pull_requests")
    repository_id = models.BigIntegerField()
    repository_full_name = models.CharField(max_length=255)
    number = models.PositiveIntegerField()
    title = models.CharField(max_length=1024)
    html_url = models.URLField(max_length=1000)
    # "open" or "closed", as GitHub reports it; drafts and merges are separate flags.
    state = models.CharField(max_length=16, default="open")
    is_draft = models.BooleanField(default=False)
    merged_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    head_ref = models.CharField(max_length=255, blank=True, default="")
    head_sha = models.CharField(max_length=64, blank=True, default="")
    base_ref = models.CharField(max_length=255, blank=True, default="")
    author_login = models.CharField(max_length=255, blank=True, default="")
    # "", "approved" or "changes_requested"
    review_state = models.CharField(max_length=32, blank=True, default="")
    # Check suites and commit statuses for head_sha: {key: "pending" | "success" | "failure"}.
    checks = models.JSONField(default=dict)
    github_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "GitHub Pull Request"
        verbose_name_plural = "GitHub Pull Requests"
        db_table = "github_pull_requests"
        ordering = ("-github_updated_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "repository_id", "number"],
                condition=Q(deleted_at__isnull=True),
                name="github_pull_request_unique_number_when_deleted_at_null",
            )
        ]


class GitHubWorkItemLink(ProjectBaseModel):
    """A pull request, branch or commit that mentions a work item's identifier."""

    PULL_REQUEST = "pull_request"
    BRANCH = "branch"
    COMMIT = "commit"
    KIND_CHOICES = ((PULL_REQUEST, "Pull request"), (BRANCH, "Branch"), (COMMIT, "Commit"))

    issue = models.ForeignKey("db.Issue", on_delete=models.CASCADE, related_name="github_links")
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    pull_request = models.ForeignKey(
        "db.GitHubPullRequest", on_delete=models.CASCADE, null=True, blank=True, related_name="work_item_links"
    )
    repository_id = models.BigIntegerField()
    repository_full_name = models.CharField(max_length=255)
    # The PR number, branch name or commit sha.
    ref = models.CharField(max_length=255)
    title = models.CharField(max_length=1024, blank=True, default="")
    url = models.URLField(max_length=1000, blank=True, default="")
    author_login = models.CharField(max_length=255, blank=True, default="")
    github_created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "GitHub Work Item Link"
        verbose_name_plural = "GitHub Work Item Links"
        db_table = "github_work_item_links"
        ordering = ("-github_created_at", "-created_at")
        constraints = [
            models.UniqueConstraint(
                fields=["issue", "kind", "repository_id", "ref"],
                condition=Q(deleted_at__isnull=True),
                name="github_work_item_link_unique_ref_when_deleted_at_null",
            )
        ]


class GitHubProjectAutomation(ProjectBaseModel):
    """How pull request events move a project's work items. Projects without a row use defaults
    derived from their states (see plane.utils.github_automation)."""

    enabled = models.BooleanField(default=True)
    # Complete items named after "Fixes/Closes/Resolves" in a PR body when it merges.
    close_keywords = models.BooleanField(default=True)
    draft_state = models.ForeignKey("db.State", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    open_state = models.ForeignKey("db.State", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    review_requested_state = models.ForeignKey(
        "db.State", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    merge_state = models.ForeignKey("db.State", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        verbose_name = "GitHub Project Automation"
        verbose_name_plural = "GitHub Project Automations"
        db_table = "github_project_automations"
        constraints = [
            models.UniqueConstraint(
                fields=["project"],
                condition=Q(deleted_at__isnull=True),
                name="github_project_automation_unique_project_when_deleted_at_null",
            )
        ]
