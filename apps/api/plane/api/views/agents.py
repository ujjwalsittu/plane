# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Agents as workspace members."""

from rest_framework import status
from rest_framework.response import Response

from plane.api.views.base import BaseAPIView
from plane.db.models import Workspace, WorkspaceAgent
from plane.utils import agents


def workspace_for(request, slug):
    return Workspace.objects.filter(
        slug=slug, workspace_member__member=request.user, workspace_member__is_active=True
    ).first()


def agent_list(workspace):
    rows = WorkspaceAgent.objects.filter(workspace=workspace).select_related("owner", "user")
    return [agents.agent_payload(agent) for agent in rows]


class WorkspaceAgentsAPIEndpoint(BaseAPIView):
    """Read-only list so agents can see each other."""

    def get(self, request, slug):
        workspace = workspace_for(request, slug)
        if workspace is None:
            return Response({"error": "Workspace not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(agent_list(workspace))
