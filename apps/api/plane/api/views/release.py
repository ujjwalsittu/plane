# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Releases, release tags and release labels for the SDK/MCP."""

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.api.views.base import BaseAPIView
from plane.app.permissions import WorkspaceEntityPermission
from plane.db.models import Issue, Release, ReleaseLabel, ReleaseTag, Workspace
from plane.utils import releases


def _data(request):
    return request.data if isinstance(request.data, dict) else {}


def _error(exc):
    return Response({"error": exc.message}, status=exc.status_code)


def _missing(what):
    return Response({"error": f"{what} not found"}, status=status.HTTP_404_NOT_FOUND)


def _workspace_id(slug):
    return Workspace.objects.filter(slug=slug).values_list("id", flat=True).first()


def _release(slug, release_id):
    return Release.objects.filter(workspace__slug=slug, pk=release_id).select_related("tag").first()


class _Base(BaseAPIView):
    permission_classes = [WorkspaceEntityPermission]


# --- releases -------------------------------------------------------------------------------------


class ReleaseListCreateAPIEndpoint(_Base):
    model = Release

    def get(self, request, slug):
        workspace_id = _workspace_id(slug)
        latest = releases.latest_release_id(workspace_id)
        rows = Release.objects.filter(workspace_id=workspace_id).select_related("tag").order_by("-created_at")
        return self.paginate(
            request=request,
            queryset=rows,
            on_results=lambda page: [releases.release_payload(row, latest) for row in page],
        )

    def post(self, request, slug):
        workspace_id = _workspace_id(slug)
        try:
            release = releases.create_release(workspace_id, _data(request))
        except releases.ReleaseError as exc:
            return _error(exc)
        return Response(
            releases.release_payload(release, releases.latest_release_id(workspace_id)),
            status=status.HTTP_201_CREATED,
        )


class ReleaseDetailAPIEndpoint(_Base):
    model = Release

    def get(self, request, slug, release_id):
        release = _release(slug, release_id)
        if not release:
            return _missing("Release")
        return Response(releases.release_payload(release, releases.latest_release_id(release.workspace_id)))

    def patch(self, request, slug, release_id):
        release = _release(slug, release_id)
        if not release:
            return _missing("Release")
        try:
            release = releases.update_release(release, _data(request))
        except releases.ReleaseError as exc:
            return _error(exc)
        return Response(releases.release_payload(release, releases.latest_release_id(release.workspace_id)))

    def delete(self, request, slug, release_id):
        release = _release(slug, release_id)
        if not release:
            return _missing("Release")
        releases.delete_release(release)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReleaseChangelogAPIEndpoint(_Base):
    model = Release

    def get(self, request, slug, release_id):
        release = _release(slug, release_id)
        return Response(releases.changelog_payload(release)) if release else _missing("Release")

    def patch(self, request, slug, release_id):
        release = _release(slug, release_id)
        if not release:
            return _missing("Release")
        try:
            return Response(releases.changelog_payload(releases.update_changelog(release, _data(request))))
        except releases.ReleaseError as exc:
            return _error(exc)


class ReleaseWorkItemAPIEndpoint(_Base):
    model = Issue

    def get(self, request, slug, release_id):
        release = _release(slug, release_id)
        if not release:
            return _missing("Release")
        issues = (
            Issue.issue_objects.filter(pk__in=release.work_item_links.values_list("issue_id", flat=True))
            .select_related("project", "state")
            .order_by("created_at")
        )
        return self.paginate(
            request=request,
            queryset=issues,
            on_results=lambda page: [releases.work_item_payload(issue) for issue in page],
        )

    def post(self, request, slug, release_id):
        release = _release(slug, release_id)
        if not release:
            return _missing("Release")
        try:
            issues = releases.add_work_items(release, _data(request))
        except releases.ReleaseError as exc:
            return _error(exc)
        return Response(
            [{"id": str(issue.id), "name": issue.name, "project_id": str(issue.project_id)} for issue in issues],
            status=status.HTTP_201_CREATED,
        )

    def delete(self, request, slug, release_id):
        release = _release(slug, release_id)
        if not release:
            return _missing("Release")
        try:
            releases.remove_work_items(release, _data(request))
        except releases.ReleaseError as exc:
            return _error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReleaseItemLabelAPIEndpoint(_Base):
    """Labels attached to one release."""

    model = ReleaseLabel

    def get(self, request, slug, release_id):
        release = _release(slug, release_id)
        if not release:
            return _missing("Release")
        labels = ReleaseLabel.objects.filter(pk__in=release.label_links.values_list("label_id", flat=True))
        return self.paginate(
            request=request,
            queryset=labels.order_by("sort_order", "name"),
            on_results=lambda page: [releases.label_payload(label) for label in page],
        )

    def post(self, request, slug, release_id):
        release = _release(slug, release_id)
        if not release:
            return _missing("Release")
        try:
            labels = releases.attach_labels(release, _data(request))
        except releases.ReleaseError as exc:
            return _error(exc)
        return Response([releases.label_payload(label) for label in labels], status=status.HTTP_201_CREATED)

    def delete(self, request, slug, release_id):
        release = _release(slug, release_id)
        if not release:
            return _missing("Release")
        try:
            releases.detach_labels(release, _data(request))
        except releases.ReleaseError as exc:
            return _error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- tags -----------------------------------------------------------------------------------------


