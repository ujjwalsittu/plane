# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Custom work item properties, shared by the external API (SDK/MCP) and the app API (web).

Payloads follow the Plane SDK models (WorkItemProperty, WorkItemPropertyOption,
WorkItemPropertyValueDetail) so the MCP tools work unchanged.
"""

# Python imports
import re
import uuid
from datetime import datetime, time
from datetime import timezone as dt_timezone

# Django imports
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import EmailValidator, URLValidator
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

# Module imports
from plane.db.models import (
    Issue,
    IssueProperty,
    IssuePropertyOption,
    IssuePropertyValue,
    IssueType,
    IssueTypeProperty,
    WorkspaceMember,
)
from plane.db.models.issue_property import PROPERTY_TYPES, RELATION_TYPES

UNSUPPORTED_PROPERTY_TYPES = ("FORMULA", "CASCADING")
TEXT_FORMATS = ("single-line", "multi-line", "readonly")
DATE_FORMATS = ("MMM dd, yyyy", "dd/MM/yyyy", "MM/dd/yyyy", "yyyy/MM/dd")
MULTI_TYPES = ("OPTION", "RELATION")


class PropertyError(ValueError):
    def __init__(self, field, message, status_code=400):
        super().__init__(message)
        self.field = field
        self.message = message
        self.status_code = status_code


def _iso(value):
    return value.isoformat() if value else None


def _id(value):
    return str(value) if value else None


# --- payloads -------------------------------------------------------------------------------------


def option_payload(option):
    return {
        "id": str(option.id),
        "name": option.name,
        "description": option.description,
        "logo_props": option.logo_props,
        "sort_order": option.sort_order,
        "is_active": option.is_active,
        "is_default": option.is_default,
        "parent": _id(option.parent_id),
        "property": str(option.property_id),
        "project": _id(option.property.project_id) if option.property_id else None,
        "workspace": str(option.workspace_id),
        "external_source": option.external_source,
        "external_id": option.external_id,
        "created_at": _iso(option.created_at),
        "updated_at": _iso(option.updated_at),
        "created_by": _id(option.created_by_id),
        "updated_by": _id(option.updated_by_id),
        "deleted_at": None,
    }


def property_payload(prop, issue_type_id=None):
    options = [option_payload(o) for o in prop.options.all()] if prop.property_type == "OPTION" else []
    if issue_type_id is None:
        link = next(iter(prop.type_links.all()), None)
        issue_type_id = link.issue_type_id if link else None
    return {
        "id": str(prop.id),
        "name": prop.name,
        "display_name": prop.display_name,
        "description": prop.description,
        "logo_props": prop.logo_props,
        "sort_order": prop.sort_order,
        "property_type": prop.property_type,
        "relation_type": prop.relation_type,
        "is_required": prop.is_required,
        "is_multi": prop.is_multi,
        "is_active": prop.is_active,
        "default_value": prop.default_value or [],
        "settings": prop.settings or {},
        "validation_rules": prop.validation_rules or {},
        "external_source": prop.external_source,
        "external_id": prop.external_id,
        "workspace": str(prop.workspace_id),
        "project": _id(prop.project_id),
        "issue_type": _id(issue_type_id),
        "options": options,
        "created_at": _iso(prop.created_at),
        "updated_at": _iso(prop.updated_at),
        "created_by": _id(prop.created_by_id),
        "updated_by": _id(prop.updated_by_id),
        "deleted_at": None,
    }


def _value_of(row, prop):
    t = prop.property_type
    if t == "BOOLEAN":
        return row.value_boolean, "boolean"
    if t == "DECIMAL":
        return row.value_decimal, "decimal"
    if t == "DATETIME":
        return _iso(row.value_datetime), "datetime"
    if t == "OPTION":
        return _id(row.value_option_id), "option"
    if t == "RELATION":
        return _id(row.value_uuid), "uuid"
    return row.value_text, "text"


def value_payload(row, prop):
    value, value_type = _value_of(row, prop)
    return {
        "id": str(row.id),
        "property_id": str(row.property_id),
        "issue_id": str(row.issue_id),
        "value": value,
        "value_type": value_type,
        "external_id": row.external_id,
        "external_source": row.external_source,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


# --- definitions ----------------------------------------------------------------------------------


def properties_queryset(workspace_slug):
    return (
        IssueProperty.objects.filter(workspace__slug=workspace_slug)
        .select_related("project")
        .prefetch_related("options", "type_links")
    )


def _slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:255] or "property"


def _clean_definition(data, instance=None):
    """Validated fields of a property create/update, as model attributes."""
    clean = {}
    if "display_name" in data or instance is None:
        display_name = str(data.get("display_name") or "").strip()
        if not display_name:
            raise PropertyError("display_name", "display_name is required")
        clean["display_name"] = display_name[:255]
        clean["name"] = _slug(display_name)
    property_type = data.get("property_type", instance.property_type if instance else None)
    if property_type in UNSUPPORTED_PROPERTY_TYPES:
        raise PropertyError("property_type", f"{property_type} properties are not available on this Plane edition")
    if property_type not in PROPERTY_TYPES:
        raise PropertyError("property_type", f"property_type must be one of {', '.join(PROPERTY_TYPES)}")
    if instance and property_type != instance.property_type and instance.values.exists():
        raise PropertyError("property_type", "Can't change the type of a property that already has values")
    clean["property_type"] = property_type

    relation_type = data.get("relation_type", instance.relation_type if instance else None)
    if property_type == "RELATION":
        if relation_type not in RELATION_TYPES:
            raise PropertyError(
                "relation_type",
                f"relation_type must be one of {', '.join(RELATION_TYPES)} on this Plane edition",
            )
    else:
        relation_type = None
    clean["relation_type"] = relation_type

    is_multi = bool(data.get("is_multi", instance.is_multi if instance else False))
    if is_multi and property_type not in MULTI_TYPES:
        raise PropertyError("is_multi", "Only OPTION and RELATION properties can hold several values")
    clean["is_multi"] = is_multi

    settings = data.get("settings", instance.settings if instance else None) or {}
    display_format = settings.get("display_format") if isinstance(settings, dict) else None
    if property_type == "TEXT":
        settings = {"display_format": display_format or "single-line"}
        if settings["display_format"] not in TEXT_FORMATS:
            raise PropertyError("settings", f"display_format must be one of {', '.join(TEXT_FORMATS)}")
    elif property_type == "DATETIME":
        settings = {"display_format": display_format or "MMM dd, yyyy"}
        if settings["display_format"] not in DATE_FORMATS:
            raise PropertyError("settings", f"display_format must be one of {', '.join(DATE_FORMATS)}")
    else:
        settings = {}
    clean["settings"] = settings

    for field in ("description",):
        if field in data:
            clean[field] = str(data.get(field) or "")
    for field in ("is_required", "is_active"):
        if field in data and data[field] is not None:
            clean[field] = bool(data[field])
    for field in ("logo_props", "validation_rules"):
        if field in data and isinstance(data[field], dict):
            clean[field] = data[field]
    if "default_value" in data:
        default = data.get("default_value") or []
        clean["default_value"] = [str(v) for v in (default if isinstance(default, list) else [default])]
    for field in ("external_source", "external_id"):
        if field in data:
            clean[field] = data.get(field) or None
    return clean


def _check_unique(workspace_id, project_id, display_name, exclude_id=None):
    clash = IssueProperty.objects.filter(
        workspace_id=workspace_id, project_id=project_id, display_name__iexact=display_name
    )
    if exclude_id:
        clash = clash.exclude(pk=exclude_id)
    if clash.exists():
        raise PropertyError("display_name", f"A property named '{display_name}' already exists here")


@transaction.atomic
def create_property(workspace_id, data, project_id=None, issue_type=None):
    clean = _clean_definition(data)
    _check_unique(workspace_id, project_id, clean["display_name"])
    prop = IssueProperty.objects.create(workspace_id=workspace_id, project_id=project_id, **clean)
    options = data.get("options") or []
    if options and prop.property_type != "OPTION":
        raise PropertyError("options", "Only OPTION properties have options")
    for index, option in enumerate(options):
        create_option(prop, option if isinstance(option, dict) else {"name": option}, sort_order=(index + 1) * 1000)
    if issue_type is not None:
        IssueTypeProperty.objects.create(workspace_id=workspace_id, issue_type=issue_type, property=prop)
    return prop


def update_property(prop, data):
    clean = _clean_definition(data, instance=prop)
    if "display_name" in clean:
        _check_unique(prop.workspace_id, prop.project_id, clean["display_name"], exclude_id=prop.id)
    for field, value in clean.items():
        setattr(prop, field, value)
    prop.save()
    return prop


def create_option(prop, data, sort_order=None):
    name = str(data.get("name") or "").strip()
    if not name:
        raise PropertyError("name", "Option name is required")
    if prop.options.filter(name__iexact=name).exists():
        raise PropertyError("name", f"An option named '{name}' already exists")
    logo_props = data.get("logo_props") if isinstance(data.get("logo_props"), dict) else {}
    if data.get("color"):
        logo_props = {**logo_props, "color": data["color"]}
    if sort_order is None:
        last = prop.options.order_by("-sort_order").first()
        sort_order = (last.sort_order + 1000) if last else 1000
    option = IssuePropertyOption.objects.create(
        workspace_id=prop.workspace_id,
        property=prop,
        name=name[:255],
        description=str(data.get("description") or ""),
        logo_props=logo_props,
        is_default=bool(data.get("is_default", False)),
        is_active=bool(data.get("is_active", True)),
        sort_order=sort_order,
        external_source=data.get("external_source") or None,
        external_id=data.get("external_id") or None,
    )
    return option


def update_option(option, data):
    if "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            raise PropertyError("name", "Option name can't be empty")
        if option.property.options.filter(name__iexact=name).exclude(pk=option.pk).exists():
            raise PropertyError("name", f"An option named '{name}' already exists")
        option.name = name[:255]
    if "description" in data:
        option.description = str(data.get("description") or "")
    if data.get("color"):
        option.logo_props = {**(option.logo_props or {}), "color": data["color"]}
    for field in ("is_default", "is_active"):
        if field in data and data[field] is not None:
            setattr(option, field, bool(data[field]))
    for field in ("external_source", "external_id"):
        if field in data:
            setattr(option, field, data.get(field) or None)
    option.save()
    return option


def attach_to_type(issue_type, property_ids, workspace_id, project_id=None):
    """Link properties to a type; returns the linked ids. Properties must be in scope."""
    wanted = [str(pid) for pid in property_ids or []]
    scope = Q(project_id__isnull=True) | (Q(project_id=project_id) if project_id else Q())
    found = {
        str(pid)
        for pid in IssueProperty.objects.filter(workspace_id=workspace_id, pk__in=wanted)
        .filter(scope)
        .values_list("id", flat=True)
    }
    missing = [pid for pid in wanted if pid not in found]
    if missing:
        raise PropertyError("properties", f"Properties not found: {', '.join(missing)}")
    for pid in wanted:
        IssueTypeProperty.objects.get_or_create(workspace_id=workspace_id, issue_type=issue_type, property_id=pid)
    return wanted


def type_property_ids(issue_type, project_id=None):
    links = IssueTypeProperty.objects.filter(issue_type=issue_type)
    if project_id:
        links = links.filter(Q(property__project_id__isnull=True) | Q(property__project_id=project_id))
    return [str(pid) for pid in links.values_list("property_id", flat=True)]


def properties_for_issue(issue):
    """Properties that apply to a work item: those linked to its type (workspace-level or of its
    project), and project-level ones of its project that aren't tied to any type."""
    candidates = (
        IssueProperty.objects.filter(workspace_id=issue.workspace_id, is_active=True)
        .filter(Q(project_id=issue.project_id) | Q(project_id__isnull=True))
        .prefetch_related("options", "type_links")
    )
    applies = []
    for prop in candidates:
        type_ids = {link.issue_type_id for link in prop.type_links.all()}
        if (issue.type_id and issue.type_id in type_ids) or (prop.project_id == issue.project_id and not type_ids):
            applies.append(prop)
    return applies


