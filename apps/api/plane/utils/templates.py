# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Templates for work items, pages and projects, shared by the external API (SDK/MCP) and the app
API (web), and the code that creates a work item, page or project from one."""

# Python imports
import html
import json

# Django imports
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.utils import timezone

# Third party imports
from rest_framework.exceptions import ValidationError as DRFValidationError

# Module imports
from plane.db.models import (
    DEFAULT_STATES,
    Label,
    Project,
    ProjectMember,
    State,
    Template,
    WorkspaceMember,
)
from plane.utils.html_processor import html_to_plain_text

PRIORITIES = ("urgent", "high", "medium", "low", "none")
STATE_GROUPS = ("backlog", "unstarted", "started", "completed", "cancelled")
# template_data "features" key -> Project field.
PROJECT_FEATURES = {
    "cycles": "cycle_view",
    "modules": "module_view",
    "views": "issue_views_view",
    "pages": "page_view",
    "intake": "intake_view",
    "time_tracking": "is_time_tracking_enabled",
}
ADMIN, MEMBER = 20, 15


class TemplateError(ValueError):
    def __init__(self, message, status_code=400, field="error"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.field = field


def _iso(value):
    return value.isoformat() if value else None


def template_payload(template):
    return {
        "id": str(template.id),
        "name": template.name,
        "kind": template.kind,
        "template_type": template.kind,
        "description": template.description_stripped,
        "description_html": template.description_html,
        "short_description": template.description_stripped,
        "logo_props": template.logo_props or {},
        "template_data": template.template_data or {},
        "project": str(template.project_id) if template.project_id else None,
        "workspace": str(template.workspace_id),
        "created_at": _iso(template.created_at),
        "updated_at": _iso(template.updated_at),
        "created_by": str(template.created_by_id) if template.created_by_id else None,
        "updated_by": str(template.updated_by_id) if template.updated_by_id else None,
    }


# --- validation -----------------------------------------------------------------------------------


def _str_list(value, field):
    if value is None:
        return
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise TemplateError(f"template_data.{field} must be a list of strings", field="template_data")


def _check_work_item(data, where="template_data"):
    if not isinstance(data, dict):
        raise TemplateError(f"{where} must be a JSON object", field="template_data")
    for field in ("name", "description_html", "state"):
        if data.get(field) is not None and not isinstance(data[field], str):
            raise TemplateError(f"{where}.{field} must be a string", field="template_data")
    priority = data.get("priority")
    if priority is not None and str(priority).lower() not in PRIORITIES:
        raise TemplateError(f"{where}.priority is one of {', '.join(PRIORITIES)}", field="template_data")
    _str_list(data.get("labels"), "labels")
    _str_list(data.get("assignees"), "assignees")
    subs = data.get("sub_work_items")
    if subs is not None:
        if not isinstance(subs, list):
            raise TemplateError(f"{where}.sub_work_items must be a list", field="template_data")
        for n, sub in enumerate(subs):
            if isinstance(sub, str):
                continue
            _check_work_item(sub, f"{where}.sub_work_items[{n}]")
            if sub.get("sub_work_items"):
                raise TemplateError("sub work items cannot have their own sub work items", field="template_data")


def _check_page(data, where="template_data"):
    if not isinstance(data, dict):
        raise TemplateError(f"{where} must be a JSON object", field="template_data")
    for field in ("name", "description_html"):
        if data.get(field) is not None and not isinstance(data[field], str):
            raise TemplateError(f"{where}.{field} must be a string", field="template_data")


def _check_project(data):
    if data.get("description") is not None and not isinstance(data["description"], str):
        raise TemplateError("template_data.description must be a string", field="template_data")
    if data.get("network") is not None and data["network"] not in (0, 2):
        raise TemplateError("template_data.network is 0 (secret) or 2 (public)", field="template_data")
    states = data.get("states")
    if states is not None:
        if not isinstance(states, list) or not states:
            raise TemplateError("template_data.states must be a non-empty list", field="template_data")
        for n, state in enumerate(states):
            if not isinstance(state, dict) or not str(state.get("name") or "").strip():
                raise TemplateError(f"template_data.states[{n}] needs a name", field="template_data")
            if state.get("group") not in STATE_GROUPS:
                raise TemplateError(
                    f"template_data.states[{n}].group is one of {', '.join(STATE_GROUPS)}", field="template_data"
                )
        groups = {state["group"] for state in states}
        if not {"backlog", "unstarted"} & groups:
            raise TemplateError("template_data.states needs a backlog or unstarted state", field="template_data")
    labels = data.get("labels")
    if labels is not None:
        if not isinstance(labels, list):
            raise TemplateError("template_data.labels must be a list", field="template_data")
        for n, label in enumerate(labels):
            name = label if isinstance(label, str) else (label or {}).get("name") if isinstance(label, dict) else None
            if not str(name or "").strip():
                raise TemplateError(f"template_data.labels[{n}] needs a name", field="template_data")
    for n, item in enumerate(data.get("work_items") or []):
        _check_work_item(item, f"template_data.work_items[{n}]")
    for n, page in enumerate(data.get("pages") or []):
        _check_page(page, f"template_data.pages[{n}]")
    features = data.get("features")
    if features is not None:
        if not isinstance(features, dict) or set(features) - set(PROJECT_FEATURES):
            raise TemplateError(
                f"template_data.features takes {', '.join(PROJECT_FEATURES)} as true/false", field="template_data"
            )


def _check(kind, data):
    if not isinstance(data, dict):
        raise TemplateError("template_data must be a JSON object", field="template_data")
    if kind == Template.WORK_ITEM:
        _check_work_item(data)
    elif kind == Template.PAGE:
        _check_page(data)
    else:
        _check_project(data)


def _template_data(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise TemplateError("template_data must be a JSON object", field="template_data")
    if not isinstance(value, dict):
        raise TemplateError("template_data must be a JSON object", field="template_data")
    return value


def _summary(data):
    """The template's summary: description_html, or plain text in description / short_description."""
    for field in ("description_html", "description", "short_description"):
        value = data.get(field)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return "<p></p>"
            # The MCP sends a plain-text summary in description_html; keep real HTML as it is.
            return text if text.startswith("<") else f"<p>{html.escape(text)}</p>"
    return None