class ReleaseTagListCreateAPIEndpoint(_Base):
    model = ReleaseTag

    def get(self, request, slug):
        return self.paginate(
            request=request,
            queryset=ReleaseTag.objects.filter(workspace__slug=slug).order_by("-created_at"),
            on_results=lambda page: [releases.tag_payload(tag) for tag in page],
        )

    def post(self, request, slug):
        try:
            tag = releases.save_tag(_workspace_id(slug), _data(request))
        except releases.ReleaseError as exc:
            return _error(exc)
        return Response(releases.tag_payload(tag), status=status.HTTP_201_CREATED)


class ReleaseTagDetailAPIEndpoint(_Base):
    model = ReleaseTag

    def get(self, request, slug, tag_id):
        tag = ReleaseTag.objects.filter(workspace__slug=slug, pk=tag_id).first()
        return Response(releases.tag_payload(tag)) if tag else _missing("Tag")

    def patch(self, request, slug, tag_id):
        tag = ReleaseTag.objects.filter(workspace__slug=slug, pk=tag_id).first()
        if not tag:
            return _missing("Tag")
        try:
            return Response(releases.tag_payload(releases.save_tag(tag.workspace_id, _data(request), tag)))
        except releases.ReleaseError as exc:
            return _error(exc)

    def delete(self, request, slug, tag_id):
        tag = ReleaseTag.objects.filter(workspace__slug=slug, pk=tag_id).first()
        if not tag:
            return _missing("Tag")
        tag.releases.update(tag=None)
        tag.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- label palette --------------------------------------------------------------------------------


class ReleaseLabelListCreateAPIEndpoint(_Base):
    model = ReleaseLabel

    def get(self, request, slug):
        return self.paginate(
            request=request,
            queryset=ReleaseLabel.objects.filter(workspace__slug=slug).order_by("sort_order", "name"),
            on_results=lambda page: [releases.label_payload(label) for label in page],
        )

    def post(self, request, slug):
        try:
            label = releases.save_label(_workspace_id(slug), _data(request))
        except releases.ReleaseError as exc:
            return _error(exc)
        return Response(releases.label_payload(label), status=status.HTTP_201_CREATED)


class ReleaseLabelDetailAPIEndpoint(_Base):
    model = ReleaseLabel

    def get(self, request, slug, label_id):
        label = ReleaseLabel.objects.filter(workspace__slug=slug, pk=label_id).first()
        return Response(releases.label_payload(label)) if label else _missing("Label")

    def patch(self, request, slug, label_id):
        label = ReleaseLabel.objects.filter(workspace__slug=slug, pk=label_id).first()
        if not label:
            return _missing("Label")
        try:
            return Response(releases.label_payload(releases.save_label(label.workspace_id, _data(request), label)))
        except releases.ReleaseError as exc:
            return _error(exc)

    def delete(self, request, slug, label_id):
        label = ReleaseLabel.objects.filter(workspace__slug=slug, pk=label_id).first()
        if not label:
            return _missing("Label")
        releases.delete_label(label)
        return Response(status=status.HTTP_204_NO_CONTENT)
