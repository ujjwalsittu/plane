# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Customers in the official Plane SDK's shapes (plane.models.customers): the payloads the API returns
and the checks every write goes through. Inputs are type-checked strictly: a boolean must be a JSON
boolean (so "false" is refused, never read as true), a number a JSON number, an id a UUID string."""

import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator, validate_email
from django.utils.text import slugify

from plane.db.models import (
    Customer,
    CustomerProperty,
    CustomerPropertyOption,
    FileAsset,
    WorkspaceMember,
)
from plane.utils.content_validator import validate_html_content
from plane.utils.html_processor import html_to_plain_text

TEXT_FORMATS = ("single-line", "multi-line", "readonly")
DATE_FORMATS = ("MMM dd, yyyy", "dd/MM/yyyy", "MM/dd/yyyy", "yyyy/MM/dd")
MAX_INT = 2147483647
MAX_TEXT_VALUE = 10000


class CustomerError(ValueError):
    """Answered as {"error": message, field: message} with status_code."""

    def __init__(self, message, status_code=400, field="error"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.field = field


def _id(value):
    return str(value) if value else None


# --- field checks ---------------------------------------------------------------------------------


def text(data, field, max_length=255, required=False):
    """A string field: None when absent or blank (unless required), else stripped and length-checked."""
    value = data.get(field)
    if value is not None and not isinstance(value, str):
        raise CustomerError(f"{field} must be a string", field=field)
    value = (value or "").strip()
    if not value:
        if required:
            raise CustomerError(f"{field} is required", field=field)
        return None
    if len(value) > max_length:
        raise CustomerError(f"{field} must be at most {max_length} characters", field=field)
    return value


def boolean(data, field):
    value = data.get(field)
    if not isinstance(value, bool):
        raise CustomerError(f"{field} must be true or false", field=field)
    return value


def number(data, field):
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CustomerError(f"{field} must be a number", field=field)
    return float(value)


def json_object(data, field):
    value = data.get(field)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise CustomerError(f"{field} must be an object", field=field)
    return value


def uuid_string(value, field):
    if not isinstance(value, str):
        raise CustomerError(f"{field} must hold UUID strings", field=field)
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise CustomerError(f"{value!r} is not a valid id", field=field)


def uuid_list(data, field, allow_empty=False):
    values = data.get(field)
    if not isinstance(values, list) or (not values and not allow_empty):
        raise CustomerError(f"{field} must be a list of ids", field=field)
    return list(dict.fromkeys(uuid_string(value, field) for value in values))


def html(data, field="description_html"):
    """Sanitised HTML and its plain text."""
    value = data.get(field)
    if value is not None and not isinstance(value, str):
        raise CustomerError(f"{field} must be a string", field=field)
    is_valid, message, clean = validate_html_content(value or "")
    if not is_valid:
        raise CustomerError(message, field=field)
    clean = clean or "<p></p>"
    return clean, html_to_plain_text(clean)


def url(data, field, max_length=800):
    value = text(data, field, max_length=max_length)
    if value:
        try:
            URLValidator(schemes=["http", "https"])(value)
        except ValidationError:
            raise CustomerError(f"{field} must be an http(s) URL", field=field)
    return value


# --- customers ------------------------------------------------------------------------------------


def apply_customer(customer, data, partial):
    """Copy the SDK's CreateCustomer/UpdateCustomer fields onto `customer` (unsaved)."""
    if not partial or "name" in data:
        customer.name = text(data, "name", required=True)
    if "description" in data:
        customer.description = json_object(data, "description")
    if "description_html" in data:
        customer.description_html, customer.description_stripped = html(data)
    if "email" in data:
        email = text(data, "email")
        if email:
            try:
                validate_email(email)
            except ValidationError:
                raise CustomerError("email is not a valid address", field="email")
        customer.email = email
    if "website_url" in data:
        customer.website_url = url(data, "website_url")
    if "logo_props" in data:
        customer.logo_props = json_object(data, "logo_props")
    for field in ("domain", "stage", "contract_status", "revenue", "external_source", "external_id"):
        if field in data:
            setattr(customer, field, text(data, field))
    if "employees" in data:
        employees = data.get("employees")
        if employees is not None and (
            isinstance(employees, bool) or not isinstance(employees, int) or not 0 <= employees <= MAX_INT
        ):
            raise CustomerError("employees must be a whole number of at least 0", field="employees")
        customer.employees = employees
    if "logo_asset" in data:
        asset_id = data.get("logo_asset")
        if asset_id is not None:
            asset_id = uuid_string(asset_id, "logo_asset")
            # Workspace-level files only (no project): a project's attachment would show to people outside it
            if not FileAsset.objects.filter(
                pk=asset_id, workspace_id=customer.workspace_id, project_id__isnull=True
            ).exists():
                raise CustomerError("logo_asset is not a workspace file in this workspace", field="logo_asset")
        customer.logo_asset_id = asset_id

    others = Customer.objects.filter(workspace_id=customer.workspace_id).exclude(pk=customer.pk)
    if others.filter(name=customer.name).exists():
        raise CustomerError("A customer with this name already exists", field="name")
    if (
        customer.external_source
        and customer.external_id
        and others.filter(external_source=customer.external_source, external_id=customer.external_id).exists()
    ):
        raise CustomerError("Another customer has this external_source and external_id", field="external_id")
    return customer