# --- templates ------------------------------------------------------------------------------------


def save_template(workspace_id, data, kind=None, project_id=None, template=None, replace_data=False):
    """Create (template=None) or update a template. On update template_data is merged into what is
    there (a null value drops a key) unless replace_data is set."""
    if template is None:
        kind = str(kind or data.get("kind") or "").lower()
        if kind not in Template.KINDS:
            raise TemplateError(f"kind is one of {', '.join(Template.KINDS)}", field="kind")
        if project_id and kind == Template.PROJECT:
            raise TemplateError("A project template lives at the workspace, not inside a project", field="kind")
        template = Template(workspace_id=workspace_id, project_id=project_id or None, kind=kind)
    if template._state.adding or "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            raise TemplateError("name is required", field="name")
        template.name = name[:255]
    summary = _summary(data)
    if summary is not None:
        template.description_html = summary
        template.description_stripped = html_to_plain_text(summary)
    if isinstance(data.get("logo_props"), dict):
        template.logo_props = data["logo_props"]
    if template._state.adding or data.get("template_data") is not None:
        body = _template_data(data.get("template_data") or {})
        if not template._state.adding and not replace_data:
            body = {**(template.template_data or {}), **body}
        body = {key: value for key, value in body.items() if value is not None}
        _check(template.kind, body)
        template.template_data = body
    template.save()
    return template


def visible_templates(workspace_id, user, kind=None, project_id=None, include_projects=True):
    """Templates the user can see: the workspace's own, plus (include_projects) those of projects they
    belong to; with project_id, that project's alone."""
    rows = Template.objects.filter(workspace_id=workspace_id).select_related("project")
    if kind:
        rows = rows.filter(kind=kind)
    if project_id:
        return rows.filter(project_id=project_id)
    if not include_projects:
        return rows.filter(project__isnull=True)
    is_admin = WorkspaceMember.objects.filter(
        workspace_id=workspace_id, member=user, role=ADMIN, is_active=True
    ).exists()
    if is_admin:
        return rows.filter(project__archived_at__isnull=True) | rows.filter(project__isnull=True)
    member_of = ProjectMember.objects.filter(member=user, is_active=True, workspace_id=workspace_id).values(
        "project_id"
    )
    return rows.filter(project__isnull=True) | rows.filter(project_id__in=member_of, project__archived_at__isnull=True)


def can_write(template_or_scope, user, workspace_id):
    """Workspace templates: workspace admins and members. Project templates: that project's admins
    and members, or a workspace admin."""
    project_id = getattr(template_or_scope, "project_id", template_or_scope)
    role = (
        WorkspaceMember.objects.filter(workspace_id=workspace_id, member=user, is_active=True)
        .values_list("role", flat=True)
        .first()
    )
    if role is None:
        return False
    if not project_id:
        return role >= MEMBER
    if role == ADMIN:
        return True
    return ProjectMember.objects.filter(project_id=project_id, member=user, is_active=True, role__gte=MEMBER).exists()


# --- using a template -----------------------------------------------------------------------------


