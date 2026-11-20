# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Session-authenticated (web app) versions of the supervision endpoints."""

from rest_framework import status
from rest_framework.response import Response

from plane.api.views import supervision as api
from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView as AppBaseAPIView
from plane.api.views.base import BaseAPIView
from plane.authentication.session import BaseSessionAuthentication
from plane.db.models import SlackConnection, SlackUserLink, Workspace
from plane.utils import brief, slack_app


class _Session:
    authentication_classes = [BaseSessionAuthentication]

    def get_throttles(self):
        return []


class WorkItemWaitingEndpoint(_Session, api.WorkItemWaitingAPIEndpoint):
    pass


class DecisionRequestEndpoint(_Session, api.DecisionRequestAPIEndpoint):
    source = "app"


class DecisionAnswerEndpoint(_Session, api.DecisionAnswerAPIEndpoint):
    source = "app"


class DecisionWithdrawEndpoint(_Session, api.DecisionWithdrawAPIEndpoint):
    source = "app"


class MyDecisionsEndpoint(_Session, api.MyDecisionsAPIEndpoint):
    pass


def _workspace_for(request, slug):
    return Workspace.objects.filter(
        slug=slug, workspace_member__member=request.user, workspace_member__is_active=True
    ).first()


class BriefEndpoint(_Session, BaseAPIView):
    """What needs the signed-in person, what is blocked, and what got done since they last looked."""

    def get(self, request, slug):
        workspace = _workspace_for(request, slug)
        if workspace is None:
            return Response({"error": "Workspace not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(brief.brief_for(workspace.id, request.user))


class BriefSeenEndpoint(_Session, BaseAPIView):
    def post(self, request, slug):
        workspace = _workspace_for(request, slug)
        if workspace is None:
            return Response({"error": "Workspace not found"}, status=status.HTTP_404_NOT_FOUND)
        visit = brief.mark_seen(workspace.id, request.user)
        return Response({"last_seen_at": visit.last_seen_at.isoformat()})


def _slack_payload(workspace):
    """Status of the workspace's Slack connection. Never includes the token."""
    connection = SlackConnection.objects.filter(workspace=workspace).first()
    if connection is None:
        return {"connected": False, "status": None, "team_name": "", "linked_users": 0, "last_error": ""}
    return {
        "connected": True,
        "status": connection.status,
        "team_name": connection.team_name,
        "linked_users": SlackUserLink.objects.filter(workspace=workspace).count(),
        "last_error": connection.last_error,
    }


class SlackConnectionEndpoint(AppBaseAPIView):
    """The workspace's Slack connection (admins only): status, connect or reconnect with a bot token, disconnect."""

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        return Response(_slack_payload(workspace))

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def put(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        token = request.data.get("bot_token")
        if not isinstance(token, str) or not token.strip():
            return Response({"error": "A bot token is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            connection = slack_app.connect(workspace, token.strip())
        except slack_app.SlackError as exc:
            return Response({"error": f"Slack refused the token ({exc})"}, status=status.HTTP_400_BAD_REQUEST)
        slack_app.link_users(connection)
        return Response(_slack_payload(workspace))

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def delete(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        SlackUserLink.objects.filter(workspace=workspace).delete()
        SlackConnection.objects.filter(workspace=workspace).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
