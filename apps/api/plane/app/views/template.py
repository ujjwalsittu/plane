# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Session-authenticated (web app) template endpoints: one list across kinds and scopes, a detail
whose PATCH replaces template_data (the web sends the whole body), and "use"."""

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.api.views import template as api
from plane.api.views.base import BaseAPIView
from plane.app.permissions import WorkspaceEntityPermission
from plane.authentication.session import BaseSessionAuthentication
from plane.db.models import Project, Template, Workspace
from plane.utils import templates


class _Session:
    authentication_classes = [BaseSessionAuthentication]

    def get_throttles(self):
        return []


class TemplateListEndpoint(_Session, BaseAPIView):
    model = Template
    permission_classes = [WorkspaceEntityPermission]

    def get(self, request, slug):
        workspace_id = Workspace.objects.filter(slug=slug).values_list("id", flat=True).first()
        kind = request.GET.get("kind") or None
        rows = templates.visible_templates(
            workspace_id, request.user, kind=kind, project_id=request.GET.get("project_id") or None
        )
        return Response([templates.template_payload(row) for row in rows.order_by("kind", "name")])

    def post(self, request, slug):
        workspace_id = Workspace.objects.filter(slug=slug).values_list("id", flat=True).first()
        data = api._data(request)
        project_id = data.get("project_id") or None
        if (
            project_id
            and not Project.objects.filter(workspace_id=workspace_id, pk=project_id, archived_at__isnull=True).exists()
        ):
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)
        if not templates.can_write(project_id, request.user, workspace_id):
            return api._forbidden()
        try:
            template = templates.save_template(workspace_id, data, project_id=project_id)
        except templates.TemplateError as exc:
            return api._error(exc)
        return Response(templates.template_payload(template), status=status.HTTP_201_CREATED)


class TemplateEndpoint(_Session, BaseAPIView):
    model = Template
    permission_classes = [WorkspaceEntityPermission]

    def _get(self, request, slug, template_id):
        workspace_id = Workspace.objects.filter(slug=slug).values_list("id", flat=True).first()
        return templates.visible_templates(workspace_id, request.user).filter(pk=template_id).first()

    def get(self, request, slug, template_id):
        template = self._get(request, slug, template_id)
        return Response(templates.template_payload(template)) if template else api._missing()

    def patch(self, request, slug, template_id):
        template = self._get(request, slug, template_id)
        if template is None:
            return api._missing()
        if not templates.can_write(template, request.user, template.workspace_id):
            return api._forbidden()
        try:
            template = templates.save_template(
                template.workspace_id, api._data(request), template=template, replace_data=True
            )
        except templates.TemplateError as exc:
            return api._error(exc)
        return Response(templates.template_payload(template))

    def delete(self, request, slug, template_id):
        template = self._get(request, slug, template_id)
        if template is None:
            return api._missing()
        if not templates.can_write(template, request.user, template.workspace_id):
            return api._forbidden()
        template.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TemplateUseEndpoint(_Session, api.TemplateUseAPIEndpoint):
    pass