def _activity(issue, user, origin, source="app"):
    # Imported here: the task module imports models that import this package.
    from plane.bgtasks.issue_activities_task import issue_activity

    issue_activity.delay(
        type="issue.activity.created",
        requested_data=json.dumps({"name": issue.name}, cls=DjangoJSONEncoder),
        actor_id=str(user.id),
        issue_id=str(issue.id),
        project_id=str(issue.project_id),
        current_instance=None,
        epoch=int(timezone.now().timestamp()),
        notification=True,
        origin=origin,
        source=source,
    )


def _state_for(project, value):
    if not value:
        return None
    states = State.objects.filter(project=project)
    return (
        states.filter(name__iexact=value).first()
        or states.filter(group=str(value).lower()).order_by("sequence").first()
    )


def _labels_for(project, values):
    if not values:
        return []
    labels = Label.objects.filter(project=project)
    found = []
    for value in values:
        label = labels.filter(name__iexact=value).first()
        if label is None:
            try:
                label = labels.filter(pk=value).first()
            except Exception:  # not a uuid
                label = None
        if label is not None and label.id not in found:
            found.append(label.id)
    return found


def _assignees_for(project, values):
    if not values:
        return []
    members = ProjectMember.objects.filter(project=project, is_active=True, role__gte=MEMBER)
    found = []
    for value in values:
        try:
            member = members.filter(member_id=value).values_list("member_id", flat=True).first()
        except Exception:
            member = None
        member = member or members.filter(member__email__iexact=value).values_list("member_id", flat=True).first()
        member = (
            member or members.filter(member__display_name__iexact=value).values_list("member_id", flat=True).first()
        )
        if member and member not in found:
            found.append(member)
    return found


def _create_issue(project, data, user, origin, parent=None, name=None, source="app"):
    # Imported here to avoid a circular import through plane.api.serializers.
    from plane.api.serializers import IssueSerializer

    if isinstance(data, str):
        data = {"name": data}
    payload = {
        "name": (name or data.get("name") or "").strip()[:255],
        "description_html": data.get("description_html") or "<p></p>",
        "priority": str(data.get("priority") or "none").lower(),
        "labels": [str(i) for i in _labels_for(project, data.get("labels"))],
        "assignees": [str(i) for i in _assignees_for(project, data.get("assignees"))],
    }
    if not payload["name"]:
        raise TemplateError("name is required", field="name")
    state = _state_for(project, data.get("state"))
    if state:
        payload["state"] = str(state.id)
    if parent:
        payload["parent"] = str(parent.id)
    serializer = IssueSerializer(
        data=payload,
        context={
            "project_id": project.id,
            "workspace_id": project.workspace_id,
            "default_assignee_id": project.default_assignee_id,
        },
    )
    if not serializer.is_valid():
        raise TemplateError(json.dumps(serializer.errors), field="template_data")
    issue = serializer.save()
    _activity(issue, user, origin, source)
    for sub in data.get("sub_work_items") or []:
        _create_issue(project, sub, user, origin, parent=issue, source=source)
    return issue


def _create_page(project, data, user, name=None):
    from plane.app.serializers import PageSerializer
    from plane.bgtasks.page_transaction_task import page_transaction

    page_name = (name or data.get("name") or "").strip()[:255]
    body = data.get("description_html") or "<p></p>"
    serializer = PageSerializer(
        data={"name": page_name},
        context={
            "project_id": project.id,
            "owned_by_id": user.id,
            "description_json": {},
            "description_binary": None,
            "description_html": body,
        },
    )
    if not serializer.is_valid():
        raise TemplateError(json.dumps(serializer.errors), field="template_data")
    page = serializer.save()
    page_transaction.delay(new_description_html=body, old_description_html=None, page_id=page.id)
    return page


def _project_member(project, user):
    return ProjectMember.objects.filter(project=project, member=user, is_active=True, role__gte=MEMBER).exists()


