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
from plane.utils import supervision


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
