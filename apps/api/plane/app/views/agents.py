# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Session-authenticated (web app) agent management."""

from rest_framework import status
from rest_framework.response import Response

from plane.api.views.agents import agent_list, workspace_for
from plane.api.views.base import BaseAPIView
from plane.authentication.session import BaseSessionAuthentication
from plane.db.models import WorkspaceAgent
from plane.utils import agents, ai_config


class _Session:
    authentication_classes = [BaseSessionAuthentication]

    def get_throttles(self):
        return []

    def _workspace(self, request, slug):
        return workspace_for(request, slug)

    def _agent(self, workspace, pk):
        return WorkspaceAgent.objects.filter(workspace=workspace, pk=pk).select_related("owner", "user").first()


def _not_found(what="Workspace"):
    return Response({"error": f"{what} not found"}, status=status.HTTP_404_NOT_FOUND)


def _data(request):
    return request.data if isinstance(request.data, dict) else {}


class AgentsEndpoint(_Session, BaseAPIView):
    def get(self, request, slug):
        workspace = self._workspace(request, slug)
        if workspace is None:
            return _not_found()
        return Response(agent_list(workspace))

    def post(self, request, slug):
        workspace = self._workspace(request, slug)
        if workspace is None:
            return _not_found()
        try:
            agent, token = agents.create_agent(workspace, _data(request), request.user)
        except agents.AgentError as exc:
            return Response({exc.field: exc.message}, status=exc.status_code)
        return Response({**agents.agent_payload(agent), "token": token}, status=status.HTTP_201_CREATED)


class AgentEndpoint(_Session, BaseAPIView):
    def get(self, request, slug, agent_id):
        workspace = self._workspace(request, slug)
        agent = self._agent(workspace, agent_id) if workspace else None
        if agent is None:
            return _not_found("Agent")
        return Response(agents.agent_payload(agent))

    def patch(self, request, slug, agent_id):
        workspace = self._workspace(request, slug)
        agent = self._agent(workspace, agent_id) if workspace else None
        if agent is None:
            return _not_found("Agent")
        try:
            agent = agents.update_agent(agent, _data(request), request.user)
        except agents.AgentError as exc:
            return Response({exc.field: exc.message}, status=exc.status_code)
        return Response(agents.agent_payload(agent))

    def delete(self, request, slug, agent_id):
        workspace = self._workspace(request, slug)
        agent = self._agent(workspace, agent_id) if workspace else None
        if agent is None:
            return _not_found("Agent")
        try:
            agents.deactivate_agent(agent, request.user)
        except agents.AgentError as exc:
            return Response({exc.field: exc.message}, status=exc.status_code)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AgentRotateTokenEndpoint(_Session, BaseAPIView):
    def post(self, request, slug, agent_id):
        workspace = self._workspace(request, slug)
        agent = self._agent(workspace, agent_id) if workspace else None
        if agent is None:
            return _not_found("Agent")
        try:
            token = agents.rotate_token(agent, request.user)
        except agents.AgentError as exc:
            return Response({exc.field: exc.message}, status=exc.status_code)
        return Response({"token": token})


class AISettingsEndpoint(_Session, BaseAPIView):
    """The workspace's Claude key, model and monthly limit (admins only). Never returns the key."""

    def _workspace(self, request, slug):
        workspace = super()._workspace(request, slug)
        if workspace is not None:
            agents._require_admin(workspace, request.user)
        return workspace

    def _respond(self, request, slug, apply=None):
        try:
            workspace = self._workspace(request, slug)
            if workspace is None:
                return _not_found()
            if apply:
                apply(workspace)
        except agents.AgentError as exc:
            return Response({exc.field: exc.message}, status=exc.status_code)
        return Response(ai_config.settings_payload(workspace))

    def get(self, request, slug):
        return self._respond(request, slug)

    def put(self, request, slug):
        return self._respond(request, slug, lambda ws: ai_config.update_settings(ws, _data(request), request.user))

    def delete(self, request, slug):
        return self._respond(request, slug, lambda ws: ai_config.clear_api_key(ws, request.user))