def customer_payload(customer, request_count):
    asset = customer.logo_asset
    logo_url = asset.asset_url if asset is not None and asset.deleted_at is None else None
    return {
        "id": str(customer.id),
        "deleted_at": customer.deleted_at,
        "customer_request_count": request_count,
        "logo_url": logo_url,
        "created_at": customer.created_at,
        "updated_at": customer.updated_at,
        "name": customer.name,
        "description": customer.description,
        "description_html": customer.description_html,
        "description_stripped": customer.description_stripped,
        "description_binary": None,
        "email": customer.email,
        "website_url": customer.website_url,
        "logo_props": customer.logo_props,
        "domain": customer.domain,
        "employees": customer.employees,
        "stage": customer.stage,
        "contract_status": customer.contract_status,
        "revenue": customer.revenue,
        "external_source": customer.external_source,
        "external_id": customer.external_id,
        "archived_at": customer.archived_at,
        "created_by": _id(customer.created_by_id),
        "updated_by": _id(customer.updated_by_id),
        "logo_asset": _id(customer.logo_asset_id),
        "workspace": str(customer.workspace_id),
    }


# --- properties -----------------------------------------------------------------------------------


def apply_property(prop, data, partial, has_values):
    """Copy the SDK's CreateCustomerProperty/UpdateCustomerProperty fields onto `prop` (unsaved). Returns the
    cleaned `options` list, or None when the payload has none."""
    if not partial or "display_name" in data:
        prop.display_name = text(data, "display_name", required=True)
        prop.name = slugify(prop.display_name, allow_unicode=True)[:255]
        if not prop.name:
            raise CustomerError("display_name needs a letter or digit", field="display_name")
        if CustomerProperty.objects.filter(workspace_id=prop.workspace_id, name=prop.name).exclude(pk=prop.pk).exists():
            raise CustomerError("A customer property with this display_name already exists", field="display_name")

    old_type, old_relation = prop.property_type, prop.relation_type
    if not partial or data.get("property_type") is not None:
        property_type = data.get("property_type")
        if property_type not in CustomerProperty.PROPERTY_TYPES:
            raise CustomerError(
                f"property_type is one of {', '.join(CustomerProperty.PROPERTY_TYPES)}", field="property_type"
            )
        prop.property_type = property_type
    type_changed = prop.property_type != old_type

    if prop.property_type == CustomerProperty.RELATION:
        if data.get("relation_type") is not None or not prop.relation_type:
            relation_type = data.get("relation_type")
            if relation_type not in CustomerProperty.RELATION_TYPES:
                raise CustomerError("relation_type is ISSUE or USER for RELATION properties", field="relation_type")
            prop.relation_type = relation_type
    else:
        if data.get("relation_type") is not None:
            raise CustomerError("relation_type only applies to RELATION properties", field="relation_type")
        prop.relation_type = None
    if has_values and (type_changed or prop.relation_type != old_relation):
        raise CustomerError(
            "property_type and relation_type can't change once customers hold values for it", field="property_type"
        )

    formats = {CustomerProperty.TEXT: TEXT_FORMATS, CustomerProperty.DATETIME: DATE_FORMATS}.get(prop.property_type)
    if formats is None:
        if data.get("settings") is not None and not isinstance(data.get("settings"), dict):
            raise CustomerError("settings must be an object", field="settings")
        prop.settings = {}
    elif type_changed or data.get("settings") is not None:
        settings = data.get("settings")
        display_format = settings.get("display_format") if isinstance(settings, dict) else None
        if display_format not in formats:
            raise CustomerError(
                f"settings.display_format is one of {', '.join(formats)} for {prop.property_type}", field="settings"
            )
        prop.settings = {"display_format": display_format}

    if "description" in data:
        prop.description = text(data, "description", max_length=MAX_TEXT_VALUE) or ""
    if "logo_props" in data:
        prop.logo_props = json_object(data, "logo_props")
    if data.get("sort_order") is not None:
        prop.sort_order = number(data, "sort_order")
    for field in ("is_required", "is_active", "is_multi"):
        if data.get(field) is not None:
            setattr(prop, field, boolean(data, field))
    if "validation_rules" in data:
        prop.validation_rules = json_object(data, "validation_rules")
    for field in ("external_source", "external_id"):
        if field in data:
            setattr(prop, field, text(data, field))

    options = data.get("options")
    if options is None:
        return None
    if prop.property_type != CustomerProperty.OPTION:
        raise CustomerError("options only apply to OPTION properties", field="options")
    if not isinstance(options, list) or not all(isinstance(option, dict) for option in options):
        raise CustomerError("options must be a list of objects", field="options")
    cleaned = []
    for option in options:
        row = {"id": uuid_string(option["id"], "options") if option.get("id") is not None else None}
        if row["id"] is None or "name" in option:
            row["name"] = text(option, "name", required=True)
        if "description" in option:
            row["description"] = text(option, "description", max_length=MAX_TEXT_VALUE) or ""
        if option.get("is_default") is not None:
            row["is_default"] = boolean(option, "is_default")
        cleaned.append(row)
    names = [row["name"] for row in cleaned if "name" in row]
    if len(names) != len(set(names)):
        raise CustomerError("option names must be unique", field="options")
    return cleaned


