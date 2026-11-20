# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""SDK-compatible work item relation endpoints for the external API.

The Plane SDK (and the Plane MCP server built on it) splits relations in two:

* dependencies -- blocking / blocked_by / start_before / start_after /
  finish_before / finish_after, under ``.../work-items/<id>/dependencies/``;
* custom relations -- typed by a workspace "relation definition", under
  ``.../work-items/<id>/work-item-relations/`` and
  ``workspaces/<slug>/work-item-relation-definitions/``.

The community edition stores every relation in ``IssueRelation`` and has no
custom definitions. These endpoints serve the SDK's shapes on top of that
model: dependencies map one to one, and the two non-dependency relation types
the app already supports (``relates_to`` and ``duplicate``) are exposed as
fixed, read-only "built-in" definitions with stable ids.
"""

# Python imports
import json
import uuid

# Django imports
from django.contrib.postgres.aggregates import ArrayAgg
from django.contrib.postgres.fields import ArrayField
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import F, Q, UUIDField, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.api.views.base import BaseAPIView
from plane.api.views.issue import guest_cannot_view_issue, visible_issue_q
from plane.app.permissions import ProjectEntityPermission, WorkspaceEntityPermission
from plane.api.serializers import IssueRelationSerializer
from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import Issue, IssueCustomRelation, IssueRelation, IssueRelationDefinition, Project, Workspace
from plane.utils.host import base_host
from plane.utils.issue_relation_mapper import get_actual_relation
from plane.utils.supervision import source_for

# Dependency directions, from the perspective of the URL work item.
DEPENDENCY_TYPES = (
    "blocking",
    "blocked_by",
    "start_before",
    "start_after",
    "finish_before",
    "finish_after",
)
# The directions stored with the URL work item as ``related_issue``.
REVERSE_DEPENDENCY_TYPES = ("blocking", "start_after", "finish_after")
# What the dependency directions are stored as.
DEPENDENCY_DB_TYPES = ("blocked_by", "start_before", "finish_before")
# Non-dependency relation types exposed as built-in definitions.
CUSTOM_DB_TYPES = ("relates_to", "duplicate")

_DEFINITION_NAMESPACE = uuid.UUID("6f1c2f4e-5a1b-4c1e-9a52-0d0b3c2f7e11")


def _definition_id(key):
    return str(uuid.uuid5(_DEFINITION_NAMESPACE, key))


# relation type -> definition. ``outward`` is the label shown on the work item
# that is ``issue`` in the stored row, ``inward`` on the ``related_issue``.
BUILT_IN_DEFINITIONS = {
    "relates_to": {
        "id": _definition_id("relates_to"),
        "name": "Relates to",
        "outward": "relates to",
        "inward": "relates to",
        "color": "#6B7280",
        "sort_order": 1000.0,
    },
    "duplicate": {
        "id": _definition_id("duplicate"),
        "name": "Duplicate",
        "outward": "duplicates",
        "inward": "duplicated by",
        "color": "#F59E0B",
        "sort_order": 2000.0,
    },
}
_DEFINITIONS_BY_ID = {d["id"]: (relation_type, d) for relation_type, d in BUILT_IN_DEFINITIONS.items()}

_WORK_ITEM_FIELDS = (
    "id",
    "name",
    "sequence_id",
    "project_id",
    "state_id",
    "priority",
    "type_id",
    "is_epic",
    "label_ids",
    "assignee_ids",
)


def _work_items(issue_ids, relation_type):
    """Work items as the SDK's ``WorkItemWithRelationType``."""
    if not issue_ids:
        return []
    rows = (
        Issue.issue_objects.filter(pk__in=issue_ids)
        .annotate(
            is_epic=Coalesce(F("type__is_epic"), Value(False)),
            label_ids=Coalesce(
                ArrayAgg(
                    "labels__id",
                    distinct=True,
                    filter=Q(~Q(labels__id__isnull=True) & Q(label_issue__deleted_at__isnull=True)),
                ),
                Value([], output_field=ArrayField(UUIDField())),
            ),
            assignee_ids=Coalesce(
                ArrayAgg(
                    "assignees__id",
                    distinct=True,
                    filter=Q(
                        ~Q(assignees__id__isnull=True)
                        & Q(assignees__member_project__is_active=True)
                        & Q(issue_assignee__deleted_at__isnull=True)
                    ),
                ),
                Value([], output_field=ArrayField(UUIDField())),
            ),
        )
        .order_by("sequence_id")
        .values(*_WORK_ITEM_FIELDS)
    )
    return [{**row, "relation_type": relation_type} for row in rows]