def use_template(template, user, data, origin=None, source="app"):
    """Create a work item, page or project from a template. Returns {"kind", "id", "project_id", ...}."""
    data = data if isinstance(data, dict) else {}
    body = template.template_data or {}
    if template.kind in (Template.WORK_ITEM, Template.PAGE):
        project_id = template.project_id or data.get("project_id")
        if not project_id:
            raise TemplateError("project_id is required", field="project_id")
        if template.project_id and data.get("project_id") and str(data["project_id"]) != str(template.project_id):
            raise TemplateError("This template belongs to another project", field="project_id")
        project = Project.objects.filter(
            pk=project_id, workspace_id=template.workspace_id, archived_at__isnull=True
        ).first()
        if project is None:
            raise TemplateError("Project not found", status_code=404, field="project_id")
        if not _project_member(project, user):
            raise TemplateError("You are not a member of this project", status_code=403, field="project_id")
        name = str(data.get("name") or "").strip() or None
        if template.kind == Template.WORK_ITEM:
            with transaction.atomic():
                issue = _create_issue(
                    project, body, user, origin, name=name or body.get("name") or template.name, source=source
                )
            return {
                "kind": template.kind,
                "id": str(issue.id),
                "project_id": str(project.id),
                "sequence_id": issue.sequence_id,
                "identifier": f"{project.identifier}-{issue.sequence_id}",
            }
        if template.kind == Template.PAGE and not project.page_view:
            raise TemplateError("Pages are turned off in this project", field="project_id")
        page = _create_page(project, body, user, name=name or body.get("name") or template.name)
        return {"kind": template.kind, "id": str(page.id), "project_id": str(project.id)}
    return {"kind": template.kind, **_create_project(template, user, data, origin, source)}


def _create_project(template, user, data, origin, source="app"):
    from plane.api.serializers import ProjectCreateSerializer

    role = (
        WorkspaceMember.objects.filter(workspace_id=template.workspace_id, member=user, is_active=True)
        .values_list("role", flat=True)
        .first()
    )
    if role is None or role < MEMBER:
        raise TemplateError("Only workspace admins and members can create projects", status_code=403)
    body = template.template_data or {}
    payload = {
        "name": str(data.get("name") or "").strip(),
        "identifier": str(data.get("identifier") or "").strip().upper(),
        "description": body.get("description") or "",
    }
    if not payload["name"]:
        raise TemplateError("name is required", field="name")
    if not payload["identifier"]:
        raise TemplateError("identifier is required", field="identifier")
    taken = Project.objects.filter(workspace_id=template.workspace_id)
    if taken.filter(identifier__iexact=payload["identifier"]).exists():
        raise TemplateError("The project identifier is already taken", status_code=409, field="identifier")
    if taken.filter(name__iexact=payload["name"]).exists():
        raise TemplateError("The project name is already taken", status_code=409, field="name")
    serializer = ProjectCreateSerializer(data=payload, context={"workspace_id": template.workspace_id})
    if not serializer.is_valid():
        errors = serializer.errors
        field = next(iter(errors), "error")
        message = errors[field][0] if isinstance(errors[field], list) else str(errors[field])
        status_code = 409 if "taken" in str(message) or "exists" in str(message) else 400
        raise TemplateError(str(message), status_code=status_code, field=field)
    try:
        with transaction.atomic():
            project = serializer.save()
            for key, value in (body.get("features") or {}).items():
                setattr(project, PROJECT_FEATURES[key], bool(value))
            project.network = body.get("network", 2)
            if isinstance(template.logo_props, dict) and template.logo_props:
                project.logo_props = template.logo_props
            project.save()
            ProjectMember.objects.create(project=project, member=user, role=ADMIN)
            states = body.get("states") or DEFAULT_STATES[:-1]
            triage = next(s for s in DEFAULT_STATES if s["group"] == "triage")
            default_group = "backlog" if any(s["group"] == "backlog" for s in states) else "unstarted"
            default_set = False
            created = []
            for n, state in enumerate(list(states) + [triage]):
                is_default = state["group"] == default_group and not default_set and state["group"] != "triage"
                default_set = default_set or is_default
                created.append(
                    State(
                        name=str(state["name"]).strip()[:255],
                        color=state.get("color") or "#60646C",
                        project=project,
                        workspace_id=project.workspace_id,
                        group=state["group"],
                        sequence=state.get("sequence") or (n + 1) * 10000 + 5000,
                        default=is_default,
                        created_by=user,
                    )
                )
            State.objects.bulk_create(created)
            for n, label in enumerate(body.get("labels") or []):
                label = {"name": label} if isinstance(label, str) else label
                Label.objects.create(
                    name=str(label["name"]).strip()[:255],
                    color=label.get("color") or "",
                    project=project,
                    workspace_id=project.workspace_id,
                    sort_order=(n + 1) * 10000,
                    created_by=user,
                )
            for item in body.get("work_items") or []:
                _create_issue(project, item, user, origin, source=source)
            for page in body.get("pages") or []:
                if str(page.get("name") or "").strip():
                    _create_page(project, page, user)
    except (IntegrityError, DRFValidationError) as exc:
        raise TemplateError(
            "A project with this name or identifier already exists" if "unique" in str(exc).lower() else str(exc),
            status_code=409,
        )
    return {"id": str(project.id), "project_id": str(project.id), "identifier": project.identifier}
