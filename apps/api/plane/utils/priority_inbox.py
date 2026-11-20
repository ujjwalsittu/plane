# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Priority inbox: the "Needs action" tab of the notifications list.

Kept out of the upstream notification view so the fork stays easy to merge.
"""

# Django imports
from django.db.models import BooleanField, Case, Exists, OuterRef, Q, When
from django.utils import timezone

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.serializers import NotificationSerializer
from plane.db.models import Issue, Notification
from plane.utils.order_queryset import NOTIFICATION_ORDER_BY_ALLOWLIST, sanitize_order_by


def action_notifications(slug, user):
    """Unread, unsnoozed, unarchived mentions, assignments and decision requests for ``user``.

    - mention: sender ``in_app:issue_activities:mentioned`` (notification_task.py)
    - assignment: the ``assignees`` activity stores ``issue_activity.field == "assignees"`` with the new
      assignee's id in ``issue_activity.new_identifier``; matching on it (not on the ``assigned`` sender, which
      tags every activity on an issue the receiver is assigned to) keeps state changes out
    - decision request: ``entity_name="decision"`` (supervision_task.py)
    """
    intake_issue = Issue.objects.filter(
        pk=OuterRef("entity_identifier"),
        issue_intake__status__in=[0, 2, -2],
        workspace__slug=slug,
    )
    needs_action = (
        Q(sender__icontains="mentioned")
        | Q(entity_name="decision")
        | Q(data__issue_activity__field="assignees", data__issue_activity__new_identifier=str(user.id))
    )
    return (
        Notification.objects.filter(workspace__slug=slug, receiver_id=user.id, read_at__isnull=True)
        .filter(Q(snoozed_till__isnull=True) | Q(snoozed_till__lt=timezone.now()))
        .filter(archived_at__isnull=True)
        .filter(needs_action)
        .annotate(is_inbox_issue=Exists(intake_issue))
        .annotate(is_intake_issue=Exists(intake_issue))
        .annotate(
            is_mentioned_notification=Case(
                When(sender__icontains="mentioned", then=True),
                default=False,
                output_field=BooleanField(),
            )
        )
        .select_related("workspace", "project", "triggered_by", "receiver")
        .order_by("-created_at")
    )


def action_inbox_response(view, request, slug):
    """Same response shape and pagination as the regular notifications list."""
    notifications = action_notifications(slug, request.user)
    if request.GET.get("per_page", False) and request.GET.get("cursor", False):
        return view.paginate(
            order_by=sanitize_order_by(
                request.GET.get("order_by", "-created_at"), NOTIFICATION_ORDER_BY_ALLOWLIST, "-created_at"
            ),
            request=request,
            queryset=notifications,
            on_results=lambda rows: NotificationSerializer(rows, many=True).data,
        )
    return Response(NotificationSerializer(notifications, many=True).data, status=status.HTTP_200_OK)
