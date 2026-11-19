# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""A work item's GitHub pull requests, branches and commits, for the SDK/MCP."""

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.api.views.base import BaseAPIView
from plane.app.permissions import ProjectEntityPermission
from plane.db.models import GitHubWorkItemLink, Issue
from plane.utils.github_sync import work_item_payload


class WorkItemGitHubAPIEndpoint(BaseAPIView):
    permission_classes = [ProjectEntityPermission]
    model = GitHubWorkItemLink

    def get(self, request, slug, project_id, issue_id):
        issue = (
            Issue.issue_objects.filter(workspace__slug=slug, project_id=project_id, pk=issue_id)
            .select_related("project")
            .first()
        )
        if not issue:
            return Response({"error": "Work item not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(work_item_payload(issue))
