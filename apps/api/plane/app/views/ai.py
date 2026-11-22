# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Session-authenticated (web app) AI features a person starts: Ask the workspace, triage suggestions, meeting
notes to work items."""

from rest_framework import status
from rest_framework.response import Response

from plane.api.views.agents import create_from_meeting_notes, extract_meeting_notes, triage_issue, workspace_for
from plane.api.views.base import BaseAPIView
from plane.app.permissions import ROLE
from plane.authentication.session import BaseSessionAuthentication
from plane.db.models import WorkspaceMember
from plane.utils import ask as ask_util
from plane.utils import triage
from plane.utils.ai_calls import check_ai_rate
from plane.utils.agents import AgentError


class _Session:
    authentication_classes = [BaseSessionAuthentication]

    def get_throttles(self):
        return []


def _error(exc):
    return Response({"error": exc.message, "field": exc.field}, status=exc.status_code)


class AskEndpoint(_Session, BaseAPIView):
    """A question about the workspace, answered by Claude from what the asking person can see."""

    def post(self, request, slug):
        workspace = workspace_for(request, slug)
        if workspace is None:
            return Response({"error": "Workspace not found"}, status=status.HTTP_404_NOT_FOUND)
        if not WorkspaceMember.objects.filter(
            workspace=workspace, member=request.user, is_active=True, role__gte=ROLE.MEMBER.value
        ).exists():
            return Response({"error": "Only workspace members can ask"}, status=status.HTTP_403_FORBIDDEN)
        data = request.data if isinstance(request.data, dict) else {}
        try:
            check_ai_rate(request.user)
            return Response(ask_util.ask(workspace, request.user, data.get("question"), data.get("history") or []))
        except AgentError as exc:
            return _error(exc)


class TriageEndpoint(_Session, BaseAPIView):
    """Suggested assignee, labels, project and duplicates for a work item (intake items included)."""

    def get(self, request, slug, project_id, issue_id):
        issue, refusal = triage_issue(request, slug, project_id, issue_id)
        if refusal is not None:
            return Response({"error": refusal[0], "field": None}, status=refusal[1])
        try:
            return Response(triage.suggest(issue, request.user, refresh=request.query_params.get("refresh") == "1"))
        except AgentError as exc:
            return _error(exc)


class MeetingNotesExtractEndpoint(_Session, BaseAPIView):
    """Proposed work items from pasted meeting notes, for the person to edit and accept."""

    def post(self, request, slug, project_id):
        try:
            return Response(extract_meeting_notes(request, slug, project_id))
        except AgentError as exc:
            return _error(exc)


class MeetingNotesCreateEndpoint(_Session, BaseAPIView):
    """Create the accepted meeting note items as work items, all or none."""

    def post(self, request, slug, project_id):
        try:
            return Response(create_from_meeting_notes(request, slug, project_id), status=status.HTTP_201_CREATED)
        except AgentError as exc:
            return _error(exc)
