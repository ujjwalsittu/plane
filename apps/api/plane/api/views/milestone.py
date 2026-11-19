# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""External API (``/api/v1``) for milestones, work item types and feature
flags, in the shapes the Plane SDK and MCP server use."""

# Third party imports
from rest_framework import status
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.response import Response

# Module imports
from plane.api.views.base import BaseAPIView
from plane.app.permissions import (
    ProjectAdminPermission,
    ProjectEntityPermission,
    WorkspaceEntityPermission,
)
from plane.app.serializers import IssueTypeSerializer, MilestoneSerializer
from plane.db.models import (
    Issue,
    IssueType,
    Milestone,
    Project,
    ProjectIssueType,
    Workspace,
    WorkspaceMember,
)
from plane.utils.host import base_host
from plane.utils.project_overview import (
    OverviewError,
    create_tag,
    overview_payload,
    tag_payload,
    update_overview,
    workspace_tags_payload,
)
from plane.utils.milestone import (
    default_epic_flag,
    enable_milestones,
    link_issue_type,
    milestone_queryset,
    project_issue_types,
    set_issues_milestone,
    unlink_issue_type,
)

ADMIN = 20


class ProjectReadMemberWriteAdmin(BasePermission):
    """Members read; project admins write."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return ProjectEntityPermission().has_permission(request, view)
        return ProjectAdminPermission().has_permission(request, view)


