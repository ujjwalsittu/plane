# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import status
from rest_framework.response import Response
from drf_spectacular.utils import OpenApiResponse

# Module imports
from plane.api.serializers import UserLiteSerializer
from plane.api.views.base import BaseAPIView
from plane.db.models import APIToken, User
from plane.utils.openapi.decorators import user_docs
from plane.utils.openapi import USER_EXAMPLE


class UserEndpoint(BaseAPIView):
    serializer_class = UserLiteSerializer
    model = User

    def get_throttles(self):
        # Clients such as the Plane MCP server call this before every request to
        # check that the API key is valid, and treat any non-200 -- including a
        # 429 -- as a revoked key. Rate limiting it turns a burst of ordinary
        # calls into a lost connection, so it neither counts toward nor is
        # blocked by the API key limit; the real calls still are.
        return []

    @user_docs(
        operation_id="get_current_user",
        summary="Get current user",
        description="Retrieve the authenticated user's profile information including basic details.",
        responses={
            200: OpenApiResponse(
                description="Current user profile",
                response=UserLiteSerializer,
                examples=[USER_EXAMPLE],
            ),
        },
    )
    def get(self, request):
        """Get current user

        Retrieve the authenticated user's profile information including basic details.
        Returns user data based on the current authentication context.
        """
        data = dict(UserLiteSerializer(request.user).data)
        # A workspace-bound token (an agent's) says which workspace it belongs to, so the Plane MCP server can
        # default to it. request.auth is the token string for API-key requests.
        if isinstance(request.auth, str):
            slug = (
                APIToken.objects.filter(token=request.auth, workspace__isnull=False)
                .values_list("workspace__slug", flat=True)
                .first()
            )
            if slug:
                data["token_workspace_slug"] = slug
        return Response(data, status=status.HTTP_200_OK)
