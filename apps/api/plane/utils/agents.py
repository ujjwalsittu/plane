# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Agents as workspace members: a bot user with its own API token, a responsible person and limits."""

import uuid

from django.db import IntegrityError, transaction
from django.db.models import Max

from plane.db.models import (
    AgentApproval,
    AgentRun,
    APIActivityLog,
    APIToken,
    Project,
    ProjectMember,
    User,
    WorkspaceAgent,
    WorkspaceMember,
)

ADMIN = 20
MEMBER = 15
APPROVAL_ACTIONS = {"delete", "change_dates"}
BUDGET_MIN_CENTS = 50
BUDGET_MAX_CENTS = 100000


class AgentError(ValueError):
    def __init__(self, message, status_code=400, field="error"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.field = field


def _sync_cloud_agent(agent, **kwargs):
    """Keep the agent's Managed Agents agent and vault in step; a no-op until cloud agents are set up."""
    from plane.utils.managed_agents import on_agent_changed

    on_agent_changed(agent, **kwargs)


def on_agent_deactivated(agent):
    """Hook for work that must stop with the agent (runs, sessions). Filled in by the run integration."""


def _require_admin(workspace, actor):
    if not WorkspaceMember.objects.filter(workspace=workspace, member=actor, role=ADMIN, is_active=True).exists():
        raise AgentError("Only workspace admins can manage agents", 403)


def require_admin(workspace, actor):
    _require_admin(workspace, actor)


def _uuid(value, field):
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise AgentError("Invalid id", 400, field)


def _clean_avatar(value):
    if value is not None and not isinstance(value, str):
        raise AgentError("avatar_url must be a string", 400, "avatar_url")
    return value or ""


def _clean_name(value):
    name = (value or "").strip() if isinstance(value, str) else ""
    if not name:
        raise AgentError("Name is required", 400, "name")
    if len(name) > 255:
        raise AgentError("Name is too long", 400, "name")
    return name


def _clean_owner(workspace, value):
    owner = (
        User.objects.filter(
            pk=_uuid(value, "owner"),
            member_workspace__workspace=workspace,
            member_workspace__is_active=True,
            is_bot=False,
        ).first()
        if value
        else None
    )
    if owner is None:
        raise AgentError("The owner must be a person in this workspace", 400, "owner")
    return owner


def _clean_permission(value):
    if value not in dict(WorkspaceAgent.PERMISSION_CHOICES):
        raise AgentError("Permission must be read, contribute or manage", 400, "permission")
    return value


def _clean_approval_actions(value):
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value) or not set(value) <= APPROVAL_ACTIONS:
        raise AgentError("Approval actions must be a subset of delete and change_dates", 400, "approval_actions")
    return sorted(set(value))


def _clean_budget(value):
    if isinstance(value, bool) or not isinstance(value, int) or not BUDGET_MIN_CENTS <= value <= BUDGET_MAX_CENTS:
        raise AgentError(
            f"Run budget must be between {BUDGET_MIN_CENTS} and {BUDGET_MAX_CENTS} cents", 400, "run_budget_cents"
        )
    return value


def _clean_projects(workspace, actor, value):
    if not isinstance(value, list):
        raise AgentError("project_ids must be a list", 400, "project_ids")
    ids = {str(_uuid(v, "project_ids")) for v in value}
    projects = list(Project.objects.filter(workspace=workspace, pk__in=ids)) if ids else []
    if len(projects) != len(ids):
        raise AgentError("Unknown project", 400, "project_ids")
    # The actor must be an active admin member of every project they give the agent
    admins = set(
        str(p)
        for p in ProjectMember.objects.filter(project_id__in=ids, member=actor, role=ADMIN, is_active=True).values_list(
            "project_id", flat=True
        )
    )
    if any(str(p.id) not in admins for p in projects):
        raise AgentError("You must be an admin of every project you give the agent", 403, "project_ids")
    return projects


def _set_project_membership(agent, projects):
    wanted = {p.id for p in projects}
    for member in ProjectMember.objects.filter(member=agent.user, project__workspace=agent.workspace):
        if member.project_id in wanted:
            wanted.discard(member.project_id)
            if not member.is_active or member.role != MEMBER:
                member.is_active = True
                member.role = MEMBER
                member.save(update_fields=["is_active", "role"])
        elif member.is_active:
            member.is_active = False
            member.save(update_fields=["is_active"])
    for project in projects:
        if project.id in wanted:
            ProjectMember.objects.create(
                project=project, workspace=agent.workspace, member=agent.user, role=MEMBER, is_active=True
            )


def _new_token(agent):
    token = APIToken.objects.create(
        user=agent.user, user_type=1, workspace=agent.workspace, label=f"agent:{agent.name}"
    )
    return token.token


def create_agent(workspace, data, actor):
    """Create the bot user, its memberships and its API token. Returns the agent and the plaintext token."""
    _require_admin(workspace, actor)
    name = _clean_name(data.get("name"))
    owner = _clean_owner(workspace, data.get("owner"))
    permission = _clean_permission(data.get("permission", "contribute"))
    approval_actions = _clean_approval_actions(data.get("approval_actions", ["delete", "change_dates"]))
    budget = _clean_budget(data.get("run_budget_cents", 500))
    projects = _clean_projects(workspace, actor, data.get("project_ids", []))
    if WorkspaceAgent.objects.filter(workspace=workspace, name=name).exists():
        raise AgentError("An agent with this name already exists", 400, "name")
    try:
        with transaction.atomic():
            bot = User.objects.create(
                email=f"agent-{uuid.uuid4().hex}@agents.invalid",
                username=uuid.uuid4().hex,
                display_name=name,
                first_name=name,
                is_bot=True,
                bot_type="agent",
                is_password_autoset=True,
                avatar=_clean_avatar(data.get("avatar_url")),
            )
            bot.set_unusable_password()
            bot.save(update_fields=["password"])
            agent = WorkspaceAgent.objects.create(
                workspace=workspace,
                user=bot,
                name=name,
                description=data.get("description") or "",
                owner=owner,
                permission=permission,
                approval_actions=approval_actions,
                run_budget_cents=budget,
                created_by=actor,
            )
            WorkspaceMember.objects.create(workspace=workspace, member=bot, role=MEMBER)
            _set_project_membership(agent, projects)
            token = _new_token(agent)
    except IntegrityError:
        raise AgentError("An agent with this name already exists", 400, "name")
    _sync_cloud_agent(agent, token=token)
    return agent, token


