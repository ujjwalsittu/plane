# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.db.models import Issue
from plane.utils.work_item_pages import WorkItemPageError, create_link, link_payload, links_for


def _work_item(slug, project_id, issue_id):
    return Issue.issue_objects.filter(workspace__slug=slug, project_id=project_id, pk=issue_id).first()


class IssuePageLinkEndpoint(BaseAPIView):
    """Pages linked to a work item, for the work item's Pages section."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, issue_id):
        links = links_for(request.user, project_id, issue_id)
        return Response([link_payload(link) for link in links], status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def post(self, request, slug, project_id, issue_id):
        issue = _work_item(slug, project_id, issue_id)
        if not issue:
            return Response({"error": "Work item not found"}, status=status.HTTP_404_NOT_FOUND)
        data = request.data if isinstance(request.data, dict) else {}
        try:
            link, created = create_link(request.user, issue, data.get("page_id"))
        except WorkItemPageError as exc:
            return Response({exc.field: exc.message, "error": exc.message}, status=exc.status_code)
        return Response(link_payload(link), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class IssuePageLinkDetailEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def delete(self, request, slug, project_id, issue_id, pk):
        link = links_for(request.user, project_id, issue_id).filter(pk=pk).first()
        if not link:
            return Response({"error": "Page link not found"}, status=status.HTTP_404_NOT_FOUND)
        link.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
