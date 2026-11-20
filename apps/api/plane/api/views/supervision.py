# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Waiting on: who or what a work item is waiting for."""

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.api.views.base import BaseAPIView
from plane.api.views.issue import guest_cannot_view_issue
from plane.app.permissions import ProjectEntityPermission
from plane.db.models import Issue, WorkItemWaiting
from plane.db.models import DecisionRequest, Project, ProjectUpdate, Workspace
from plane.utils import decisions, supervision
from plane.utils.content_validator import validate_html_content
from plane.utils.host import base_host


def _issue(request, slug, project_id, issue_id):
    issue = Issue.issue_objects.filter(workspace__slug=slug, project_id=project_id, pk=issue_id).first()
    if issue is None or guest_cannot_view_issue(request.user.id, issue, slug):
        return None
    return issue


def _missing():
    return Response({"error": "Work item not found"}, status=status.HTTP_404_NOT_FOUND)


class WorkItemWaitingAPIEndpoint(BaseAPIView):
    permission_classes = [ProjectEntityPermission]
    model = WorkItemWaiting

    def get(self, request, slug, project_id, issue_id):
        issue = _issue(request, slug, project_id, issue_id)
        if issue is None:
            return _missing()
        row = (
            WorkItemWaiting.objects.filter(issue=issue, resolved_at__isnull=True)
            .select_related("waiting_on_user")
            .first()
        )
        if row is None:
            return Response(None)
        return Response(supervision.waiting_payload(row))

    def put(self, request, slug, project_id, issue_id):
        issue = _issue(request, slug, project_id, issue_id)
        if issue is None:
            return _missing()
        data = request.data if isinstance(request.data, dict) else {}
        try:
            row = supervision.set_waiting(issue, data, request.user)
        except supervision.SupervisionError as exc:
            return Response({exc.field: exc.message}, status=exc.status_code)
        return Response(supervision.waiting_payload(row))

    def delete(self, request, slug, project_id, issue_id):
        issue = _issue(request, slug, project_id, issue_id)
        if issue is None:
            return _missing()
        supervision.clear_waiting(issue)
        return Response(status=status.HTTP_204_NO_CONTENT)


class DecisionRequestAPIEndpoint(BaseAPIView):
    """List and create the decisions asked on a work item."""

    permission_classes = [ProjectEntityPermission]
    model = DecisionRequest
    source = "api"

    def get(self, request, slug, project_id, issue_id):
        issue = _issue(request, slug, project_id, issue_id)
        if issue is None:
            return _missing()
        rows = DecisionRequest.objects.filter(issue=issue).select_related("created_by")
        wanted = request.query_params.get("status")
        if wanted:
            rows = rows.filter(status=wanted)
        return Response([decisions.decision_payload(row) for row in rows])

    def post(self, request, slug, project_id, issue_id):
        issue = _issue(request, slug, project_id, issue_id)
        if issue is None:
            return _missing()
        data = request.data if isinstance(request.data, dict) else {}
        try:
            decision = decisions.create_decision(issue, data, request.user, self.source)
        except supervision.SupervisionError as exc:
            return Response({exc.field: exc.message}, status=exc.status_code)
        return Response(decisions.decision_payload(decision), status=status.HTTP_201_CREATED)


class _DecisionActionEndpoint(BaseAPIView):
    permission_classes = [ProjectEntityPermission]
    model = DecisionRequest
    source = "api"

    def act(self, request, decision):
        raise NotImplementedError

    def post(self, request, slug, project_id, issue_id, decision_id):
        issue = _issue(request, slug, project_id, issue_id)
        if issue is None:
            return _missing()
        decision = DecisionRequest.objects.filter(pk=decision_id, issue=issue).select_related("created_by").first()
        if decision is None:
            return Response({"error": "Decision not found"}, status=status.HTTP_404_NOT_FOUND)
        try:
            decision = self.act(request, decision)
        except supervision.SupervisionError as exc:
            return Response({exc.field: exc.message}, status=exc.status_code)
        return Response(decisions.decision_payload(decision))


class DecisionAnswerAPIEndpoint(_DecisionActionEndpoint):
    def act(self, request, decision):
        data = request.data if isinstance(request.data, dict) else {}
        return decisions.answer_decision(
            decision, request.user, data.get("answer"), self.source, origin=base_host(request=request, is_app=True)
        )


class DecisionWithdrawAPIEndpoint(_DecisionActionEndpoint):
    def act(self, request, decision):
        return decisions.withdraw_decision(decision, request.user)


class MyDecisionsAPIEndpoint(BaseAPIView):
    """Decisions asked of the signed-in person across the workspace."""

    def get(self, request, slug):
        workspace = Workspace.objects.filter(
            slug=slug, workspace_member__member=request.user, workspace_member__is_active=True
        ).first()
        if workspace is None:
            return Response({"error": "Workspace not found"}, status=status.HTTP_404_NOT_FOUND)
        wanted = request.query_params.get("status", "open")
        return Response(decisions.decisions_for(workspace.id, request.user, wanted))


def _update_payload(update):
    by = update.created_by
    return {
        "id": str(update.id),
        "health": update.health,
        "body_html": update.body_html,
        "source": update.source,
        "created_at": update.created_at.isoformat(),
        "by": {
            "id": str(by.id) if by else None,
            "display_name": (by.display_name or by.email.split("@")[0]) if by else None,
            "is_agent": update.source == "api" or bool(by and by.is_bot),
        },
    }


class ProjectUpdateAPIEndpoint(BaseAPIView):
    """List and post project updates. Project members read, members and admins post (guests cannot)."""

    permission_classes = [ProjectEntityPermission]
    model = ProjectUpdate
    source = "api"

    def get(self, request, slug, project_id):
        rows = ProjectUpdate.objects.filter(workspace__slug=slug, project_id=project_id).select_related("created_by")
        return Response([_update_payload(row) for row in rows[:100]])

    def post(self, request, slug, project_id):
        data = request.data if isinstance(request.data, dict) else {}
        health = data.get("health")
        if health not in dict(ProjectUpdate.HEALTH_CHOICES):
            return Response({"health": "health must be on_track, at_risk or off_track"}, status=400)
        body = data.get("body_html") or ""
        if not isinstance(body, str):
            return Response({"body_html": "body_html must be a string"}, status=400)
        is_valid, error, clean = validate_html_content(body)
        if not is_valid:
            return Response({"body_html": error}, status=400)
        project = Project.objects.filter(workspace__slug=slug, pk=project_id).first()
        if project is None:
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)
        update = ProjectUpdate.objects.create(
            project=project,
            workspace_id=project.workspace_id,
            health=health,
            body_html=clean or "",
            source=self.source,
            created_by=request.user,
        )
        return Response(_update_payload(update), status=status.HTTP_201_CREATED)
