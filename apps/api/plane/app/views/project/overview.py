# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.db.models import Project, ProjectTag, Workspace
from plane.utils.project_overview import (
    OverviewError,
    create_tag,
    overview_payload,
    tag_payload,
    update_overview,
    update_tag,
)


def _error(exc):
    return Response({exc.field: exc.message, "error": exc.message}, status=status.HTTP_400_BAD_REQUEST)


class ProjectOverviewEndpoint(BaseAPIView):
    """The project home page's overview, linked pages and tags."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        return Response(overview_payload(request.user, project), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def patch(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        try:
            update_overview(request.user, project, request.data if isinstance(request.data, dict) else {})
        except OverviewError as exc:
            return _error(exc)
        return Response(overview_payload(request.user, project), status=status.HTTP_200_OK)


class ProjectTagEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug):
        tags = ProjectTag.objects.filter(workspace__slug=slug)
        return Response([tag_payload(tag) for tag in tags], status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def post(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        try:
            tag = create_tag(workspace.id, request.data if isinstance(request.data, dict) else {})
        except OverviewError as exc:
            return _error(exc)
        return Response(tag_payload(tag), status=status.HTTP_201_CREATED)


class ProjectTagDetailEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def patch(self, request, slug, pk):
        tag = ProjectTag.objects.get(workspace__slug=slug, pk=pk)
        try:
            update_tag(tag, request.data if isinstance(request.data, dict) else {})
        except OverviewError as exc:
            return _error(exc)
        return Response(tag_payload(tag), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def delete(self, request, slug, pk):
        tag = ProjectTag.objects.get(workspace__slug=slug, pk=pk)
        tag.projects.clear()
        tag.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
