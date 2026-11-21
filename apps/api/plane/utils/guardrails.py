# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Guardrails for agent API tokens: read-only agents can't write, and risky requests (deleting or archiving,
changing dates) wait for the agent's owner to approve. Plane then replays the held request once, as the agent."""

import json
import uuid
from datetime import timedelta

import crum
from django.core import signing
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q
from django.http import QueryDict
from django.urls import Resolver404, resolve
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException, AuthenticationFailed, PermissionDenied

from plane.db.models import AgentApproval, APIToken, Issue, Project, WorkspaceAgent, WorkspaceMember
from plane.utils.agents import ADMIN, AgentError, agent_for_user
from plane.utils.exception_logger import log_exception

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
DATE_KEYS = frozenset({"start_date", "target_date", "end_date"})
APPROVAL_HEADER = "X-Plane-Approval"
APPROVAL_SALT = "agent-approval"
# The signed header only lives for the in-process replay
SIGNATURE_MAX_AGE = 600
EXPIRE_DAYS = 7
MAX_BODY_DEPTH = 6


class ApprovalRequired(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_code = "approval_required"

    def __init__(self, approval):
        owner = approval.asked_user
        name = owner.display_name or owner.first_name or owner.email
        detail = f"Waiting for {name} to approve: {approval.summary}. Plane runs it once approved; do not retry."
        super().__init__({"error": "approval_required", "approval_id": str(approval.id), "detail": detail})


def on_approval_created(approval):
    """Hook to tell the owner an approval is waiting (Slack DM, notification). Filled in by the Slack integration."""


# --- classifying a request --------------------------------------------------------------------


def _json_body(request):
    """The request body as DRF parsed it (cached, so the view still gets it), as plain JSON data or None.
    A body DRF can't parse raises here (400), as it would in the view."""
    data = request.data
    if isinstance(data, QueryDict):
        data = data.dict()
    if not data:
        return None
    try:
        return json.loads(json.dumps(data, cls=DjangoJSONEncoder))
    except (TypeError, ValueError):
        return None


def _has_date_key(value, depth=0):
    if depth > MAX_BODY_DEPTH:
        return False
    if isinstance(value, dict):
        return bool(DATE_KEYS & set(value)) or any(_has_date_key(v, depth + 1) for v in value.values())
    if isinstance(value, list):
        return any(_has_date_key(v, depth + 1) for v in value)
    return False


def classify(request):
    """ "delete" for deleting or archiving, "change_dates" for an update that sets a date, else None."""
    method = request.method.upper()
    if method == "DELETE":
        return "delete"
    if method == "POST" and request.path.rstrip("/").endswith("/archive"):
        return "delete"
    if method in ("PATCH", "PUT") and _has_date_key(_json_body(request)):
        return "change_dates"
    return None


# --- the gate ----------------------------------------------------------------------------------


def _approved_replay(request, agent):
    """True only for Plane's own replay of this exact approval, while it is approved."""
    header = request.headers.get(APPROVAL_HEADER)
    if not header:
        return False
    try:
        approval_id = uuid.UUID(str(signing.loads(header, salt=APPROVAL_SALT, max_age=SIGNATURE_MAX_AGE)))
    except (signing.BadSignature, ValueError, TypeError):
        return False
    return AgentApproval.objects.filter(
        pk=approval_id,
        agent=agent,
        status="approved",
        method=request.method.upper(),
        path=request.path,
        query=request.META.get("QUERY_STRING", ""),
    ).exists()


def _scope(request, agent):
    match = getattr(request, "resolver_match", None)
    if match is None:
        try:
            match = resolve(request.path_info)
        except Resolver404:
            match = None
    kwargs = match.kwargs if match else {}
    project = issue = None
    if kwargs.get("project_id"):
        project = Project.objects.filter(workspace_id=agent.workspace_id, pk=kwargs["project_id"]).first()
    issue_id = kwargs.get("issue_id") or kwargs.get("pk")
    if project and issue_id:
        issue = Issue.issue_objects.filter(project=project, pk=issue_id).select_related("project").first()
    return project, issue


def _summary(action, method, path, body, issue):
    target = f'{issue.project.identifier}-{issue.sequence_id} "{issue.name}"' if issue else path
    if action == "delete":
        return f"{'archive' if method == 'POST' else 'delete'} {target}"
    dates = [f"{k} to {body[k] or 'none'}" for k in sorted(DATE_KEYS) if isinstance(body, dict) and k in body]
    return f"change dates on {target}" + (f" ({', '.join(dates)})" if dates else "")


def _open_approval(request, agent, action):
    """The open approval for this exact request (method, path, query and body), created if there is none."""
    method = request.method.upper()
    path = request.path
    query = request.META.get("QUERY_STRING", "")
    body = _json_body(request)
    created = False
    with transaction.atomic():
        # Serialise one agent's requests so the same request never opens two approvals
        WorkspaceAgent.objects.select_for_update().filter(pk=agent.pk).first()
        approval = next(
            (
                a
                for a in AgentApproval.objects.filter(
                    agent=agent, status="open", method=method, path=path, query=query
                ).select_related("asked_user")
                if a.body == body
            ),
            None,
        )
        if approval is None:
            project, issue = _scope(request, agent)
            approval = AgentApproval(
                workspace_id=agent.workspace_id,
                project=project,
                issue=issue,
                agent=agent,
                asked_user_id=agent.owner_id,
                action=action,
                summary=_summary(action, method, path, body, issue),
                method=method,
                path=path,
                query=query,
                body=body,
            )
            approval.save(created_by_id=agent.user_id)
            approval = AgentApproval.objects.select_related("asked_user").get(pk=approval.pk)
            created = True
    if created:
        try:
            on_approval_created(approval)
        except Exception as exc:
            log_exception(exc)
    return approval


def check_request(request, user):
    """Called for every API-key request once the token is valid. Does nothing for people."""
    if user is None or not getattr(user, "is_bot", False):
        return
    agent = agent_for_user(user)
    if agent is None:
        # Fail closed for an agent bot whose agent record is gone
        if getattr(user, "bot_type", None) == "agent":
            raise AuthenticationFailed("This agent is not active")
        return
    if not agent.is_active:
        raise AuthenticationFailed("This agent is deactivated")
    method = request.method.upper()
    if agent.permission == "read" and method not in SAFE_METHODS:
        raise PermissionDenied("This agent is read-only")
    action = classify(request)
    if action is None:
        return
    if action in (agent.approval_actions or []):
        if _approved_replay(request, agent):
            return
        raise ApprovalRequired(_open_approval(request, agent, action))
    if action == "delete" and agent.permission == "contribute":
        raise PermissionDenied("This agent can't delete or archive")


# --- deciding and replaying --------------------------------------------------------------------


def _is_admin(workspace_id, user):
    return WorkspaceMember.objects.filter(workspace_id=workspace_id, member=user, role=ADMIN, is_active=True).exists()


def decide_approval(approval, user, approve):
    """The owner (or a workspace admin) approves or rejects; an approval replays the held request once."""
    if user.id != approval.asked_user_id and not _is_admin(approval.workspace_id, user):
        raise AgentError("Only the agent's owner or a workspace admin can decide", 403)
    with transaction.atomic():
        approval = AgentApproval.objects.select_for_update().get(pk=approval.pk)
        was_open = approval.status == "open"
        if was_open and approval.created_at < timezone.now() - timedelta(days=EXPIRE_DAYS):
            # Past the deadline but not swept yet
            approval.status = "expired"
            approval.save(update_fields=["status", "updated_at"])
        elif was_open:
            approval.status = "approved" if approve else "rejected"
            approval.decided_by = user
            approval.decided_at = timezone.now()
            approval.save(update_fields=["status", "decided_by", "decided_at", "updated_at"])
    if not was_open or approval.status == "expired":
        raise AgentError("This approval has already been decided or has expired", 409, "status")
    if approve:
        replay(approval)
    return approval


def _response_body(response):
    data = getattr(response, "data", None)
    if data is None:
        return None
    try:
        return json.loads(json.dumps(data, cls=DjangoJSONEncoder))
    except (TypeError, ValueError):
        return {"detail": str(data)}


def replay(approval):
    """Run the held request once, through the same API-key auth, as the agent. Records the outcome."""
    from rest_framework.test import APIRequestFactory

    agent = approval.agent
    token = (
        APIToken.objects.filter(user_id=agent.user_id, is_active=True)
        .filter(Q(expired_at__isnull=True) | Q(expired_at__gt=timezone.now()))
        .order_by("-created_at")
        .first()
    )
    if token is None:
        result_status, result_body = None, {"error": "The agent has no active token"}
    else:
        url = approval.path + (f"?{approval.query}" if approval.query else "")
        request = APIRequestFactory().generic(
            approval.method,
            url,
            data=json.dumps(approval.body) if approval.body is not None else "",
            content_type="application/json",
            HTTP_X_API_KEY=token.token,
            HTTP_X_PLANE_APPROVAL=signing.dumps(str(approval.id), salt=APPROVAL_SALT),
        )
        try:
            match = resolve(approval.path)
            request.resolver_match = match
            # Model audit fields (created_by/updated_by) follow the agent, not the person approving
            with crum.impersonate(agent.user):
                response = match.func(request, *match.args, **match.kwargs)
            result_status, result_body = response.status_code, _response_body(response)
        except Resolver404:
            result_status, result_body = 404, {"error": "Not found"}
        except Exception as exc:
            log_exception(exc)
            result_status, result_body = 500, {"error": "The request failed"}
    approval.result_status = result_status
    approval.result_body = result_body
    approval.status = "executed" if result_status and 200 <= result_status < 300 else "failed"
    approval.save(update_fields=["result_status", "result_body", "status", "updated_at"])
    return approval


def expire_approvals():
    """Open approvals older than a week expire; the agent must ask again."""
    cutoff = timezone.now() - timedelta(days=EXPIRE_DAYS)
    return AgentApproval.objects.filter(status="open", created_at__lt=cutoff).update(
        status="expired", updated_at=timezone.now()
    )


def approval_payload(approval):
    asked = approval.asked_user
    decided = approval.decided_by
    return {
        "id": str(approval.id),
        "agent": {"id": str(approval.agent_id), "name": approval.agent.name},
        "asked_user": {"id": str(asked.id), "display_name": asked.display_name or asked.email},
        "action": approval.action,
        "summary": approval.summary,
        "status": approval.status,
        "method": approval.method,
        "path": approval.path,
        "query": approval.query,
        "body": approval.body,
        "project_id": str(approval.project_id) if approval.project_id else None,
        "issue_id": str(approval.issue_id) if approval.issue_id else None,
        "decided_by": {"id": str(decided.id), "display_name": decided.display_name or decided.email}
        if decided
        else None,
        "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
        "result_status": approval.result_status,
        "result_body": approval.result_body,
        "created_at": approval.created_at.isoformat(),
    }


def approvals_for(workspace, user, status_filter=None):
    rows = AgentApproval.objects.filter(workspace=workspace, asked_user=user).select_related(
        "agent", "asked_user", "decided_by"
    )
    if status_filter:
        rows = rows.filter(status=status_filter)
    return rows


def can_view(approval, user):
    return user.id in (approval.asked_user_id, approval.agent.user_id) or _is_admin(approval.workspace_id, user)
