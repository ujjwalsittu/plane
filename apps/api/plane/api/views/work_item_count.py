# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""GET workspaces/<slug>/work-items/count -- the SDK's ``count_workspace`` (MCP ``workitem count``)."""

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.api.views.base import BaseAPIView
from plane.app.permissions import WorkspaceEntityPermission
from plane.db.models import Issue
from plane.utils.pql_lite import SUPPORTED as PQL_SUPPORTED, UnsupportedPQL, pql_to_q
from plane.utils.work_item_count import CountError, count_work_items, visible_work_items


class WorkItemCountAPIEndpoint(BaseAPIView):
    model = Issue
    permission_classes = [WorkspaceEntityPermission]

    def get(self, request, slug):
        if request.GET.get("filters"):
            return Response(
                {"filters": f"Structured filters are not supported on this Plane edition. Use pql: {PQL_SUPPORTED}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        rows = visible_work_items(slug, request.user)
        if request.GET.get("pql"):
            try:
                rows = rows.filter(pql_to_q(request.GET["pql"], slug))
            except UnsupportedPQL as exc:
                return Response(
                    {"pql": f"{exc}. Supported on this Plane edition: {PQL_SUPPORTED}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        try:
            result = count_work_items(
                rows,
                group_by=request.GET.get("group_by") or None,
                sub_group_by=request.GET.get("sub_group_by") or None,
            )
        except CountError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)
