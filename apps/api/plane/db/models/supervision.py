# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Supervision: who or what a work item is waiting on."""

# Django imports
from django.conf import settings
from django.db import models
from django.db.models import Q

# Module imports
from .base import BaseModel
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


class DecisionRequest(ProjectBaseModel):
    """A question an agent (or person) asks a person about a work item. Answering writes a comment
    on the work item, which is where the asker reads the answer."""

    STATUS_CHOICES = (("open", "Open"), ("answered", "Answered"), ("withdrawn", "Withdrawn"))

    issue = models.ForeignKey("db.Issue", on_delete=models.CASCADE, related_name="decision_requests")
    asked_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="decisions_asked")
    question = models.TextField()
    # Empty means a free-text answer.
    options = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="open")
    answer = models.TextField(blank=True, default="")
    answered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    answered_at = models.DateTimeField(null=True, blank=True)
    # "api" when an agent asked through an API key, "app" for the browser session
    source = models.CharField(max_length=8, default="app")

    class Meta:
        verbose_name = "Decision Request"
        verbose_name_plural = "Decision Requests"
        db_table = "decision_requests"
        ordering = ("-created_at",)


class BriefVisit(BaseModel):
    """When a person last looked at their Brief; "done since" is measured from here."""

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="brief_visits")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="brief_visits")
    # Null when the row only records a Slack send: the person has not opened the Brief yet.
    last_seen_at = models.DateTimeField(null=True, blank=True)
    # The local day the Slack brief was last sent, so it goes out at most once a day.
    slack_sent_on = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "Brief Visit"
        verbose_name_plural = "Brief Visits"
        db_table = "brief_visits"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user"],
                condition=Q(deleted_at__isnull=True),
                name="brief_visit_unique_workspace_user",
            )
        ]


class SlackConnection(BaseModel):
    """A workspace's internal Slack app: the bot token (encrypted) and whether it still works."""

    STATUS_CHOICES = (("ok", "Ok"), ("broken", "Broken"))

    workspace = models.OneToOneField("db.Workspace", on_delete=models.CASCADE, related_name="slack_connection")
    team_id = models.CharField(max_length=32, blank=True, default="")
    team_name = models.CharField(max_length=255, blank=True, default="")
    bot_token_encrypted = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="ok")
    last_error = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = "Slack Connection"
        verbose_name_plural = "Slack Connections"
        db_table = "slack_connections"


class SlackUserLink(BaseModel):
    """A workspace member matched to their Slack user (by email)."""

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="slack_user_links")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="slack_links")
    slack_user_id = models.CharField(max_length=32)

    class Meta:
        verbose_name = "Slack User Link"
        verbose_name_plural = "Slack User Links"
        db_table = "slack_user_links"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user"],
                condition=Q(deleted_at__isnull=True),
                name="slack_user_link_unique_workspace_user",
            )
        ]


class ProjectUpdate(ProjectBaseModel):
    """A status post on a project: how it is going, in a sentence or two. Agents post these over the API."""

    HEALTH_CHOICES = (("on_track", "On track"), ("at_risk", "At risk"), ("off_track", "Off track"))

    health = models.CharField(max_length=16, choices=HEALTH_CHOICES)
    body_html = models.TextField(blank=True, default="")
    # "api" when posted through an API key, "app" for the browser session
    source = models.CharField(max_length=8, default="app")

    class Meta:
        verbose_name = "Project Update"
        verbose_name_plural = "Project Updates"
        db_table = "project_updates"
        ordering = ("-created_at",)
