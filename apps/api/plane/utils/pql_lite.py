# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""A small subset of Plane Query Language for the external work item list.

Supported, joined with AND:

* ``type = "<uuid>"`` / ``type IN ("<uuid>", ...)``
* ``milestone = "<uuid>"`` / ``milestone IN (...)``
* ``parent = "<uuid>"``
* ``childOf("<PROJECT>-<N>")`` -- direct children of a work item
* ``cf["<property id>"] = <value>`` / ``cf["<property id>"] IN ("<value>", ...)`` -- custom
  property values: option or record ids for OPTION/RELATION, true/false, numbers, dates
  (YYYY-MM-DD) or text

Anything else raises :class:`UnsupportedPQL`, which the view turns into a 400
naming what is supported.
"""

# Python imports
import re
import uuid

# Django imports
from django.db.models import Q

# Module imports
from plane.db.models import Issue, IssueProperty, IssuePropertyValue

SUPPORTED = (
    'type = "<id>", type IN ("<id>", ...), milestone = "<id>", milestone IN (...), '
    'parent = "<id>", childOf("<PROJECT>-<N>") and cf["<property id>"] = <value> / IN (...), joined with AND'
)

_FIELDS = {"type": "type_id", "milestone": "milestone_id", "parent": "parent_id"}
_COMPARISON = re.compile(r"^(?P<field>\w+)\s*(?P<op>=|IN)\s*(?P<value>.+)$", re.IGNORECASE)
_CHILD_OF = re.compile(r'^childOf\(\s*"(?P<identifier>[^"]+)"\s*\)$', re.IGNORECASE)
_STRING = re.compile(r'"([^"]*)"')
_CUSTOM = re.compile(r'^cf\[\s*"(?P<id>[^"]+)"\s*\]\s*(?P<op>=|IN)\s*(?P<value>.+)$', re.IGNORECASE)


class UnsupportedPQL(ValueError):
    pass


def _uuids(raw):
    values = _STRING.findall(raw)
    if not values:
        raise UnsupportedPQL(f"Expected quoted ids in: {raw}")
    try:
        return [str(uuid.UUID(v)) for v in values]
    except ValueError as exc:
        raise UnsupportedPQL(f"Not a valid id in: {raw}") from exc


_AND = re.compile(r"\s+AND\s+", re.IGNORECASE)


def _split_and(pql):
    """Split on AND outside quotes and parentheses."""
    parts, start, depth, in_quote, i = [], 0, 0, False, 0
    while i < len(pql):
        ch = pql[i]
        if ch == '"':
            in_quote = not in_quote
        elif not in_quote and ch == "(":
            depth += 1
        elif not in_quote and ch == ")":
            depth -= 1
        elif not in_quote and depth == 0:
            match = _AND.match(pql, i)
            if match:
                parts.append(pql[start:i].strip())
                start = i = match.end()
                continue
        i += 1
    parts.append(pql[start:].strip())
    if in_quote or depth:
        raise UnsupportedPQL("Unbalanced quotes or parentheses")
    return [p for p in parts if p]


def _custom_values(raw, op):
    """The literal(s) of a cf[] comparison: quoted strings, or a bare true/false/number for =."""
    strings = _STRING.findall(raw)
    if op == "IN":
        if not strings:
            raise UnsupportedPQL(f"IN takes quoted values: {raw}")
        return strings
    if strings:
        return [strings[0]]
    bare = raw.strip()
    if bare.lower() in ("true", "false"):
        return [bare.lower() == "true"]
    try:
        return [float(bare)]
    except ValueError:
        raise UnsupportedPQL(f"Expected a quoted value, true/false or a number: {raw}") from None


def _custom_q(match, slug):
    try:
        property_id = uuid.UUID(match.group("id"))
    except ValueError as exc:
        raise UnsupportedPQL(f"Not a valid property id: {match.group('id')}") from exc
    prop = IssueProperty.objects.filter(workspace__slug=slug, pk=property_id).first()
    if prop is None:
        raise UnsupportedPQL(f"Unknown property: {property_id}")
    values = _custom_values(match.group("value"), match.group("op").upper())
    rows = IssuePropertyValue.objects.filter(property=prop)
    kind = prop.property_type
    try:
        if kind == "OPTION":
            rows = rows.filter(value_option_id__in=[uuid.UUID(str(v)) for v in values])
        elif kind == "RELATION":
            rows = rows.filter(value_uuid__in=[uuid.UUID(str(v)) for v in values])
        elif kind == "BOOLEAN":
            flags = [v if isinstance(v, bool) else str(v).lower() == "true" for v in values]
            rows = rows.filter(value_boolean__in=flags)
        elif kind == "DECIMAL":
            rows = rows.filter(value_decimal__in=[float(v) for v in values])
        elif kind == "DATETIME":
            rows = rows.filter(value_datetime__date__in=[str(v)[:10] for v in values])
        else:
            text = Q()
            for value in values:
                text |= Q(value_text__iexact=str(value))
            rows = rows.filter(text)
    except ValueError as exc:
        raise UnsupportedPQL(f"Value doesn't match the property's type: {match.group('value')}") from exc
    return Q(pk__in=rows.values("issue_id"))


def pql_to_q(pql, slug):
    """Translate ``pql`` into a Q for Issue querysets of workspace ``slug``."""
    q = Q()
    for clause in _split_and(pql.strip()):
        child_of = _CHILD_OF.match(clause)
        if child_of:
            identifier = child_of.group("identifier")
            project_identifier, _, sequence = identifier.rpartition("-")
            if not project_identifier or not sequence.isdigit():
                raise UnsupportedPQL(f"childOf expects an identifier like PROJ-12, got: {identifier}")
            parent = Issue.objects.filter(
                workspace__slug=slug,
                project__identifier__iexact=project_identifier,
                sequence_id=int(sequence),
            ).first()
            # An unknown parent matches nothing rather than everything.
            q &= Q(parent_id=parent.id) if parent else Q(pk__in=[])
            continue

        custom = _CUSTOM.match(clause)
        if custom:
            q &= _custom_q(custom, slug)
            continue

        comparison = _COMPARISON.match(clause)
        if not comparison or comparison.group("field").lower() not in _FIELDS:
            raise UnsupportedPQL(f"Unsupported clause: {clause}")
        field = _FIELDS[comparison.group("field").lower()]
        ids = _uuids(comparison.group("value"))
        if comparison.group("op").upper() == "=":
            if len(ids) != 1:
                raise UnsupportedPQL(f"= takes one id: {clause}")
            q &= Q(**{field: ids[0]})
        else:
            q &= Q(**{f"{field}__in": ids})
    return q
