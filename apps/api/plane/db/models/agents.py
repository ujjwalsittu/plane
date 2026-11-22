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
from .project import ProjectBaseModel


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
    # The APIToken the vault's credential was made from; the vault is current only while this is the active token
    ma_vault_token_id = models.UUIDField(null=True, blank=True)

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


class AIUsage(BaseModel):
    """One Claude call made for a person (ask, triage, meeting notes); counts toward the monthly AI limit."""

    KIND_CHOICES = (("ask", "Ask"), ("triage", "Triage"), ("meeting_notes", "Meeting notes"))

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="ai_usage")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="ai_usage"
    )
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    model = models.CharField(max_length=100)
    input_tokens = models.PositiveBigIntegerField(default=0)
    output_tokens = models.PositiveBigIntegerField(default=0)
    # Money is integer cents, USD only
    cost_cents = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "AI Usage"
        verbose_name_plural = "AI Usage"
        db_table = "ai_usage"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["workspace", "created_at"], name="ai_usage_ws_created_idx")]

    def __str__(self):
        return f"{self.workspace_id} {self.kind} {self.cost_cents}"


class AgentRun(ProjectBaseModel):
    """One run of an agent (or a person's own Claude Code session) on a work item."""

    KIND_CHOICES = (("managed", "Managed"), ("external", "External"))
    STATUS_CHOICES = (
        ("queued", "Queued"),
        ("running", "Running"),
        ("waiting", "Waiting"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
    )

    issue = models.ForeignKey("db.Issue", on_delete=models.CASCADE, related_name="agent_runs")
    agent = models.ForeignKey(
        "db.WorkspaceAgent", on_delete=models.SET_NULL, null=True, blank=True, related_name="runs"
    )
    # Who reports the run: the agent's bot user, or a person's own token for a Claude Code session
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reported_agent_runs")
    delegated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="delegated_agent_runs"
    )
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default="external")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="queued")
    title = models.CharField(max_length=255, blank=True, default="")
    instructions = models.TextField(blank=True, default="")
    external_session_id = models.CharField(max_length=255, blank=True, default="")
    external_url = models.URLField(max_length=1000, blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    last_event_at = models.DateTimeField(null=True, blank=True)
    # Money is integer cents, USD only
    cost_cents = models.PositiveIntegerField(null=True, blank=True)
    input_tokens = models.PositiveBigIntegerField(default=0)
    output_tokens = models.PositiveBigIntegerField(default=0)
    summary = models.TextField(blank=True, default="")
    error = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Agent Run"
        verbose_name_plural = "Agent Runs"
        db_table = "agent_runs"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["issue", "-created_at"], name="agent_run_issue_created_idx")]

    def __str__(self):
        return f"{self.issue_id} {self.status}"


class AgentRunStep(BaseModel):
    KIND_CHOICES = (
        ("message", "Message"),
        ("tool", "Tool"),
        ("status", "Status"),
        ("pr", "Pull request"),
        ("commit", "Commit"),
        ("error", "Error"),
    )

    run = models.ForeignKey("db.AgentRun", on_delete=models.CASCADE, related_name="steps")
    seq = models.PositiveIntegerField()
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default="message")
    text = models.TextField(blank=True, default="")
    data = models.JSONField(default=dict)
    external_event_id = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = "Agent Run Step"
        verbose_name_plural = "Agent Run Steps"
        db_table = "agent_run_steps"
        ordering = ("seq",)
        constraints = [
            models.UniqueConstraint(
                fields=["run", "seq"], condition=Q(deleted_at__isnull=True), name="agent_run_step_unique_seq"
            ),
            models.UniqueConstraint(
                fields=["run", "external_event_id"],
                condition=Q(deleted_at__isnull=True) & ~Q(external_event_id=""),
                name="agent_run_step_unique_external_event",
            ),
        ]


class AgentApproval(BaseModel):
    """A risky request an agent made, held until its owner approves; Plane then replays it once."""

    ACTION_CHOICES = (("delete", "Delete"), ("change_dates", "Change dates"))
    STATUS_CHOICES = (
        ("open", "Open"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("expired", "Expired"),
        ("executed", "Executed"),
        ("failed", "Failed"),
    )

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="agent_approvals")
    project = models.ForeignKey(
        "db.Project", on_delete=models.CASCADE, null=True, blank=True, related_name="agent_approvals"
    )
    issue = models.ForeignKey(
        "db.Issue", on_delete=models.SET_NULL, null=True, blank=True, related_name="agent_approvals"
    )
    agent = models.ForeignKey("db.WorkspaceAgent", on_delete=models.CASCADE, related_name="approvals")
    asked_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="agent_approvals_asked"
    )
    action = models.CharField(max_length=16, choices=ACTION_CHOICES)
    summary = models.TextField(blank=True, default="")
    method = models.CharField(max_length=10)
    path = models.TextField()
    query = models.TextField(blank=True, default="")
    body = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="open")
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_approvals_decided",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    result_status = models.PositiveSmallIntegerField(null=True, blank=True)
    result_body = models.JSONField(null=True, blank=True)

    class Meta:
        verbose_name = "Agent Approval"
        verbose_name_plural = "Agent Approvals"
        db_table = "agent_approvals"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["asked_user", "status"], name="agent_appr_asked_status_idx")]

    def __str__(self):
        return f"{self.agent_id} {self.action} {self.status}"


class WorkspaceEvent(models.Model):
    """Durable per-workspace change log. Not a BaseModel: agents page through it with the integer id as cursor."""

    EVENT_CHOICES = (
        ("issue", "Issue"),
        ("issue_comment", "Issue comment"),
        ("project", "Project"),
        ("cycle", "Cycle"),
        ("module", "Module"),
        ("milestone", "Milestone"),
        ("decision", "Decision"),
        ("approval", "Approval"),
        ("agent_run", "Agent run"),
    )

    id = models.BigAutoField(primary_key=True)
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="workspace_events")
    project_id = models.UUIDField(null=True, blank=True)
    # The work item the row is about, so readers who can't see that item don't see the row
    issue_id = models.UUIDField(null=True, blank=True)
    event = models.CharField(max_length=32, choices=EVENT_CHOICES)
    action = models.CharField(max_length=32)
    entity_id = models.UUIDField()
    actor_id = models.UUIDField(null=True, blank=True)
    is_agent = models.BooleanField(default=False)
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Workspace Event"
        verbose_name_plural = "Workspace Events"
        db_table = "workspace_events"
        ordering = ("id",)
        indexes = [
            models.Index(fields=["workspace", "id"], name="workspace_event_ws_id_idx"),
            models.Index(fields=["created_at"], name="workspace_event_created_idx"),
        ]

    def __str__(self):
        return f"{self.workspace_id} {self.event}.{self.action}"
