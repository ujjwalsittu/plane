# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Custom work item properties for the SDK/MCP: definitions (workspace, project and type scoped),
options, type links and per-work-item values."""

# Django imports
from django.db.models import Q

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.api.views.base import BaseAPIView
from plane.app.permissions import ProjectEntityPermission, WorkspaceEntityPermission
from plane.db.models import Issue, IssueProperty, IssueTypeProperty, Project, Workspace
from plane.utils.issue_properties import (
    PropertyError,
    attach_to_type,
    create_option,
    create_property,
    option_payload,
    properties_queryset,
    property_payload,
    resolve_issue_type,
    set_values,
    type_property_ids,
    update_option,
    update_property,
    values_of,
    values_response,
)


def _data(request):
    return request.data if isinstance(request.data, dict) else {}


def _error(exc):
    return Response({exc.field: exc.message, "error": exc.message}, status=exc.status_code)


def _not_found(what="Property"):
    return Response({"error": f"{what} not found"}, status=status.HTTP_404_NOT_FOUND)


def _workspace_id(slug):
    return Workspace.objects.only("id").get(slug=slug).id


def _project_scope(slug, project_id):
    """Properties visible in a project: its own and the workspace's."""
    return properties_queryset(slug).filter(Q(project_id=project_id) | Q(project_id__isnull=True))


class _Base(BaseAPIView):
    model = IssueProperty

    def handle_exception(self, exc):
        if isinstance(exc, PropertyError):
            return _error(exc)
        return super().handle_exception(exc)


# --- workspace scope ------------------------------------------------------------------------------


class WorkspacePropertyListCreateAPIEndpoint(_Base):
    permission_classes = [WorkspaceEntityPermission]

    def get(self, request, slug):
        return Response([property_payload(p) for p in properties_queryset(slug)], status=status.HTTP_200_OK)

    def post(self, request, slug):
        prop = create_property(_workspace_id(slug), _data(request))
        return Response(property_payload(prop), status=status.HTTP_201_CREATED)


