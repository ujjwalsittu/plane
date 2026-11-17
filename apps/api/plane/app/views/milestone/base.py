# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.serializers import IssueTypeSerializer, MilestoneSerializer
from plane.app.views.base import BaseAPIView, BaseViewSet
from plane.db.models import Issue, Milestone, Project
from plane.utils.host import base_host
from plane.utils.milestone import (
    link_issue_type,
    milestone_queryset,
    project_issue_types,
    set_issues_milestone,
    unlink_issue_type,
)


class MilestoneViewSet(BaseViewSet):
    serializer_class = MilestoneSerializer
    model = Milestone

    def get_queryset(self):
        return milestone_queryset(self.kwargs["slug"], self.kwargs["project_id"])

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def list(self, request, slug, project_id):
        return Response(self.serializer_class(self.get_queryset(), many=True).data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def retrieve(self, request, slug, project_id, pk):
        milestone = self.get_queryset().get(pk=pk)
        return Response(self.serializer_class(milestone).data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def create(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        milestone = serializer.save(project=project, workspace_id=project.workspace_id)
        return Response(
            self.serializer_class(self.get_queryset().get(pk=milestone.pk)).data,
            status=status.HTTP_201_CREATED,
        )

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def partial_update(self, request, slug, project_id, pk):
        milestone = Milestone.objects.get(pk=pk, project_id=project_id, workspace__slug=slug)
        serializer = self.serializer_class(milestone, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(self.serializer_class(self.get_queryset().get(pk=pk)).data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN], creator=True, model=Milestone)
    def destroy(self, request, slug, project_id, pk):
        milestone = Milestone.objects.get(pk=pk, project_id=project_id, workspace__slug=slug)
        issue_ids = list(Issue.issue_objects.filter(milestone=milestone).values_list("id", flat=True))
        set_issues_milestone(request, slug, project_id, issue_ids, None, base_host(request=request, is_app=True))
        # Archived and draft items keep no reference to a deleted milestone either.
        Issue.all_objects.filter(milestone=milestone).update(milestone=None)
        milestone.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MilestoneIssueEndpoint(BaseAPIView):
    """Add work items to a milestone, or take them out."""

    def _issue_ids(self, request):
        issues = request.data.get("issues")
        if not isinstance(issues, list) or not issues:
            return None
        return issues

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def post(self, request, slug, project_id, milestone_id):
        milestone = Milestone.objects.get(pk=milestone_id, project_id=project_id, workspace__slug=slug)
        issue_ids = self._issue_ids(request)
        if issue_ids is None:
            return Response({"error": "issues must be a non-empty list"}, status=status.HTTP_400_BAD_REQUEST)
        changed = set_issues_milestone(
            request, slug, project_id, issue_ids, milestone, base_host(request=request, is_app=True)
        )
        return Response({"updated": changed}, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def delete(self, request, slug, project_id, milestone_id):
        milestone = Milestone.objects.get(pk=milestone_id, project_id=project_id, workspace__slug=slug)
        issue_ids = self._issue_ids(request)
        if issue_ids is None:
            return Response({"error": "issues must be a non-empty list"}, status=status.HTTP_400_BAD_REQUEST)
        in_milestone = Issue.issue_objects.filter(milestone=milestone, pk__in=issue_ids).values_list("id", flat=True)
        set_issues_milestone(
            request, slug, project_id, list(in_milestone), None, base_host(request=request, is_app=True)
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectIssueTypeEndpoint(BaseAPIView):
    """Work item types of a project."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        return Response(
            IssueTypeSerializer(project_issue_types(slug, project_id), many=True).data,
            status=status.HTTP_200_OK,
        )

    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        serializer = IssueTypeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        name = serializer.validated_data["name"]
        if project_issue_types(slug, project_id).filter(name__iexact=name).exists():
            return Response(
                {"error": f"A work item type named '{name}' already exists in this project"},
                status=status.HTTP_409_CONFLICT,
            )
        issue_type = serializer.save(workspace_id=project.workspace_id)
        link_issue_type(issue_type, project)
        if not project.is_issue_type_enabled:
            project.is_issue_type_enabled = True
            project.save(update_fields=["is_issue_type_enabled"])
        return Response(IssueTypeSerializer(issue_type).data, status=status.HTTP_201_CREATED)


class ProjectIssueTypeDetailEndpoint(BaseAPIView):
    def _get(self, slug, project_id, pk):
        return project_issue_types(slug, project_id).get(pk=pk)

    @allow_permission([ROLE.ADMIN])
    def patch(self, request, slug, project_id, pk):
        issue_type = self._get(slug, project_id, pk)
        serializer = IssueTypeSerializer(issue_type, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        name = serializer.validated_data.get("name")
        if name and project_issue_types(slug, project_id).filter(name__iexact=name).exclude(pk=issue_type.pk).exists():
            return Response(
                {"error": f"A work item type named '{name}' already exists in this project"},
                status=status.HTTP_409_CONFLICT,
            )
        issue_type = serializer.save()
        if issue_type.is_default:
            # One default type per project.
            project_issue_types(slug, project_id).exclude(pk=issue_type.pk).filter(is_default=True).update(
                is_default=False
            )
        return Response(IssueTypeSerializer(issue_type).data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def delete(self, request, slug, project_id, pk):
        issue_type = self._get(slug, project_id, pk)
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        unlink_issue_type(issue_type, project)
        return Response(status=status.HTTP_204_NO_CONTENT)
