# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Workspace event feed (cursor paged) and live stream (server-sent events)."""

import asyncio
import json
import time
import uuid

from asgiref.sync import sync_to_async
from django.http import JsonResponse, StreamingHttpResponse
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response

from plane.api.middleware.api_authentication import APIKeyAuthentication
from plane.api.views.base import BaseAPIView
from plane.authentication.session import BaseSessionAuthentication
from plane.db.models import Workspace, WorkspaceMember
from plane.utils.events import events_after

# Stream timings, module constants so tests can shorten them
STREAM_POLL_SECONDS = 1
STREAM_PING_SECONDS = 15
STREAM_MAX_SECONDS = 300
STREAM_BATCH = 100
# How often an open stream re-checks that the user is still an active workspace member
MEMBERSHIP_CHECK_SECONDS = 30


def workspace_for(user, slug):
    return Workspace.objects.filter(slug=slug, workspace_member__member=user, workspace_member__is_active=True).first()


def is_active_member(workspace, user):
    return WorkspaceMember.objects.filter(workspace=workspace, member=user, is_active=True).exists()


def _int(value, default=0):
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


def _types(request):
    raw = request.GET.get("types", "")
    return [t for t in (part.strip() for part in raw.split(",")) if t] or None


def _project(request):
    raw = request.GET.get("project")
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return False


class WorkspaceEventsAPIEndpoint(BaseAPIView):
    """Changes after a cursor: `?after=<id>&types=issue,decision&project=<id>&limit=<n>`."""

    authentication_classes = [APIKeyAuthentication, BaseSessionAuthentication]

    def get(self, request, slug):
        workspace = workspace_for(request.user, slug)
        if workspace is None:
            return Response({"error": "Workspace not found"}, status=status.HTTP_404_NOT_FOUND)
        project = _project(request)
        if project is False:
            return Response({"project": "project must be an id"}, status=status.HTTP_400_BAD_REQUEST)
        after = _int(request.GET.get("after"))
        results = events_after(
            workspace,
            request.user,
            after_id=after,
            types=_types(request),
            project_id=project,
            limit=_int(request.GET.get("limit"), 100) or 100,
        )
        return Response({"results": results, "next_after": results[-1]["id"] if results else after})


def _authenticate(request):
    """API key (an agent) or the browser session. Returns (user, None) or (None, error response)."""
    try:
        if request.headers.get(APIKeyAuthentication.auth_header_name):
            result = APIKeyAuthentication().authenticate(request)
            user = result[0] if result else None
        else:
            user = request.user if request.user.is_authenticated else None
    except APIException as exc:
        return None, JsonResponse({"error": str(exc.detail)}, status=exc.status_code)
    if user is None:
        return None, JsonResponse({"error": "Authentication credentials were not provided"}, status=401)
    return user, None


def _context(request, slug):
    user, error = _authenticate(request)
    if error is not None:
        return None, None, error
    workspace = workspace_for(user, slug)
    if workspace is None:
        return None, None, JsonResponse({"error": "Workspace not found"}, status=404)
    return user, workspace, None


def _frame(event):
    return f"id: {event['id']}\nevent: {event['event']}\ndata: {json.dumps(event)}\n\n"


async def _generate(workspace, user, after, types, project):
    started = last_sent = last_checked = time.monotonic()
    yield "retry: 5000\n\n"
    while time.monotonic() - started < STREAM_MAX_SECONDS:
        if time.monotonic() - last_checked >= MEMBERSHIP_CHECK_SECONDS:
            if not await sync_to_async(is_active_member)(workspace, user):
                return
            last_checked = time.monotonic()
        rows = await sync_to_async(events_after)(
            workspace, user, after_id=after, types=types, project_id=project, limit=STREAM_BATCH
        )
        for row in rows:
            yield _frame(row)
            after = row["id"]
        now = time.monotonic()
        if rows:
            last_sent = now
        elif now - last_sent >= STREAM_PING_SECONDS:
            yield ": ping\n\n"
            last_sent = now
        if len(rows) < STREAM_BATCH:
            await asyncio.sleep(STREAM_POLL_SECONDS)


async def workspace_events_stream(request, slug):
    """Live stream of the feed. Starts after `Last-Event-ID` (or `?after=`), ends after STREAM_MAX_SECONDS so
    clients reconnect with the last id they saw."""
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    user, workspace, error = await sync_to_async(_context)(request, slug)
    if error is not None:
        return error
    project = _project(request)
    if project is False:
        return JsonResponse({"project": "project must be an id"}, status=400)
    after = _int(request.headers.get("Last-Event-ID") or request.GET.get("after"))
    response = StreamingHttpResponse(
        _generate(workspace, user, after, _types(request), project), content_type="text/event-stream"
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