def update_agent(agent, data, actor):
    _require_admin(agent.workspace, actor)
    if not agent.is_active:
        raise AgentError("The agent is deactivated", 400)
    with transaction.atomic():
        if "name" in data:
            agent.name = _clean_name(data["name"])
            if WorkspaceAgent.objects.filter(workspace=agent.workspace, name=agent.name).exclude(pk=agent.pk).exists():
                raise AgentError("An agent with this name already exists", 400, "name")
            User.objects.filter(pk=agent.user_id).update(display_name=agent.name, first_name=agent.name)
        if "description" in data:
            agent.description = data["description"] or ""
        if "owner" in data:
            agent.owner = _clean_owner(agent.workspace, data["owner"])
        if "permission" in data:
            agent.permission = _clean_permission(data["permission"])
        if "approval_actions" in data:
            agent.approval_actions = _clean_approval_actions(data["approval_actions"])
        if "run_budget_cents" in data:
            agent.run_budget_cents = _clean_budget(data["run_budget_cents"])
        if "avatar_url" in data:
            User.objects.filter(pk=agent.user_id).update(avatar=_clean_avatar(data["avatar_url"]))
        agent.updated_by = actor
        agent.save()
        if "project_ids" in data:
            _set_project_membership(agent, _clean_projects(agent.workspace, actor, data["project_ids"]))
    _sync_cloud_agent(agent)
    return agent


def deactivate_agent(agent, actor):
    _require_admin(agent.workspace, actor)
    with transaction.atomic():
        agent.is_active = False
        agent.save(update_fields=["is_active", "updated_at"])
        User.objects.filter(pk=agent.user_id).update(is_active=False)
        APIToken.objects.filter(user=agent.user).update(is_active=False)
        ProjectMember.objects.filter(member=agent.user).update(is_active=False)
        WorkspaceMember.objects.filter(member=agent.user, workspace=agent.workspace).update(is_active=False)
    on_agent_deactivated(agent)
    _sync_cloud_agent(agent, deactivated=True)
    return agent


def rotate_token(agent, actor):
    """Revoke the agent's tokens and issue a new one, returned once."""
    _require_admin(agent.workspace, actor)
    if not agent.is_active:
        raise AgentError("The agent is deactivated", 400)
    with transaction.atomic():
        APIToken.objects.filter(user=agent.user, is_active=True).update(is_active=False)
        token = _new_token(agent)
    _sync_cloud_agent(agent, token=token)
    return token


def agent_for_user(user):
    if user is None or not getattr(user, "is_bot", False):
        return None
    return WorkspaceAgent.objects.filter(user=user).select_related("workspace").first()


def agent_payload(agent):
    owner = agent.owner
    project_ids = ProjectMember.objects.filter(
        member_id=agent.user_id, project__workspace_id=agent.workspace_id, is_active=True
    ).values_list("project_id", flat=True)
    last_active = APIToken.objects.filter(user_id=agent.user_id).aggregate(m=Max("last_used"))["m"]
    return {
        "id": str(agent.id),
        "name": agent.name,
        "description": agent.description,
        "avatar_url": agent.user.avatar_url,
        "user_id": str(agent.user_id),
        "owner": {"id": str(owner.id), "display_name": owner.display_name or owner.email},
        "permission": agent.permission,
        "approval_actions": agent.approval_actions,
        "run_budget_cents": agent.run_budget_cents,
        "is_active": agent.is_active,
        "project_ids": sorted(str(p) for p in project_ids),
        "last_active_at": last_active.isoformat() if last_active else None,
    }


AUDIT_LIMIT = 200


def audit_for(agent, limit=AUDIT_LIMIT):
    """What an agent did, newest first: its API requests (across every token it ever had, revoked ones
    included, so history survives rotation), the approvals it asked for and its runs."""
    tokens = list(APIToken.objects.filter(user_id=agent.user_id).values_list("token", flat=True))
    rows = [
        {
            "at": log.created_at.isoformat(),
            "kind": "request",
            "method": log.method,
            "path": log.path,
            "status": log.response_code,
        }
        for log in APIActivityLog.objects.filter(token_identifier__in=tokens).order_by("-created_at")[:limit]
    ]
    rows += [
        {
            "at": approval.created_at.isoformat(),
            "kind": "approval",
            "id": str(approval.id),
            "action": approval.action,
            "summary": approval.summary,
            "status": approval.status,
            "decided_by": (approval.decided_by.display_name or approval.decided_by.email)
            if approval.decided_by
            else None,
            "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
        }
        for approval in AgentApproval.objects.filter(agent=agent)
        .select_related("decided_by")
        .order_by("-created_at")[:limit]
    ]
    rows += [
        {
            "at": run.created_at.isoformat(),
            "kind": "run",
            "id": str(run.id),
            "issue_id": str(run.issue_id),
            "title": run.title,
            "status": run.status,
        }
        for run in AgentRun.objects.filter(agent=agent).order_by("-created_at")[:limit]
    ]
    rows.sort(key=lambda row: row["at"], reverse=True)
    return rows[:limit]