# --- values ---------------------------------------------------------------------------------------


def _parse_datetime(value):
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text.replace("Z", ""), fmt)
            if fmt == "%Y-%m-%d":
                parsed = datetime.combine(parsed.date(), time())
            return timezone.make_aware(parsed, dt_timezone.utc) if timezone.is_naive(parsed) else parsed
        except ValueError:
            continue
    raise PropertyError("value", "DATETIME values are YYYY-MM-DD or YYYY-MM-DD HH:MM:SS")


def _as_uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise PropertyError("value", f"{value!r} is not an id")


def _row_fields(prop, value, issue):
    """Model fields for one value of a property, validated against its type."""
    t = prop.property_type
    if isinstance(value, dict):
        raise PropertyError("value", "Rich text values are not available on this Plane edition")
    if t in ("TEXT", "URL", "EMAIL", "FILE"):
        if not isinstance(value, str):
            raise PropertyError("value", f"{t} values are strings")
        try:
            if t == "URL":
                URLValidator()(value)
            if t == "EMAIL":
                EmailValidator()(value)
        except DjangoValidationError:
            raise PropertyError("value", f"{value!r} is not a valid {t.lower()}")
        return {"value_text": value}
    if t == "BOOLEAN":
        if not isinstance(value, bool):
            raise PropertyError("value", "BOOLEAN values are true or false")
        return {"value_boolean": value}
    if t == "DECIMAL":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PropertyError("value", "DECIMAL values are numbers")
        return {"value_decimal": float(value)}
    if t == "DATETIME":
        return {"value_datetime": _parse_datetime(value)}
    if t == "OPTION":
        option = prop.options.filter(pk=_as_uuid(value)).first()
        if option is None:
            raise PropertyError("value", f"{value} is not an option of this property")
        return {"value_option": option}
    if t == "RELATION":
        target = _as_uuid(value)
        if prop.relation_type == "ISSUE":
            if not Issue.issue_objects.filter(workspace_id=issue.workspace_id, pk=target).exists():
                raise PropertyError("value", f"Work item {value} not found")
        elif prop.relation_type == "USER":
            if not WorkspaceMember.objects.filter(
                workspace_id=issue.workspace_id, member_id=target, is_active=True
            ).exists():
                raise PropertyError("value", f"User {value} is not a member of this workspace")
        return {"value_uuid": target}
    raise PropertyError("value", f"{t} values are not supported")


