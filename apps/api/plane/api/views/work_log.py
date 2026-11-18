# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Work logs (time tracking) for the SDK/MCP; durations are minutes."""

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.api.views.base import BaseAPIView
from plane.app.permissions import ProjectEntityPermission
from plane.db.models import Issue, IssueWorkLog, Project
from plane.utils import work_logs


def _data(request):
    return request.data if isinstance(request.data, dict) else {}


def _error(exc):
    return Response({"error": exc.message}, status=exc.status_code)


def _issue(slug, project_id, issue_id):
    return (
        Issue.issue_objects.filter(workspace__slug=slug, project_id=project_id, pk=issue_id)
        .select_related("project")
        .first()
    )


class WorkLogListCreateAPIEndpoint(BaseAPIView):
    permission_classes = [ProjectEntityPermission]
    model = IssueWorkLog

    def get(self, request, slug, project_id, issue_id):
        issue = _issue(slug, project_id, issue_id)
        if not issue:
            return Response({"error": "Work item not found"}, status=status.HTTP_404_NOT_FOUND)
        logs = IssueWorkLog.objects.filter(issue=issue)
        return Response([work_logs.payload(log) for log in logs], status=status.HTTP_200_OK)

    def post(self, request, slug, project_id, issue_id):
        issue = _issue(slug, project_id, issue_id)
        if not issue:
            return Response({"error": "Work item not found"}, status=status.HTTP_404_NOT_FOUND)
        try:
            log = work_logs.create(request.user, issue, _data(request))
        except work_logs.WorkLogError as exc:
            return _error(exc)
        return Response(work_logs.payload(log), status=status.HTTP_201_CREATED)


class WorkLogDetailAPIEndpoint(BaseAPIView):
    permission_classes = [ProjectEntityPermission]
    model = IssueWorkLog

    def _log(self, slug, project_id, issue_id, work_log_id):
        return IssueWorkLog.objects.filter(
            workspace__slug=slug, project_id=project_id, issue_id=issue_id, pk=work_log_id
        ).first()

    def patch(self, request, slug, project_id, issue_id, work_log_id):
        log = self._log(slug, project_id, issue_id, work_log_id)
        if not log:
            return Response({"error": "Work log not found"}, status=status.HTTP_404_NOT_FOUND)
        try:
            return Response(work_logs.payload(work_logs.update(request.user, log, _data(request))))
        except work_logs.WorkLogError as exc:
            return _error(exc)

    def delete(self, request, slug, project_id, issue_id, work_log_id):
        log = self._log(slug, project_id, issue_id, work_log_id)
        if not log:
            return Response({"error": "Work log not found"}, status=status.HTTP_404_NOT_FOUND)
        try:
            work_logs.delete(request.user, log)
        except work_logs.WorkLogError as exc:
            return _error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectWorkLogSummaryAPIEndpoint(BaseAPIView):
    """Minutes logged per work item in a project."""

    permission_classes = [ProjectEntityPermission]
    model = IssueWorkLog

    def get(self, request, slug, project_id):
        Project.objects.get(pk=project_id, workspace__slug=slug)
        return Response(work_logs.project_summary(project_id), status=status.HTTP_200_OK)