def save_options(prop, options):
    """Update the options that name an id, create the rest; options left out are kept."""
    existing = {str(option.id): option for option in prop.options.all()}
    last = max((option.sort_order for option in existing.values()), default=0)
    for row in options:
        if row["id"]:
            option = existing.get(row["id"])
            if option is None:
                raise CustomerError(f"option {row['id']} isn't an option of this property", field="options")
        else:
            last += 1000
            option = CustomerPropertyOption(workspace_id=prop.workspace_id, property=prop, sort_order=last)
        for field in ("name", "description", "is_default"):
            if field in row:
                setattr(option, field, row[field])
        if CustomerPropertyOption.objects.filter(property=prop, name=option.name).exclude(pk=option.pk).exists():
            raise CustomerError(f"option {option.name!r} already exists", field="options")
        option.save()


def option_payload(option):
    return {
        "id": str(option.id),
        "deleted_at": option.deleted_at,
        "created_at": option.created_at,
        "updated_at": option.updated_at,
        "name": option.name,
        "sort_order": option.sort_order,
        "description": option.description,
        "logo_props": option.logo_props,
        "is_active": option.is_active,
        "is_default": option.is_default,
        "external_source": option.external_source,
        "external_id": option.external_id,
        "created_by": _id(option.created_by_id),
        "updated_by": _id(option.updated_by_id),
        "workspace": str(option.workspace_id),
        "property": str(option.property_id),
        "parent": None,
    }


def property_payload(prop):
    return {
        "id": str(prop.id),
        "deleted_at": prop.deleted_at,
        "created_at": prop.created_at,
        "updated_at": prop.updated_at,
        "name": prop.name,
        "display_name": prop.display_name,
        "description": prop.description,
        "logo_props": prop.logo_props,
        "sort_order": prop.sort_order,
        "property_type": prop.property_type,
        "relation_type": prop.relation_type,
        "is_required": prop.is_required,
        "default_value": prop.default_value,
        "settings": prop.settings,
        "is_active": prop.is_active,
        "is_multi": prop.is_multi,
        "validation_rules": prop.validation_rules,
        "external_source": prop.external_source,
        "external_id": prop.external_id,
        "created_by": _id(prop.created_by_id),
        "updated_by": _id(prop.updated_by_id),
        "workspace": str(prop.workspace_id),
        # Prefetched as `options`, which the default manager already limits to undeleted rows.
        "options": [option_payload(option) for option in prop.options.all()],
    }


# --- property values ------------------------------------------------------------------------------


