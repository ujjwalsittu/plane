# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Custom work item properties for the web app: manage a project's properties and edit values."""

# Django imports
from django.db.models import Q

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.db.models import Issue, Project
from plane.utils.issue_properties import (
    PropertyError,
    create_option,
    create_property,
    issue_values_payload,
    option_payload,
    properties_queryset,
    property_payload,
    resolve_issue_type,
    set_values,
    update_option,
    update_property,
    values_of,
)


def _data(request):
    return request.data if isinstance(request.data, dict) else {}


def _error(exc):
    return Response({exc.field: exc.message, "error": exc.message}, status=exc.status_code)


def _scope(slug, project_id):
    return properties_queryset(slug).filter(Q(project_id=project_id) | Q(project_id__isnull=True))


class IssuePropertyEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        return Response([property_payload(p) for p in _scope(slug, project_id)], status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        data = _data(request)
        try:
            issue_type = (
                resolve_issue_type(project.workspace_id, data["issue_type_id"]) if data.get("issue_type_id") else None
            )
            prop = create_property(project.workspace_id, data, project_id=project.id, issue_type=issue_type)
        except PropertyError as exc:
            return _error(exc)
        return Response(property_payload(prop), status=status.HTTP_201_CREATED)


class IssuePropertyDetailEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN])
    def patch(self, request, slug, project_id, pk):
        prop = _scope(slug, project_id).filter(pk=pk, project_id=project_id).first()
        if not prop:
            return Response({"error": "Property not found"}, status=status.HTTP_404_NOT_FOUND)
        try:
            return Response(property_payload(update_property(prop, _data(request))), status=status.HTTP_200_OK)
        except PropertyError as exc:
            return _error(exc)

    @allow_permission([ROLE.ADMIN])
    def delete(self, request, slug, project_id, pk):
        prop = _scope(slug, project_id).filter(pk=pk, project_id=project_id).first()
        if not prop:
            return Response({"error": "Property not found"}, status=status.HTTP_404_NOT_FOUND)
        prop.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class IssuePropertyOptionEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id, property_id):
        prop = _scope(slug, project_id).filter(pk=property_id, project_id=project_id).first()
        if not prop or prop.property_type != "OPTION":
            return Response({"error": "Option property not found"}, status=status.HTTP_404_NOT_FOUND)
        try:
            return Response(option_payload(create_option(prop, _data(request))), status=status.HTTP_201_CREATED)
        except PropertyError as exc:
            return _error(exc)


class IssuePropertyOptionDetailEndpoint(BaseAPIView):
    def _option(self, slug, project_id, property_id, pk):
        prop = _scope(slug, project_id).filter(pk=property_id, project_id=project_id).first()
        return prop.options.filter(pk=pk).first() if prop else None

    @allow_permission([ROLE.ADMIN])
    def patch(self, request, slug, project_id, property_id, pk):
        option = self._option(slug, project_id, property_id, pk)
        if not option:
            return Response({"error": "Option not found"}, status=status.HTTP_404_NOT_FOUND)
        try:
            return Response(option_payload(update_option(option, _data(request))), status=status.HTTP_200_OK)
        except PropertyError as exc:
            return _error(exc)

    @allow_permission([ROLE.ADMIN])
    def delete(self, request, slug, project_id, property_id, pk):
        option = self._option(slug, project_id, property_id, pk)
        if not option:
            return Response({"error": "Option not found"}, status=status.HTTP_404_NOT_FOUND)
        option.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class IssuePropertyValuesEndpoint(BaseAPIView):
    """Every property that applies to a work item with its values; PUT sets one property."""

    def _issue(self, slug, project_id, issue_id):
        return Issue.issue_objects.filter(workspace__slug=slug, project_id=project_id, pk=issue_id).first()

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, issue_id):
        issue = self._issue(slug, project_id, issue_id)
        if not issue:
            return Response({"error": "Work item not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(issue_values_payload(issue), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def put(self, request, slug, project_id, issue_id):
        issue = self._issue(slug, project_id, issue_id)
        data = _data(request)
        prop = _scope(slug, project_id).filter(pk=data.get("property_id")).first()
        if not issue or not prop:
            return Response({"error": "Work item or property not found"}, status=status.HTTP_404_NOT_FOUND)
        value = data.get("value")
        try:
            if value is None or value == [] or value == "":
                values_of(issue, prop).delete()
            else:
                set_values(issue, prop, value)
        except PropertyError as exc:
            return _error(exc)
        return Response(issue_values_payload(issue), status=status.HTTP_200_OK)
