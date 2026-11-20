# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Workspace work item counts, optionally grouped and sub-grouped, in the shape the Plane SDK's
``count_workspace`` returns: {grouped_by, sub_grouped_by, total_count, grouped_counts}."""

# Python imports
from datetime import date

# Django imports
from django.db.models import Count, FilteredRelation, Q

# Module imports
from plane.db.models import Issue, ProjectMember

# group_by value -> (column to group on, relation to join with live rows only, or None)
_LINKS = {
    "assignees__id": ("live_assignee__assignee_id", "issue_assignee"),
    "labels__id": ("live_label__label_id", "label_issue"),
    "issue_module__module_id": ("live_module__module_id", "issue_module"),
    "cycle_id": ("live_cycle__cycle_id", "issue_cycle"),
    "release_work_items__release_id": ("live_release__release_id", "release_links"),
}
_ALIASES = {
    "issue_assignee": "live_assignee",
    "label_issue": "live_label",
    "issue_module": "live_module",
    "issue_cycle": "live_cycle",
    "release_links": "live_release",
}
_DIRECT = (
    "state_id",
    "state__group",
    "priority",
    "project_id",
    "type_id",
    "milestone_id",
    "created_by",
    "target_date",
    "start_date",
)
GROUP_BY_VALUES = _DIRECT + tuple(_LINKS)


class CountError(ValueError):
    pass


def _column(rows, group_by):
    """Join what group_by needs and return (rows, column name)."""
    if group_by in _DIRECT:
        return rows, ("created_by_id" if group_by == "created_by" else group_by)
    column, relation = _LINKS[group_by]
    alias = _ALIASES[relation]
    rows = rows.annotate(
        **{alias: FilteredRelation(relation, condition=Q(**{f"{relation}__deleted_at__isnull": True}))}
    )
    return rows, column


def _key(value):
    if value is None:
        return "None"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _counts(rows, column):
    result = {}
    for row in rows.order_by().values(column).annotate(count=Count("id", distinct=True)):
        key = _key(row[column])
        result[key] = result.get(key, 0) + row["count"]
    return result


def count_work_items(rows, group_by=None, sub_group_by=None):
    """rows: an Issue queryset already narrowed to what the caller may see and asked for."""
    for name, value in (("group_by", group_by), ("sub_group_by", sub_group_by)):
        if value and value not in GROUP_BY_VALUES:
            raise CountError(f"{name} is one of: {', '.join(GROUP_BY_VALUES)}")
    if sub_group_by and not group_by:
        raise CountError("sub_group_by needs group_by")
    if sub_group_by and sub_group_by == group_by:
        raise CountError("sub_group_by must differ from group_by")

    total = rows.order_by().values("id").distinct().count()
    response = {"grouped_by": group_by, "sub_grouped_by": sub_group_by, "total_count": total, "grouped_counts": {}}
    if not group_by:
        return response

    grouped, column = _column(rows, group_by)
    groups = {key: {"count": count} for key, count in _counts(grouped, column).items()}
    if sub_group_by:
        both, sub_column = _column(grouped, sub_group_by)
        for row in both.order_by().values(column, sub_column).annotate(count=Count("id", distinct=True)):
            entry = groups.setdefault(_key(row[column]), {"count": 0})
            subs = entry.setdefault("sub_grouped_counts", {})
            sub_key = _key(row[sub_column])
            subs[sub_key] = {"count": subs.get(sub_key, {}).get("count", 0) + row["count"]}
        for entry in groups.values():
            entry.setdefault("sub_grouped_counts", {})
    response["grouped_counts"] = groups
    return response


def visible_work_items(workspace_slug, user):
    """Work items in active projects of the workspace that the user is a member of."""
    member_of = ProjectMember.objects.filter(member=user, is_active=True).values("project_id")
    return Issue.issue_objects.filter(
        workspace__slug=workspace_slug, project__archived_at__isnull=True, project_id__in=member_of
    )