class WorkspacePropertyDetailAPIEndpoint(_Base):
    permission_classes = [WorkspaceEntityPermission]

    def _get(self, slug, property_id):
        return properties_queryset(slug).filter(pk=property_id).first()

    def get(self, request, slug, property_id):
        prop = self._get(slug, property_id)
        return Response(property_payload(prop), status=status.HTTP_200_OK) if prop else _not_found()

    def patch(self, request, slug, property_id):
        prop = self._get(slug, property_id)
        if not prop:
            return _not_found()
        return Response(property_payload(update_property(prop, _data(request))), status=status.HTTP_200_OK)

    def delete(self, request, slug, property_id):
        prop = self._get(slug, property_id)
        if not prop:
            return _not_found()
        prop.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class _OptionsMixin:
    """Options of a property; subclasses resolve the property for their scope."""

    def _property(self, request, slug, property_id, project_id=None):
        raise NotImplementedError

    def _list(self, request, slug, property_id, project_id=None):
        prop = self._property(request, slug, property_id, project_id)
        if not prop:
            return _not_found()
        return Response([option_payload(o) for o in prop.options.all()], status=status.HTTP_200_OK)

    def _create(self, request, slug, property_id, project_id=None):
        prop = self._property(request, slug, property_id, project_id)
        if not prop:
            return _not_found()
        if prop.property_type != "OPTION":
            return Response({"error": "Only OPTION properties have options"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(option_payload(create_option(prop, _data(request))), status=status.HTTP_201_CREATED)

    def _option(self, request, slug, property_id, option_id, project_id=None):
        prop = self._property(request, slug, property_id, project_id)
        return prop.options.filter(pk=option_id).first() if prop else None


class WorkspaceOptionListCreateAPIEndpoint(_OptionsMixin, _Base):
    permission_classes = [WorkspaceEntityPermission]

    def _property(self, request, slug, property_id, project_id=None):
        return properties_queryset(slug).filter(pk=property_id).first()

    def get(self, request, slug, property_id):
        return self._list(request, slug, property_id)

    def post(self, request, slug, property_id):
        return self._create(request, slug, property_id)


class WorkspaceOptionDetailAPIEndpoint(_OptionsMixin, _Base):
    permission_classes = [WorkspaceEntityPermission]

    def _property(self, request, slug, property_id, project_id=None):
        return properties_queryset(slug).filter(pk=property_id).first()

    def get(self, request, slug, property_id, option_id):
        option = self._option(request, slug, property_id, option_id)
        return Response(option_payload(option), status=status.HTTP_200_OK) if option else _not_found("Option")

    def patch(self, request, slug, property_id, option_id):
        option = self._option(request, slug, property_id, option_id)
        if not option:
            return _not_found("Option")
        return Response(option_payload(update_option(option, _data(request))), status=status.HTTP_200_OK)

    def delete(self, request, slug, property_id, option_id):
        option = self._option(request, slug, property_id, option_id)
        if not option:
            return _not_found("Option")
        option.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkspaceTypePropertyLinksAPIEndpoint(_Base):
    """Workspace properties linked to a work item type (bare ids, as the SDK expects)."""

    permission_classes = [WorkspaceEntityPermission]

    def get(self, request, slug, type_id):
        issue_type = resolve_issue_type(_workspace_id(slug), type_id)
        return Response(type_property_ids(issue_type), status=status.HTTP_200_OK)

    def post(self, request, slug, type_id):
        workspace_id = _workspace_id(slug)
        issue_type = resolve_issue_type(workspace_id, type_id)
        linked = attach_to_type(issue_type, _data(request).get("properties"), workspace_id)
        return Response({"properties": linked}, status=status.HTTP_201_CREATED)


class WorkspaceTypePropertyUnlinkAPIEndpoint(_Base):
    permission_classes = [WorkspaceEntityPermission]

    def delete(self, request, slug, type_id, property_id):
        issue_type = resolve_issue_type(_workspace_id(slug), type_id)
        IssueTypeProperty.objects.filter(issue_type=issue_type, property_id=property_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- project scope --------------------------------------------------------------------------------


class ProjectPropertyListCreateAPIEndpoint(_Base):
    permission_classes = [ProjectEntityPermission]

    def get(self, request, slug, project_id):
        return Response([property_payload(p) for p in _project_scope(slug, project_id)], status=status.HTTP_200_OK)

    def post(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        prop = create_property(project.workspace_id, _data(request), project_id=project.id)
        return Response(property_payload(prop), status=status.HTTP_201_CREATED)


class ProjectPropertyDetailAPIEndpoint(_Base):
    permission_classes = [ProjectEntityPermission]

    def _get(self, slug, project_id, property_id):
        return _project_scope(slug, project_id).filter(pk=property_id).first()

    def get(self, request, slug, project_id, property_id):
        prop = self._get(slug, project_id, property_id)
        return Response(property_payload(prop), status=status.HTTP_200_OK) if prop else _not_found()

    def patch(self, request, slug, project_id, property_id):
        prop = self._get(slug, project_id, property_id)
        if not prop:
            return _not_found()
        return Response(property_payload(update_property(prop, _data(request))), status=status.HTTP_200_OK)

    def delete(self, request, slug, project_id, property_id):
        prop = self._get(slug, project_id, property_id)
        if not prop or prop.project_id is None:
            # Workspace properties are deleted at the workspace endpoint.
            return _not_found()
        prop.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TypePropertyListCreateAPIEndpoint(_Base):
    """Properties of a work item type within a project."""

    permission_classes = [ProjectEntityPermission]

    def get(self, request, slug, project_id, type_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        issue_type = resolve_issue_type(project.workspace_id, type_id)
        ids = type_property_ids(issue_type, project_id=project.id)
        props = _project_scope(slug, project_id).filter(pk__in=ids)
        return Response([property_payload(p, issue_type.id) for p in props], status=status.HTTP_200_OK)

    def post(self, request, slug, project_id, type_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        issue_type = resolve_issue_type(project.workspace_id, type_id)
        prop = create_property(project.workspace_id, _data(request), project_id=project.id, issue_type=issue_type)
        return Response(property_payload(prop, issue_type.id), status=status.HTTP_201_CREATED)


class TypePropertyDetailAPIEndpoint(ProjectPropertyDetailAPIEndpoint):
    def get(self, request, slug, project_id, type_id, work_item_property_id):
        return super().get(request, slug, project_id, work_item_property_id)

    def patch(self, request, slug, project_id, type_id, work_item_property_id):
        return super().patch(request, slug, project_id, work_item_property_id)

    def delete(self, request, slug, project_id, type_id, work_item_property_id):
        return super().delete(request, slug, project_id, work_item_property_id)


class ProjectTypePropertyLinksAPIEndpoint(_Base):
    permission_classes = [ProjectEntityPermission]

    def post(self, request, slug, project_id, type_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        issue_type = resolve_issue_type(project.workspace_id, type_id)
        linked = attach_to_type(
            issue_type, _data(request).get("properties"), project.workspace_id, project_id=project.id
        )
        return Response({"properties": linked}, status=status.HTTP_201_CREATED)


class ProjectTypePropertyUnlinkAPIEndpoint(_Base):
    permission_classes = [ProjectEntityPermission]

    def delete(self, request, slug, project_id, type_id, property_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        issue_type = resolve_issue_type(project.workspace_id, type_id)
        IssueTypeProperty.objects.filter(issue_type=issue_type, property_id=property_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectOptionListCreateAPIEndpoint(_OptionsMixin, _Base):
    permission_classes = [ProjectEntityPermission]

    def _property(self, request, slug, property_id, project_id=None):
        return _project_scope(slug, project_id).filter(pk=property_id).first()

    def get(self, request, slug, project_id, property_id):
        return self._list(request, slug, property_id, project_id)

    def post(self, request, slug, project_id, property_id):
        return self._create(request, slug, property_id, project_id)


class ProjectOptionDetailAPIEndpoint(_OptionsMixin, _Base):
    permission_classes = [ProjectEntityPermission]

    def _property(self, request, slug, property_id, project_id=None):
        return _project_scope(slug, project_id).filter(pk=property_id).first()

    def get(self, request, slug, project_id, property_id, option_id):
        option = self._option(request, slug, property_id, option_id, project_id)
        return Response(option_payload(option), status=status.HTTP_200_OK) if option else _not_found("Option")

    def patch(self, request, slug, project_id, property_id, option_id):
        option = self._option(request, slug, property_id, option_id, project_id)
        if not option:
            return _not_found("Option")
        return Response(option_payload(update_option(option, _data(request))), status=status.HTTP_200_OK)

    def delete(self, request, slug, project_id, property_id, option_id):
        option = self._option(request, slug, property_id, option_id, project_id)
        if not option:
            return _not_found("Option")
        option.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- values ---------------------------------------------------------------------------------------


class WorkItemPropertyValueAPIEndpoint(_Base):
    permission_classes = [ProjectEntityPermission]

    def _resolve(self, slug, project_id, issue_id, property_id):
        issue = Issue.issue_objects.filter(workspace__slug=slug, project_id=project_id, pk=issue_id).first()
        prop = _project_scope(slug, project_id).filter(pk=property_id).first()
        return issue, prop

    def get(self, request, slug, project_id, issue_id, property_id):
        issue, prop = self._resolve(slug, project_id, issue_id, property_id)
        if not issue or not prop:
            return _not_found("Work item or property")
        payload = values_response(prop, list(values_of(issue, prop)))
        if payload is None:
            return Response({"error": "No value set"}, status=status.HTTP_404_NOT_FOUND)
        return Response(payload, status=status.HTTP_200_OK)

    def post(self, request, slug, project_id, issue_id, property_id):
        issue, prop = self._resolve(slug, project_id, issue_id, property_id)
        if not issue or not prop:
            return _not_found("Work item or property")
        data = _data(request)
        if "value" not in data:
            return Response({"value": "value is required", "error": "value is required"}, status=400)
        rows = set_values(issue, prop, data["value"], data.get("external_source"), data.get("external_id"))
        return Response(values_response(prop, rows), status=status.HTTP_201_CREATED)

    def patch(self, request, slug, project_id, issue_id, property_id):
        response = self.post(request, slug, project_id, issue_id, property_id)
        if response.status_code == status.HTTP_201_CREATED:
            response.status_code = status.HTTP_200_OK
        return response

    def delete(self, request, slug, project_id, issue_id, property_id):
        issue, prop = self._resolve(slug, project_id, issue_id, property_id)
        if not issue or not prop:
            return _not_found("Work item or property")
        values_of(issue, prop).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