def check_property_applies(prop, issue):
    if prop.workspace_id != issue.workspace_id or (prop.project_id and prop.project_id != issue.project_id):
        raise PropertyError("property", "This property doesn't belong to the work item's project", status_code=404)


def values_of(issue, prop):
    return IssuePropertyValue.objects.filter(issue=issue, property=prop).order_by("created_at")


@transaction.atomic
def set_values(issue, prop, value, external_source=None, external_id=None):
    """Replace the property's value(s) on the work item; returns the stored rows."""
    check_property_applies(prop, issue)
    raw = value if isinstance(value, list) else [value]
    if len(raw) > 1 and not prop.is_multi:
        raise PropertyError("value", "This property holds a single value")
    if not prop.is_multi and isinstance(value, list) and len(raw) == 0:
        raise PropertyError("value", "value is required")
    fields = [_row_fields(prop, item, issue) for item in raw]
    values_of(issue, prop).delete()
    return [
        IssuePropertyValue.objects.create(
            workspace_id=issue.workspace_id,
            project_id=issue.project_id,
            issue=issue,
            property=prop,
            external_source=external_source,
            external_id=external_id,
            **row,
        )
        for row in fields
    ]


def values_response(prop, rows):
    """Multi-value properties answer with a list, single-value ones with one object."""
    if prop.is_multi:
        return [value_payload(row, prop) for row in rows]
    return value_payload(rows[0], prop) if rows else None


def issue_values_payload(issue):
    """Every property that applies to a work item, with its current value(s), for the web app."""
    props = properties_for_issue(issue)
    rows = IssuePropertyValue.objects.filter(issue=issue, property__in=props).order_by("created_at")
    by_property = {}
    for row in rows:
        by_property.setdefault(row.property_id, []).append(row)
    result = []
    for prop in props:
        prop_rows = by_property.get(prop.id, [])
        result.append(
            {
                "property": property_payload(prop),
                "values": [_value_of(row, prop)[0] for row in prop_rows],
            }
        )
    return result


def resolve_issue_type(workspace_id, type_id):
    issue_type = IssueType.objects.filter(workspace_id=workspace_id, pk=type_id).first()
    if issue_type is None:
        raise PropertyError("type_id", "Work item type not found", status_code=404)
    return issue_type
