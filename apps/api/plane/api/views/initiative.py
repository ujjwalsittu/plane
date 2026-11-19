# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Initiatives for the SDK/MCP: CRUD, linked projects and linked work items."""

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.api.serializers import IssueSerializer, ProjectSerializer
from plane.api.views.base import BaseAPIView
from plane.app.permissions import WorkspaceEntityPermission
from plane.db.models import Initiative, Issue, Project, Workspace
from plane.utils import initiatives


def _data(request):
    return request.data if isinstance(request.data, dict) else {}


def _error(exc):
    return Response({"error": exc.message}, status=exc.status_code)


def _initiative(slug, initiative_id):
    return Initiative.objects.filter(workspace__slug=slug, pk=initiative_id).first()


def _not_found():
    return Response({"error": "Initiative not found"}, status=status.HTTP_404_NOT_FOUND)


class InitiativeListCreateAPIEndpoint(BaseAPIView):
    permission_classes = [WorkspaceEntityPermission]
    model = Initiative

    def get(self, request, slug):
        rows = Initiative.objects.filter(workspace__slug=slug).select_related("lead")
        return Response({"results": [initiatives.payload(row) for row in rows]})

    def post(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        try:
            initiative = initiatives.create(workspace, _data(request))
        except initiatives.InitiativeError as exc:
            return _error(exc)
        return Response(initiatives.payload(initiative), status=status.HTTP_201_CREATED)


class InitiativeDetailAPIEndpoint(BaseAPIView):
    permission_classes = [WorkspaceEntityPermission]
    model = Initiative

    def get(self, request, slug, initiative_id):
        initiative = _initiative(slug, initiative_id)
        return Response(initiatives.payload(initiative)) if initiative else _not_found()

    def patch(self, request, slug, initiative_id):
        initiative = _initiative(slug, initiative_id)
        if not initiative:
            return _not_found()
        try:
            return Response(initiatives.payload(initiatives.update(initiative, _data(request))))
        except initiatives.InitiativeError as exc:
            return _error(exc)

    def delete(self, request, slug, initiative_id):
        initiative = _initiative(slug, initiative_id)
        if not initiative:
            return _not_found()
        initiatives.delete(initiative)
        return Response(status=status.HTTP_204_NO_CONTENT)


class InitiativeProjectAPIEndpoint(BaseAPIView):
    permission_classes = [WorkspaceEntityPermission]
    model = Project

    def get(self, request, slug, initiative_id):
        initiative = _initiative(slug, initiative_id)
        if not initiative:
            return _not_found()
        projects = Project.objects.filter(
            pk__in=initiative.project_links.values_list("project_id", flat=True)
        ).order_by("name")
        return self.paginate(
            request=request,
            queryset=projects,
            on_results=lambda rows: ProjectSerializer(rows, many=True).data,
        )

    def post(self, request, slug, initiative_id):
        initiative = _initiative(slug, initiative_id)
        if not initiative:
            return _not_found()
        try:
            projects = initiatives.add_projects(initiative, _data(request))
        except initiatives.InitiativeError as exc:
            return _error(exc)
        return Response(ProjectSerializer(projects, many=True).data, status=status.HTTP_201_CREATED)

    def delete(self, request, slug, initiative_id):
        initiative = _initiative(slug, initiative_id)
        if not initiative:
            return _not_found()
        try:
            initiatives.remove_projects(initiative, _data(request))
        except initiatives.InitiativeError as exc:
            return _error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class InitiativeWorkItemAPIEndpoint(BaseAPIView):
    """Work items linked to an initiative; /epics is the SDK's older spelling (epic_ids)."""

    permission_classes = [WorkspaceEntityPermission]
    model = Issue

    def get(self, request, slug, initiative_id):
        initiative = _initiative(slug, initiative_id)
        if not initiative:
            return _not_found()
        issues = Issue.issue_objects.filter(
            pk__in=initiative.work_item_links.values_list("issue_id", flat=True)
        ).order_by("created_at")
        return self.paginate(
            request=request,
            queryset=issues,
            on_results=lambda rows: IssueSerializer(rows, many=True).data,
        )

    def post(self, request, slug, initiative_id):
        initiative = _initiative(slug, initiative_id)
        if not initiative:
            return _not_found()
        try:
            issues = initiatives.add_work_items(initiative, _data(request))
        except initiatives.InitiativeError as exc:
            return _error(exc)
        return Response(IssueSerializer(issues, many=True).data, status=status.HTTP_201_CREATED)

    def delete(self, request, slug, initiative_id):
        initiative = _initiative(slug, initiative_id)
        if not initiative:
            return _not_found()
        try:
            initiatives.remove_work_items(initiative, _data(request))
        except initiatives.InitiativeError as exc:
            return _error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)
