# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Agents as workspace members: a bot user with its own token, a responsible person and limits."""

# Django imports
from django.conf import settings
from django.db import models
from django.db.models import Q

# Module imports
from .base import BaseModel


def default_approval_actions():
    return ["delete", "change_dates"]


class WorkspaceAgent(BaseModel):
    PERMISSION_CHOICES = (("read", "Read"), ("contribute", "Contribute"), ("manage", "Manage"))

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="workspace_agents")
    # The bot user the agent acts as
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workspace_agent")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    # The person responsible for the agent
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_agents")
    permission = models.CharField(max_length=16, choices=PERMISSION_CHOICES, default="contribute")
    # Actions that wait for a person's approval before the agent may do them
    approval_actions = models.JSONField(default=default_approval_actions)
    run_budget_cents = models.PositiveIntegerField(default=500)
    is_active = models.BooleanField(default=True)
    # Claude Managed Agents handles, filled in by the run integration
    ma_agent_id = models.CharField(max_length=255, blank=True, default="")
    ma_agent_version = models.PositiveIntegerField(null=True, blank=True)
    ma_vault_id = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = "Workspace Agent"
        verbose_name_plural = "Workspace Agents"
        db_table = "workspace_agents"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "name"],
                condition=Q(deleted_at__isnull=True),
                name="workspace_agent_unique_workspace_name",
            )
        ]

    def __str__(self):
        return f"{self.workspace_id} {self.name}"


class WorkspaceAIConfig(BaseModel):
    """A workspace's own Claude key (encrypted), model and monthly spend limit for AI features and agent runs."""

    STATUS_CHOICES = (("ok", "Ok"), ("broken", "Broken"), ("unset", "Unset"))

    workspace = models.OneToOneField("db.Workspace", on_delete=models.CASCADE, related_name="ai_config")
    api_key_encrypted = models.TextField(blank=True, default="")
    # Money is integer cents, USD only; null means no limit
    monthly_limit_cents = models.PositiveIntegerField(null=True, blank=True)
    model = models.CharField(max_length=100, blank=True, default="")
    ma_environment_id = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="unset")
    last_error = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Workspace AI Config"
        verbose_name_plural = "Workspace AI Configs"
        db_table = "workspace_ai_configs"