def clean_values(prop, values, visible_issues):
    """Check a property's values (a list of strings) against its type; returns them normalised.
    `visible_issues` is the queryset of work items the caller may see, for ISSUE relations."""
    label = prop.display_name
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise CustomerError(f"{label}: values must be a list of strings", field="values")
    values = list(dict.fromkeys(value.strip() for value in values if value.strip()))
    if not values:
        if prop.is_required:
            raise CustomerError(f"{label} is required", field="values")
        return []
    if len(values) > 1 and not prop.is_multi:
        raise CustomerError(f"{label} takes a single value", field="values")

    kind = prop.property_type
    if kind == CustomerProperty.TEXT:
        if any(len(value) > MAX_TEXT_VALUE for value in values):
            raise CustomerError(f"{label}: a value is too long", field="values")
        return values
    if kind == CustomerProperty.BOOLEAN:
        normalised = {"true": "True", "false": "False"}
        if any(value.lower() not in normalised for value in values):
            raise CustomerError(f"{label}: values are True or False", field="values")
        return [normalised[value.lower()] for value in values]
    if kind == CustomerProperty.DECIMAL:
        for value in values:
            try:
                if not Decimal(value).is_finite():
                    raise InvalidOperation
            except InvalidOperation:
                raise CustomerError(f"{label}: {value!r} is not a number", field="values")
        return values
    if kind == CustomerProperty.DATETIME:
        for value in values:
            try:
                if len(value) != 10:
                    raise ValueError
                date.fromisoformat(value)
            except ValueError:
                raise CustomerError(f"{label}: dates are YYYY-MM-DD", field="values")
        return values
    if kind == CustomerProperty.URL:
        for value in values:
            try:
                URLValidator(schemes=["http", "https"])(value)
            except ValidationError:
                raise CustomerError(f"{label}: {value!r} is not an http(s) URL", field="values")
        return values
    if kind == CustomerProperty.EMAIL:
        for value in values:
            try:
                validate_email(value)
            except ValidationError:
                raise CustomerError(f"{label}: {value!r} is not an email address", field="values")
        return values

    ids = [uuid_string(value, "values") for value in values]
    if kind == CustomerProperty.OPTION:
        found = CustomerPropertyOption.objects.filter(property=prop, is_active=True, pk__in=ids)
    elif kind == CustomerProperty.FILE:
        found = FileAsset.objects.filter(workspace_id=prop.workspace_id, pk__in=ids)
    elif prop.relation_type == "USER":
        found = WorkspaceMember.objects.filter(
            workspace_id=prop.workspace_id, is_active=True, member_id__in=ids
        ).values_list("member_id", flat=True)
        if len(set(found)) != len(ids):
            raise CustomerError(f"{label}: a user isn't a member of this workspace", field="values")
        return ids
    else:
        found = visible_issues.filter(pk__in=ids)
    if found.count() != len(ids):
        raise CustomerError(f"{label}: a value isn't one this property can hold", field="values")
    return ids


# --- requests and linked work items ---------------------------------------------------------------


def apply_request(customer_request, data, partial):
    if not partial or "name" in data:
        customer_request.name = text(data, "name", required=True)
    if "description" in data:
        customer_request.description = json_object(data, "description")
    if "description_html" in data:
        customer_request.description_html, customer_request.description_stripped = html(data)
    if "link" in data:
        customer_request.link = url(data, "link")
    return customer_request


def request_payload(customer_request, work_item_ids):
    return {
        "id": str(customer_request.id),
        "name": customer_request.name,
        "description": customer_request.description,
        "description_html": customer_request.description_html,
        "link": customer_request.link,
        "work_item_ids": work_item_ids,
        # Requests have no attachments in this fork.
        "attachment_count": 0,
        "created_at": customer_request.created_at,
    }


def work_item_payload(issue):
    return {
        "id": str(issue.id),
        "name": issue.name,
        "state_id": _id(issue.state_id),
        "priority": issue.priority,
        "sequence_id": issue.sequence_id,
        "project_id": str(issue.project_id),
        "project__identifier": issue.project.identifier,
        "created_at": issue.created_at,
        "updated_at": issue.updated_at,
    }


def linked_work_item_payload(issue):
    return {
        "id": str(issue.id),
        "name": issue.name,
        "sequence_id": issue.sequence_id,
        "project_id": str(issue.project_id),
        "project__identifier": issue.project.identifier,
    }
