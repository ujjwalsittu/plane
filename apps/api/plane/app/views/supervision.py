# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Session-authenticated (web app) versions of the supervision endpoints."""

from rest_framework import status
from rest_framework.response import Response

from plane.api.views import supervision as api
from plane.api.views.base import BaseAPIView
from plane.authentication.session import BaseSessionAuthentication
from plane.db.models import Workspace
from plane.utils import brief


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