class WorkspaceReadMemberWriteAdmin(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return WorkspaceEntityPermission().has_permission(request, view)
        if request.user.is_anonymous:
            return False
        return WorkspaceMember.objects.filter(
            member=request.user, workspace__slug=view.workspace_slug, role=ADMIN, is_active=True
        ).exists()


def _issue_ids(request):
    issues = request.data.get("issues") if isinstance(request.data, dict) else None
    if not isinstance(issues, list) or not issues:
        return None
    return [str(issue) for issue in issues]


def _external_conflict(queryset, request, exclude_pk=None):
    source = request.data.get("external_source")
    external_id = request.data.get("external_id")
    if not source or not external_id:
        return None
    existing = queryset.filter(external_source=source, external_id=external_id)
    if exclude_pk:
        existing = existing.exclude(pk=exclude_pk)
    existing = existing.first()
    if existing is None:
        return None
    return Response(
        {"error": "An item with this external id already exists", "id": str(existing.id)},
        status=status.HTTP_409_CONFLICT,
    )


# --- milestones -------------------------------------------------------------


class MilestoneListCreateAPIEndpoint(BaseAPIView):
    permission_classes = [ProjectEntityPermission]
    model = Milestone

    def get(self, request, slug, project_id):
        queryset = milestone_queryset(slug, project_id)
        external_id = request.GET.get("external_id")
        external_source = request.GET.get("external_source")
        if external_id and external_source:
            queryset = queryset.filter(external_id=external_id, external_source=external_source)
        return self.paginate(
            request=request,
            queryset=queryset,
            on_results=lambda milestones: MilestoneSerializer(milestones, many=True).data,
        )

    def post(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        conflict = _external_conflict(Milestone.objects.filter(project=project), request)
        if conflict:
            return conflict
        serializer = MilestoneSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        milestone = serializer.save(project=project, workspace_id=project.workspace_id)
        enable_milestones(project)
        return Response(
            MilestoneSerializer(milestone_queryset(slug, project_id).get(pk=milestone.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class MilestoneDetailAPIEndpoint(BaseAPIView):
    permission_classes = [ProjectEntityPermission]
    model = Milestone

    def get(self, request, slug, project_id, milestone_id):
        milestone = milestone_queryset(slug, project_id).get(pk=milestone_id)
        return Response(MilestoneSerializer(milestone).data, status=status.HTTP_200_OK)

    def patch(self, request, slug, project_id, milestone_id):
        milestone = Milestone.objects.get(pk=milestone_id, project_id=project_id, workspace__slug=slug)
        conflict = _external_conflict(Milestone.objects.filter(project_id=project_id), request, exclude_pk=milestone.pk)
        if conflict:
            return conflict
        serializer = MilestoneSerializer(milestone, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(
            MilestoneSerializer(milestone_queryset(slug, project_id).get(pk=milestone_id)).data,
            status=status.HTTP_200_OK,
        )

    def delete(self, request, slug, project_id, milestone_id):
        milestone = Milestone.objects.get(pk=milestone_id, project_id=project_id, workspace__slug=slug)
        issue_ids = list(Issue.issue_objects.filter(milestone=milestone).values_list("id", flat=True))
        set_issues_milestone(request, slug, project_id, issue_ids, None, base_host(request=request, is_app=True))
        Issue.all_objects.filter(milestone=milestone).update(milestone=None)
        milestone.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MilestoneWorkItemAPIEndpoint(BaseAPIView):
    """Work items of a milestone: list, add (``{"issues": [...]}``), remove."""

    permission_classes = [ProjectEntityPermission]
    model = Milestone

    def _milestone(self, slug, project_id, milestone_id):
        return Milestone.objects.get(pk=milestone_id, project_id=project_id, workspace__slug=slug)

    def get(self, request, slug, project_id, milestone_id):
        milestone = self._milestone(slug, project_id, milestone_id)
        queryset = Issue.issue_objects.filter(milestone=milestone).order_by("sequence_id")
        return self.paginate(
            request=request,
            queryset=queryset,
            on_results=lambda issues: [
                {"id": str(issue.id), "issue": str(issue.id), "milestone": str(milestone.id)} for issue in issues
            ],
        )

    def post(self, request, slug, project_id, milestone_id):
        milestone = self._milestone(slug, project_id, milestone_id)
        issue_ids = _issue_ids(request)
        if issue_ids is None:
            return Response({"error": "issues must be a non-empty list"}, status=status.HTTP_400_BAD_REQUEST)
        found = {
            str(pk)
            for pk in Issue.issue_objects.filter(
                workspace__slug=slug, project_id=project_id, pk__in=issue_ids
            ).values_list("id", flat=True)
        }
        missing = sorted(set(issue_ids) - found)
        if missing:
            return Response(
                {"error": "Some work items were not found in this project", "issues": missing},
                status=status.HTTP_404_NOT_FOUND,
            )
        set_issues_milestone(request, slug, project_id, issue_ids, milestone, base_host(request=request, is_app=True))
        return Response(status=status.HTTP_204_NO_CONTENT)

    def delete(self, request, slug, project_id, milestone_id):
        milestone = self._milestone(slug, project_id, milestone_id)
        issue_ids = _issue_ids(request)
        if issue_ids is None:
            return Response({"error": "issues must be a non-empty list"}, status=status.HTTP_400_BAD_REQUEST)
        in_milestone = Issue.issue_objects.filter(milestone=milestone, pk__in=issue_ids).values_list("id", flat=True)
        set_issues_milestone(
            request, slug, project_id, list(in_milestone), None, base_host(request=request, is_app=True)
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- work item types ---------------------------------------------------------


def _type_payload(issue_type):
    data = IssueTypeSerializer(issue_type).data
    data["project_ids"] = [
        str(pk) for pk in ProjectIssueType.objects.filter(issue_type=issue_type).values_list("project_id", flat=True)
    ]
    return data


def _save_type(serializer, project_ids_scope, **save_kwargs):
    """Save; keep ``is_default`` unique per project."""
    issue_type = serializer.save(**save_kwargs)
    if issue_type.is_default:
        IssueType.objects.filter(
            project_issue_types__project_id__in=project_ids_scope,
            project_issue_types__deleted_at__isnull=True,
            is_default=True,
        ).exclude(pk=issue_type.pk).update(is_default=False)
    return issue_type


class ProjectWorkItemTypeListCreateAPIEndpoint(BaseAPIView):
    permission_classes = [ProjectReadMemberWriteAdmin]
    model = IssueType

    def get(self, request, slug, project_id):
        Project.objects.get(pk=project_id, workspace__slug=slug)
        return Response(
            [_type_payload(t) for t in project_issue_types(slug, project_id)],
            status=status.HTTP_200_OK,
        )

    def post(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        serializer = IssueTypeSerializer(data=default_epic_flag(request.data))
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        name = serializer.validated_data["name"]
        existing = project_issue_types(slug, project_id).filter(name__iexact=name).first()
        if existing:
            return Response(
                {"error": f"A work item type named '{name}' already exists in this project", "id": str(existing.id)},
                status=status.HTTP_409_CONFLICT,
            )
        issue_type = _save_type(serializer, [project.id], workspace_id=project.workspace_id)
        link_issue_type(issue_type, project)
        if not project.is_issue_type_enabled:
            project.is_issue_type_enabled = True
            project.save(update_fields=["is_issue_type_enabled"])
        return Response(_type_payload(issue_type), status=status.HTTP_201_CREATED)


class ProjectWorkItemTypeDetailAPIEndpoint(BaseAPIView):
    permission_classes = [ProjectReadMemberWriteAdmin]
    model = IssueType

    def get(self, request, slug, project_id, type_id):
        return Response(_type_payload(project_issue_types(slug, project_id).get(pk=type_id)), status=status.HTTP_200_OK)

    def patch(self, request, slug, project_id, type_id):
        issue_type = project_issue_types(slug, project_id).get(pk=type_id)
        serializer = IssueTypeSerializer(issue_type, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        name = serializer.validated_data.get("name")
        if name and project_issue_types(slug, project_id).filter(name__iexact=name).exclude(pk=type_id).exists():
            return Response(
                {"error": f"A work item type named '{name}' already exists in this project"},
                status=status.HTTP_409_CONFLICT,
            )
        issue_type = _save_type(serializer, [project_id])
        return Response(_type_payload(issue_type), status=status.HTTP_200_OK)

    def delete(self, request, slug, project_id, type_id):
        issue_type = project_issue_types(slug, project_id).get(pk=type_id)
        unlink_issue_type(issue_type, Project.objects.get(pk=project_id, workspace__slug=slug))
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectImportWorkItemTypesAPIEndpoint(BaseAPIView):
    """Link workspace types to a project (``{"work_item_types": [ids]}``)."""

    permission_classes = [ProjectReadMemberWriteAdmin]
    model = IssueType

    def post(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        ids = request.data.get("work_item_types") if isinstance(request.data, dict) else None
        if not isinstance(ids, list) or not ids:
            return Response(
                {"error": "work_item_types must be a non-empty list of work item type ids"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        types = list(IssueType.objects.filter(workspace__slug=slug, pk__in=ids))
        missing = sorted({str(i) for i in ids} - {str(t.id) for t in types})
        if missing:
            return Response(
                {"error": "Some work item types were not found", "work_item_types": missing},
                status=status.HTTP_404_NOT_FOUND,
            )
        for issue_type in types:
            link_issue_type(issue_type, project)
        if not project.is_issue_type_enabled:
            project.is_issue_type_enabled = True
            project.save(update_fields=["is_issue_type_enabled"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkspaceWorkItemTypeListCreateAPIEndpoint(BaseAPIView):
    permission_classes = [WorkspaceReadMemberWriteAdmin]
    model = IssueType

    def get(self, request, slug):
        types = IssueType.objects.filter(workspace__slug=slug).order_by("level", "created_at")
        return Response([_type_payload(t) for t in types], status=status.HTTP_200_OK)

    def post(self, request, slug):
        serializer = IssueTypeSerializer(data=default_epic_flag(request.data))
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        project_ids = request.data.get("project_ids") or []
        projects = list(Project.objects.filter(workspace__slug=slug, pk__in=project_ids))
        if len(projects) != len(set(map(str, project_ids))):
            return Response({"error": "Some projects were not found"}, status=status.HTTP_404_NOT_FOUND)
        workspace = Workspace.objects.get(slug=slug)
        issue_type = _save_type(serializer, [p.id for p in projects], workspace_id=workspace.id)
        for project in projects:
            link_issue_type(issue_type, project)
        return Response(_type_payload(issue_type), status=status.HTTP_201_CREATED)


class WorkspaceWorkItemTypeDetailAPIEndpoint(BaseAPIView):
    permission_classes = [WorkspaceReadMemberWriteAdmin]
    model = IssueType

    def get(self, request, slug, type_id):
        issue_type = IssueType.objects.get(workspace__slug=slug, pk=type_id)
        return Response(_type_payload(issue_type), status=status.HTTP_200_OK)

    def patch(self, request, slug, type_id):
        issue_type = IssueType.objects.get(workspace__slug=slug, pk=type_id)
        serializer = IssueTypeSerializer(issue_type, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        linked = list(ProjectIssueType.objects.filter(issue_type=issue_type).values_list("project_id", flat=True))
        issue_type = _save_type(serializer, linked)
        return Response(_type_payload(issue_type), status=status.HTTP_200_OK)

    def delete(self, request, slug, type_id):
        issue_type = IssueType.objects.get(workspace__slug=slug, pk=type_id)
        for project in Project.objects.filter(
            project_projectissuetype__issue_type=issue_type,
            project_projectissuetype__deleted_at__isnull=True,
        ).distinct():
            unlink_issue_type(issue_type, project)
        if IssueType.objects.filter(pk=type_id).exists():
            issue_type.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- feature flags -----------------------------------------------------------

# SDK feature name -> Project field
PROJECT_FEATURE_FIELDS = {
    "modules": "module_view",
    "cycles": "cycle_view",
    "views": "issue_views_view",
    "pages": "page_view",
    "intakes": "intake_view",
    "work_item_types": "is_issue_type_enabled",
    "milestones": "milestone_view",
}
# Known to the SDK, not available on this edition.
UNSUPPORTED_PROJECT_FEATURES = ("workflows", "parallel_cycles", "project_updates")


def _project_features(project):
    data = {name: bool(getattr(project, field)) for name, field in PROJECT_FEATURE_FIELDS.items()}
    data["epics"] = bool(
        project.is_issue_type_enabled
        and project_issue_types(project.workspace.slug, project.id).filter(is_epic=True).exists()
    )
    for name in UNSUPPORTED_PROJECT_FEATURES:
        data[name] = False
    return data


class ProjectFeatureAPIEndpoint(BaseAPIView):
    permission_classes = [ProjectReadMemberWriteAdmin]
    model = Project

    def get(self, request, slug, project_id):
        project = Project.objects.select_related("workspace").get(pk=project_id, workspace__slug=slug)
        return Response(_project_features(project), status=status.HTTP_200_OK)

    def patch(self, request, slug, project_id):
        project = Project.objects.select_related("workspace").get(pk=project_id, workspace__slug=slug)
        data = request.data if isinstance(request.data, dict) else {}
        unsupported = [name for name in UNSUPPORTED_PROJECT_FEATURES if data.get(name)]
        if unsupported:
            return Response(
                {"error": f"Not available on this Plane edition: {', '.join(unsupported)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        changed = []
        for name, field in PROJECT_FEATURE_FIELDS.items():
            if name in data and data[name] is not None:
                setattr(project, field, bool(data[name]))
                changed.append(field)
        if data.get("epics"):
            # Epics are a work item type; turning them on adds one if missing.
            project.is_issue_type_enabled = True
            changed.append("is_issue_type_enabled")
        if changed:
            project.save(update_fields=sorted(set(changed)))
        if data.get("epics") and not project_issue_types(slug, project_id).filter(is_epic=True).exists():
            epic = IssueType.objects.create(workspace_id=project.workspace_id, name="Epic", is_epic=True, level=1)
            link_issue_type(epic, project)
        return Response(_project_features(project), status=status.HTTP_200_OK)


class WorkspaceFeatureAPIEndpoint(BaseAPIView):
    """Workspace-level catalogues are not available: types, states and labels
    live per project, which is what tells the MCP server to use project scope."""

    permission_classes = [WorkspaceEntityPermission]
    model = Project

    FEATURES = {
        "project_grouping": False,
        "initiatives": True,
        "teams": False,
        "customers": False,
        "wiki": False,
        "pi": False,
        "work_item_types": False,
        "releases": True,
        "states_owned_by_workspace": False,
    }

    def get(self, request, slug):
        return Response(self.FEATURES, status=status.HTTP_200_OK)

    def patch(self, request, slug):
        data = request.data if isinstance(request.data, dict) else {}
        # Initiatives are always on in this fork.
        enabled = [name for name, value in data.items() if value and not self.FEATURES.get(name)]
        if enabled:
            return Response(
                {"error": f"Not available on this Plane edition: {', '.join(enabled)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(self.FEATURES, status=status.HTTP_200_OK)


# --- project overview and tags ---------------------------------------------------


class ProjectOverviewAPIEndpoint(BaseAPIView):
    permission_classes = [ProjectEntityPermission]
    model = Project

    def get(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        return Response(overview_payload(request.user, project), status=status.HTTP_200_OK)

    def patch(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        try:
            update_overview(request.user, project, request.data if isinstance(request.data, dict) else {})
        except OverviewError as exc:
            return Response({exc.field: exc.message, "error": exc.message}, status=status.HTTP_400_BAD_REQUEST)
        return Response(overview_payload(request.user, project), status=status.HTTP_200_OK)


class ProjectTagListCreateAPIEndpoint(BaseAPIView):
    permission_classes = [WorkspaceEntityPermission]
    model = Project

    def get(self, request, slug):
        return Response(workspace_tags_payload(slug), status=status.HTTP_200_OK)

    def post(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        try:
            tag = create_tag(workspace.id, request.data if isinstance(request.data, dict) else {})
        except OverviewError as exc:
            return Response({exc.field: exc.message, "error": exc.message}, status=status.HTTP_400_BAD_REQUEST)
        return Response(tag_payload(tag), status=status.HTTP_201_CREATED)