def _get_issue(request, slug, project_id, issue_id, *, include_archived):
    """The URL work item, bound to the URL project. Raises DoesNotExist (404)."""
    manager = Issue.objects if include_archived else Issue.issue_objects
    issue = manager.get(workspace__slug=slug, project_id=project_id, pk=issue_id)
    if guest_cannot_view_issue(request.user.id, issue, slug):
        raise Issue.DoesNotExist()
    return issue


def _relations_of(slug, issue_id, user, db_types):
    """Stored relations of ``issue_id`` whose other side the user may view."""
    visible = Issue.objects.filter(visible_issue_q(user)).values("id")
    return IssueRelation.objects.filter(
        Q(issue_id=issue_id, related_issue_id__in=visible) | Q(related_issue_id=issue_id, issue_id__in=visible),
        workspace__slug=slug,
        relation_type__in=db_types,
    ).values("relation_type", "issue_id", "related_issue_id")


def _validate_targets(request, slug, issue_id):
    """The ``work_item_ids`` of the body, scoped to what the caller may view."""
    raw = request.data.get("work_item_ids")
    if not isinstance(raw, list) or not raw:
        return None, Response(
            {"error": "work_item_ids must be a non-empty list of work item ids"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        wanted = {str(uuid.UUID(str(value))) for value in raw}
    except ValueError:
        return None, Response(
            {"error": "work_item_ids must contain valid UUIDs"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    wanted.discard(str(issue_id))
    # Relations may cross projects, so scope to the workspace and to the
    # work items the caller can see.
    targets = list(
        Issue.issue_objects.filter(workspace__slug=slug, pk__in=wanted)
        .filter(pk__in=Issue.objects.filter(visible_issue_q(request.user)).values("id"))
        .values_list("id", flat=True)
    )
    missing = wanted - {str(t) for t in targets}
    if missing:
        return None, Response(
            {"error": "Some work items were not found", "work_item_ids": sorted(missing)},
            status=status.HTTP_404_NOT_FOUND,
        )
    return targets, None


def _create(request, slug, project_id, issue_id, db_type, reverse, targets):
    project = Project.objects.get(pk=project_id, workspace__slug=slug)
    IssueRelation.objects.bulk_create(
        [
            IssueRelation(
                issue_id=(target if reverse else issue_id),
                related_issue_id=(issue_id if reverse else target),
                relation_type=db_type,
                project_id=project_id,
                workspace_id=project.workspace_id,
                created_by=request.user,
                updated_by=request.user,
            )
            for target in targets
        ],
        batch_size=50,
        ignore_conflicts=True,
    )


def _log_created(request, project_id, issue_id, relation_type, targets):
    issue_activity.delay(
        source=source_for(request),
        type="issue_relation.activity.created",
        requested_data=json.dumps(
            {"relation_type": relation_type, "issues": [str(t) for t in targets]},
            cls=DjangoJSONEncoder,
        ),
        actor_id=str(request.user.id),
        issue_id=str(issue_id),
        project_id=str(project_id),
        current_instance=None,
        epoch=int(timezone.now().timestamp()),
        notification=True,
        origin=base_host(request=request, is_app=True),
    )


def _remove(request, slug, project_id, issue_id, related_issue_id, db_types):
    _get_issue(request, slug, project_id, issue_id, include_archived=False)
    relation = (
        IssueRelation.objects.filter(workspace__slug=slug, relation_type__in=db_types)
        .filter(
            Q(issue_id=issue_id, related_issue_id=related_issue_id)
            | Q(issue_id=related_issue_id, related_issue_id=issue_id)
        )
        .select_related("related_issue__state")
        .first()
    )
    if relation is None:
        return Response({"error": "Work item relation not found"}, status=status.HTTP_404_NOT_FOUND)
    current_instance = json.dumps(IssueRelationSerializer(relation).data, cls=DjangoJSONEncoder)
    relation.delete()
    issue_activity.delay(
        source=source_for(request),
        type="issue_relation.activity.deleted",
        requested_data=json.dumps({"related_issue": str(related_issue_id)}, cls=DjangoJSONEncoder),
        actor_id=str(request.user.id),
        issue_id=str(issue_id),
        project_id=str(project_id),
        current_instance=current_instance,
        epoch=int(timezone.now().timestamp()),
        notification=True,
        origin=base_host(request=request, is_app=True),
    )
    return Response(status=status.HTTP_204_NO_CONTENT)


class WorkItemDependencyListCreateAPIEndpoint(BaseAPIView):
    """List and create dependencies of a work item."""

    permission_classes = [ProjectEntityPermission]
    model = IssueRelation

    def get(self, request, slug, project_id, issue_id):
        _get_issue(request, slug, project_id, issue_id, include_archived=True)
        grouped = {key: [] for key in DEPENDENCY_TYPES}
        issue_id = str(issue_id)
        for rel in _relations_of(slug, issue_id, request.user, DEPENDENCY_DB_TYPES):
            # blocked_by: issue is blocked by related_issue, and so on.
            forward = rel["relation_type"]
            backward = {
                "blocked_by": "blocking",
                "start_before": "start_after",
                "finish_before": "finish_after",
            }[forward]
            if str(rel["issue_id"]) == issue_id:
                grouped[forward].append(rel["related_issue_id"])
            else:
                grouped[backward].append(rel["issue_id"])
        return Response(
            {key: _work_items(ids, key) for key, ids in grouped.items()},
            status=status.HTTP_200_OK,
        )

    def post(self, request, slug, project_id, issue_id):
        relation_type = request.data.get("relation_type")
        if relation_type not in DEPENDENCY_TYPES:
            return Response(
                {"error": f"relation_type must be one of: {', '.join(DEPENDENCY_TYPES)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        _get_issue(request, slug, project_id, issue_id, include_archived=False)
        targets, error = _validate_targets(request, slug, issue_id)
        if error:
            return error
        reverse = relation_type in REVERSE_DEPENDENCY_TYPES
        db_type = get_actual_relation(relation_type)
        _create(request, slug, project_id, issue_id, db_type, reverse, targets)
        _log_created(request, project_id, issue_id, relation_type, targets)

        # Only report pairs that now hold this dependency: a pair that already
        # had another relation is left as it was (one relation per pair).
        if reverse:
            linked = IssueRelation.objects.filter(
                issue_id__in=targets, related_issue_id=issue_id, relation_type=db_type
            ).values_list("issue_id", flat=True)
        else:
            linked = IssueRelation.objects.filter(
                issue_id=issue_id, related_issue_id__in=targets, relation_type=db_type
            ).values_list("related_issue_id", flat=True)
        return Response(_work_items(list(linked), relation_type), status=status.HTTP_201_CREATED)


class WorkItemDependencyDetailAPIEndpoint(BaseAPIView):
    """Remove a dependency between two work items."""

    permission_classes = [ProjectEntityPermission]
    model = IssueRelation

    def delete(self, request, slug, project_id, issue_id, related_issue_id):
        return _remove(request, slug, project_id, issue_id, related_issue_id, DEPENDENCY_DB_TYPES)


def _custom_definition(slug, definition_id):
    return IssueRelationDefinition.objects.filter(workspace__slug=slug, pk=definition_id).first()


def _custom_definition_payload(definition):
    return {
        "id": str(definition.id),
        "name": definition.name,
        "outward": definition.outward,
        "inward": definition.inward,
        "color": definition.color,
        "sort_order": definition.sort_order,
        "is_default": False,
        "is_active": definition.is_active,
        "workspace": str(definition.workspace_id),
        "created_at": definition.created_at.isoformat() if definition.created_at else None,
        "updated_at": definition.updated_at.isoformat() if definition.updated_at else None,
    }


def _labels_taken(slug, exclude_id=None):
    """Names and labels already used, lower-cased (built-in ones included)."""
    taken = set()
    for definition in BUILT_IN_DEFINITIONS.values():
        taken.update({definition["name"].lower(), definition["outward"].lower(), definition["inward"].lower()})
    customs = IssueRelationDefinition.objects.filter(workspace__slug=slug)
    if exclude_id:
        customs = customs.exclude(pk=exclude_id)
    for definition in customs:
        taken.update({definition.name.lower(), definition.outward.lower(), definition.inward.lower()})
    return taken


def _clean_definition(slug, data, instance=None):
    """Validated definition fields, or raises ValueError with a message."""
    clean = {}
    name = str(data.get("name", instance.name if instance else "") or "").strip()
    if not name:
        raise ValueError("name is required")
    outward = str(data.get("outward", instance.outward if instance else "") or "").strip() or name.lower()
    inward = str(data.get("inward", instance.inward if instance else "") or "").strip() or outward
    taken = _labels_taken(slug, exclude_id=instance.id if instance else None)
    for value in {name.lower(), outward.lower(), inward.lower()}:
        if value in taken:
            raise ValueError(f"'{value}' is already used by another relation definition")
    clean.update({"name": name[:255], "outward": outward[:255], "inward": inward[:255]})
    if "color" in data:
        clean["color"] = str(data.get("color") or "")[:32]
    if "sort_order" in data and data["sort_order"] is not None:
        clean["sort_order"] = float(data["sort_order"])
    if "is_active" in data and data["is_active"] is not None:
        clean["is_active"] = bool(data["is_active"])
    return clean


def _custom_relations_of(slug, issue_id, user):
    visible = Issue.objects.filter(visible_issue_q(user)).values("id")
    return (
        IssueCustomRelation.objects.filter(workspace__slug=slug, definition__is_active=True)
        .filter(Q(issue_id=issue_id, related_issue_id__in=visible) | Q(related_issue_id=issue_id, issue_id__in=visible))
        .select_related("definition")
    )


class WorkItemCustomRelationListCreateAPIEndpoint(BaseAPIView):
    """List and create relations typed by a definition (built-in or workspace-defined)."""

    permission_classes = [ProjectEntityPermission]
    model = IssueRelation

    def get(self, request, slug, project_id, issue_id):
        _get_issue(request, slug, project_id, issue_id, include_archived=True)
        issue_id = str(issue_id)
        grouped = {}

        def add(label, other):
            ids = grouped.setdefault(label, [])
            if other not in ids:
                ids.append(other)

        for rel in _relations_of(slug, issue_id, request.user, CUSTOM_DB_TYPES):
            definition = BUILT_IN_DEFINITIONS[rel["relation_type"]]
            if str(rel["issue_id"]) == issue_id:
                add(definition["outward"], rel["related_issue_id"])
            else:
                add(definition["inward"], rel["issue_id"])
        for rel in _custom_relations_of(slug, issue_id, request.user):
            if str(rel.issue_id) == issue_id:
                add(rel.definition.outward, rel.related_issue_id)
            else:
                add(rel.definition.inward, rel.issue_id)
        return Response(
            {label: _work_items(ids, label) for label, ids in grouped.items()},
            status=status.HTTP_200_OK,
        )

    def post(self, request, slug, project_id, issue_id):
        definition_id = str(request.data.get("relation_definition_id") or "")
        label = request.data.get("relation_definition_type")
        custom = None
        if definition_id in _DEFINITIONS_BY_ID:
            db_type, definition = _DEFINITIONS_BY_ID[definition_id]
            outward, inward = definition["outward"], definition["inward"]
        else:
            try:
                custom = _custom_definition(slug, uuid.UUID(definition_id))
            except ValueError:
                custom = None
            if custom is None or not custom.is_active:
                return Response(
                    {"error": "Unknown relation_definition_id; list them with GET work-item-relation-definitions/"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            outward, inward = custom.outward, custom.inward
        if label not in (outward, inward):
            return Response(
                {
                    "error": "relation_definition_type must be the definition's outward or inward label: "
                    f"'{outward}' or '{inward}'"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        issue = _get_issue(request, slug, project_id, issue_id, include_archived=False)
        targets, error = _validate_targets(request, slug, issue_id)
        if error:
            return error
        # Outward: the URL work item is the stored ``issue``.
        reverse = label != outward
        if custom is None:
            _create(request, slug, project_id, issue_id, db_type, reverse, targets)
            _log_created(request, project_id, issue_id, db_type, targets)
            linked = IssueRelation.objects.filter(relation_type=db_type).filter(
                Q(issue_id=issue_id, related_issue_id__in=targets) | Q(related_issue_id=issue_id, issue_id__in=targets)
            )
        else:
            for target in targets:
                IssueCustomRelation.objects.get_or_create(
                    workspace_id=issue.workspace_id,
                    definition=custom,
                    issue_id=(target if reverse else issue.id),
                    related_issue_id=(issue.id if reverse else target),
                )
            linked = IssueCustomRelation.objects.filter(definition=custom).filter(
                Q(issue_id=issue_id, related_issue_id__in=targets) | Q(related_issue_id=issue_id, issue_id__in=targets)
            )
        linked_ids = {rel.related_issue_id if str(rel.issue_id) == str(issue_id) else rel.issue_id for rel in linked}
        return Response(_work_items(list(linked_ids), label), status=status.HTTP_201_CREATED)


class WorkItemCustomRelationDetailAPIEndpoint(BaseAPIView):
    """Remove a definition-typed relation (built-in or workspace-defined) between two work items."""

    permission_classes = [ProjectEntityPermission]
    model = IssueRelation

    def delete(self, request, slug, project_id, issue_id, related_issue_id):
        custom = IssueCustomRelation.objects.filter(workspace__slug=slug).filter(
            Q(issue_id=issue_id, related_issue_id=related_issue_id)
            | Q(issue_id=related_issue_id, related_issue_id=issue_id)
        )
        if custom.exists():
            _get_issue(request, slug, project_id, issue_id, include_archived=False)
            custom.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        return _remove(request, slug, project_id, issue_id, related_issue_id, CUSTOM_DB_TYPES)


def _definition_payload(slug, definition):
    return {**definition, "is_default": True, "is_active": True, "workspace": slug}


def _parse_bool(value):
    if value is None:
        return None
    return str(value).lower() in ("true", "1", "yes")


class WorkItemRelationDefinitionListAPIEndpoint(BaseAPIView):
    """Built-in relation definitions (default) and the workspace's own."""

    permission_classes = [WorkspaceEntityPermission]
    model = IssueRelation

    def get(self, request, slug):
        is_default = _parse_bool(request.query_params.get("is_default"))
        is_active = _parse_bool(request.query_params.get("is_active"))
        results = []
        if is_default is not False and is_active is not False:
            results += [_definition_payload(slug, d) for d in BUILT_IN_DEFINITIONS.values()]
        if is_default is not True:
            customs = IssueRelationDefinition.objects.filter(workspace__slug=slug)
            if is_active is not None:
                customs = customs.filter(is_active=is_active)
            results += [_custom_definition_payload(d) for d in customs]
        return Response(
            {
                "grouped_by": None,
                "sub_grouped_by": None,
                "total_count": len(results),
                "next_cursor": "",
                "prev_cursor": "",
                "next_page_results": False,
                "prev_page_results": False,
                "count": len(results),
                "total_pages": 1,
                "total_results": len(results),
                "extra_stats": None,
                "results": results,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, slug):
        data = request.data if isinstance(request.data, dict) else {}
        try:
            clean = _clean_definition(slug, data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        workspace = Workspace.objects.get(slug=slug)
        definition = IssueRelationDefinition.objects.create(workspace=workspace, **clean)
        return Response(_custom_definition_payload(definition), status=status.HTTP_201_CREATED)


_BUILT_IN_READ_ONLY = "Built-in relation definitions can't be changed or deleted"


class WorkItemRelationDefinitionDetailAPIEndpoint(BaseAPIView):
    permission_classes = [WorkspaceEntityPermission]
    model = IssueRelation

    def get(self, request, slug, definition_id):
        match = _DEFINITIONS_BY_ID.get(str(definition_id))
        if match is not None:
            return Response(_definition_payload(slug, match[1]), status=status.HTTP_200_OK)
        custom = _custom_definition(slug, definition_id)
        if custom is None:
            return Response({"error": "Relation definition not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(_custom_definition_payload(custom), status=status.HTTP_200_OK)

    def patch(self, request, slug, definition_id):
        if str(definition_id) in _DEFINITIONS_BY_ID:
            return Response({"error": _BUILT_IN_READ_ONLY}, status=status.HTTP_400_BAD_REQUEST)
        custom = _custom_definition(slug, definition_id)
        if custom is None:
            return Response({"error": "Relation definition not found"}, status=status.HTTP_404_NOT_FOUND)
        data = request.data if isinstance(request.data, dict) else {}
        try:
            clean = _clean_definition(slug, data, instance=custom)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        for field, value in clean.items():
            setattr(custom, field, value)
        custom.save()
        return Response(_custom_definition_payload(custom), status=status.HTTP_200_OK)

    def delete(self, request, slug, definition_id):
        if str(definition_id) in _DEFINITIONS_BY_ID:
            return Response({"error": _BUILT_IN_READ_ONLY}, status=status.HTTP_400_BAD_REQUEST)
        custom = _custom_definition(slug, definition_id)
        if custom is None:
            return Response({"error": "Relation definition not found"}, status=status.HTTP_404_NOT_FOUND)
        custom.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
