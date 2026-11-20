# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Project health: a predicted finish date from recent throughput, and the health shown on a project."""

import math
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from plane.utils.supervision import OPEN_GROUPS

THROUGHPUT_DAYS = 14


def finish_from_counts(open_count, done_recently, today):
    """today + open items / (items completed in the last 14 days / 14), rounded up; None without throughput."""
    if not done_recently:
        return None
    if not open_count:
        return today
    return today + timedelta(days=math.ceil(open_count * THROUGHPUT_DAYS / done_recently))


def project_counts(issues, project_ids, now=None):
    """Open and last-14-day completed work item counts per project, in one grouped query.

    `issues` is the queryset of work items to count (callers pass their own visibility and exclude
    archived, deleted and draft ones, e.g. ``Issue.issue_objects``)."""
    now = now or timezone.now()
    rows = (
        issues.filter(project_id__in=list(project_ids))
        .order_by()
        .values("project_id")
        .annotate(
            open=Count("id", filter=Q(state__group__in=OPEN_GROUPS), distinct=True),
            done=Count(
                "id",
                filter=Q(state__group="completed", completed_at__gte=now - timedelta(days=THROUGHPUT_DAYS)),
                distinct=True,
            ),
        )
    )
    return {row["project_id"]: (row["open"], row["done"]) for row in rows}


def health_for(update, predicted, target_date):
    """The latest update's health; with none, at_risk when the prediction is past the target date."""
    if update is not None:
        return update.health
    if predicted is not None and target_date is not None and predicted > target_date:
        return "at_risk"
    return "on_track"
