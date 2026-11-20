# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Work item, page and project templates for the SDK/MCP.

Workspace routes: workspaces/<slug>/{workitems,pages,projects}/templates/. Listing a workitem or
page kind there is the wider view: the workspace's own templates plus those of the caller's
projects, told apart by a non-null project. Project routes:
workspaces/<slug>/projects/<project_id>/{workitems,pages}/templates/ hold that project's alone.
Lists are plain JSON arrays, which is what the SDK reads."""

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.api.views.base import BaseAPIView
from plane.app.permissions import ProjectEntityPermission, WorkspaceEntityPermission
from plane.db.models import Project, Template, Workspace
from plane.utils import templates
from plane.utils.host import base_host


def _data(request):
    return request.data if isinstance(request.data, dict) else {}


def _error(exc):
    return Response({"error": exc.message, exc.field: exc.message}, status=exc.status_code)


def _missing():
    return Response({"error": "Template not found"}, status=status.HTTP_404_NOT_FOUND)


def _forbidden():
    return Response({"error": "You don't have permission to change this template"}, status=status.HTTP_403_FORBIDDEN)


def _workspace_id(slug):
    return Workspace.objects.filter(slug=slug).values_list("id", flat=True).first()


class _Templates(BaseAPIView):
    """List and create, at the workspace (project_id None) or in one project."""

    model = Template
    kind = None

    def _list(self, request, slug, project_id=None):
        workspace_id = _workspace_id(slug)
        rows = templates.visible_templates(
            workspace_id,
            request.user,
            kind=self.kind,
            project_id=project_id,
            include_projects=self.kind != Template.PROJECT,
        )
        return Response([templates.template_payload(row) for row in rows.order_by("name", "-created_at")])

    def _create(self, request, slug, project_id=None):
        workspace_id = _workspace_id(slug)
        if not templates.can_write(project_id, request.user, workspace_id):
            return _forbidden()
        try:
            template = templates.save_template(workspace_id, _data(request), kind=self.kind, project_id=project_id)
        except templates.TemplateError as exc:
            return _error(exc)
        return Response(templates.template_payload(template), status=status.HTTP_201_CREATED)


class _Template(BaseAPIView):
    model = Template
    kind = None

    def _get_template(self, slug, template_id, project_id=None):
        rows = Template.objects.filter(workspace__slug=slug, kind=self.kind, pk=template_id)
        rows = rows.filter(project_id=project_id) if project_id else rows.filter(project__isnull=True)
        return rows.first()

    def _retrieve(self, request, slug, template_id, project_id=None):
        template = self._get_template(slug, template_id, project_id)
        return Response(templates.template_payload(template)) if template else _missing()

    def _update(self, request, slug, template_id, project_id=None):
        template = self._get_template(slug, template_id, project_id)
        if template is None:
            return _missing()
        if not templates.can_write(template, request.user, template.workspace_id):
            return _forbidden()
        try:
            template = templates.save_template(template.workspace_id, _data(request), template=template)
        except templates.TemplateError as exc:
            return _error(exc)
        return Response(templates.template_payload(template))

    def _destroy(self, request, slug, template_id, project_id=None):
        template = self._get_template(slug, template_id, project_id)
        if template is None:
            return _missing()
        if not templates.can_write(template, request.user, template.workspace_id):
            return _forbidden()
        template.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _workspace_views(kind, label):
    class ListCreate(_Templates):
        permission_classes = [WorkspaceEntityPermission]

        def get(self, request, slug):
            return self._list(request, slug)

        def post(self, request, slug):
            return self._create(request, slug)

    class Detail(_Template):
        permission_classes = [WorkspaceEntityPermission]

        def get(self, request, slug, template_id):
            return self._retrieve(request, slug, template_id)

        def patch(self, request, slug, template_id):
            return self._update(request, slug, template_id)

        def delete(self, request, slug, template_id):
            return self._destroy(request, slug, template_id)

    ListCreate.kind = Detail.kind = kind
    ListCreate.__name__ = ListCreate.__qualname__ = f"Workspace{label}TemplateListCreateAPIEndpoint"
    Detail.__name__ = Detail.__qualname__ = f"Workspace{label}TemplateDetailAPIEndpoint"
    return ListCreate, Detail


def _project_views(kind, label):
    def _project_ok(slug, project_id):
        return Project.objects.filter(workspace__slug=slug, pk=project_id, archived_at__isnull=True).exists()

    class ListCreate(_Templates):
        permission_classes = [ProjectEntityPermission]

        def get(self, request, slug, project_id):
            if not _project_ok(slug, project_id):
                return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)
            return self._list(request, slug, project_id)

        def post(self, request, slug, project_id):
            if not _project_ok(slug, project_id):
                return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)
            return self._create(request, slug, project_id)

    class Detail(_Template):
        permission_classes = [ProjectEntityPermission]

        def get(self, request, slug, project_id, template_id):
            return self._retrieve(request, slug, template_id, project_id)

        def patch(self, request, slug, project_id, template_id):
            return self._update(request, slug, template_id, project_id)

        def delete(self, request, slug, project_id, template_id):
            return self._destroy(request, slug, template_id, project_id)

    ListCreate.kind = Detail.kind = kind
    ListCreate.__name__ = ListCreate.__qualname__ = f"Project{label}TemplateListCreateAPIEndpoint"
    Detail.__name__ = Detail.__qualname__ = f"Project{label}TemplateDetailAPIEndpoint"
    return ListCreate, Detail


WorkspaceWorkItemTemplateListCreateAPIEndpoint, WorkspaceWorkItemTemplateDetailAPIEndpoint = _workspace_views(
    Template.WORK_ITEM, "WorkItem"
)
WorkspacePageTemplateListCreateAPIEndpoint, WorkspacePageTemplateDetailAPIEndpoint = _workspace_views(
    Template.PAGE, "Page"
)
WorkspaceProjectTemplateListCreateAPIEndpoint, WorkspaceProjectTemplateDetailAPIEndpoint = _workspace_views(
    Template.PROJECT, "Project"
)
ProjectWorkItemTemplateListCreateAPIEndpoint, ProjectWorkItemTemplateDetailAPIEndpoint = _project_views(
    Template.WORK_ITEM, "WorkItem"
)
ProjectPageTemplateListCreateAPIEndpoint, ProjectPageTemplateDetailAPIEndpoint = _project_views(Template.PAGE, "Page")


class TemplateUseAPIEndpoint(BaseAPIView):
    """POST workspaces/<slug>/templates/<template_id>/use/ creates a work item, page or project."""

    model = Template
    permission_classes = [WorkspaceEntityPermission]

    def post(self, request, slug, template_id):
        template = Template.objects.filter(workspace__slug=slug, pk=template_id).first()
        if template is None:
            return _missing()
        try:
            result = templates.use_template(
                template, request.user, _data(request), origin=base_host(request=request, is_app=True)
            )
        except templates.TemplateError as exc:
            return _error(exc)
        return Response(result, status=status.HTTP_201_CREATED)
