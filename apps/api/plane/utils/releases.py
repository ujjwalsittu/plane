# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Releases, release tags and release labels, shared by the external API (SDK/MCP) and the app
API (web)."""

# Python imports
from datetime import date

# Django imports
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

# Module imports
from plane.db.models import (
    Issue,
    Release,
    ReleaseLabel,
    ReleaseLabelLink,
    ReleaseTag,
    ReleaseWorkItem,
    WorkspaceMember,
)
from plane.utils.html_processor import html_to_plain_text


class ReleaseError(ValueError):
    def __init__(self, message, status_code=400, field="error"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.field = field


def _iso(value):
    return value.isoformat() if value else None


def _date(data, field):
    value = data.get(field)
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ReleaseError(f"{field} must be a date (YYYY-MM-DD)", field=field)


def _audit(row):
    return {
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "created_by": str(row.created_by_id) if row.created_by_id else None,
        "updated_by": str(row.updated_by_id) if row.updated_by_id else None,
        "workspace": str(row.workspace_id),
    }


# --- tags -----------------------------------------------------------------------------------------


def tag_payload(tag):
    return {
        "id": str(tag.id),
        "version": tag.version,
        "description": tag.description,
        "commit_hash": tag.commit_hash,
        "git_tag": tag.git_tag,
        **_audit(tag),
    }


def save_tag(workspace_id, data, tag=None):
    tag = tag or ReleaseTag(workspace_id=workspace_id)
    if tag._state.adding or "version" in data:
        version = str(data.get("version") or "").strip()
        if not version:
            raise ReleaseError("version is required", field="version")
        clash = ReleaseTag.objects.filter(workspace_id=workspace_id, version__iexact=version).exclude(pk=tag.pk)
        if clash.exists():
            raise ReleaseError(f"A tag {version} already exists", status_code=409, field="version")
        tag.version = version[:255]
    for field, limit in (("description", None), ("commit_hash", 64), ("git_tag", 255)):
        if field in data:
            value = str(data.get(field) or "")
            setattr(tag, field, value[:limit] if limit else value)
    tag.save()
    return tag


# --- labels ---------------------------------------------------------------------------------------


def label_payload(label):
    return {
        "id": str(label.id),
        "name": label.name,
        "color": label.color,
        "sort_order": label.sort_order,
        **_audit(label),
    }


def save_label(workspace_id, data, label=None):
    label = label or ReleaseLabel(workspace_id=workspace_id)
    if label._state.adding or "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            raise ReleaseError("name is required", field="name")
        label.name = name[:255]
    if "color" in data:
        label.color = str(data.get("color") or "")[:32]
    if data.get("sort_order") is not None:
        label.sort_order = float(data["sort_order"])
    label.save()
    return label


@transaction.atomic
def delete_label(label):
    label.release_links.all().delete()
    label.delete()


# --- releases -------------------------------------------------------------------------------------


def latest_release_id(workspace_id):
    latest = (
        Release.objects.filter(workspace_id=workspace_id, status=Release.RELEASED, is_prerelease=False)
        .order_by("-release_date", "-created_at")
        .values_list("id", flat=True)
        .first()
    )
    return latest


def progress(release):
    counts = Issue.issue_objects.filter(pk__in=release.work_item_links.values_list("issue_id", flat=True)).aggregate(
        total=Count("id", distinct=True),
        completed=Count("id", filter=Q(state__group="completed"), distinct=True),
        cancelled=Count("id", filter=Q(state__group="cancelled"), distinct=True),
    )
    active = counts["total"] - counts["cancelled"]
    counts["percent"] = round(100 * counts["completed"] / active) if active else 0
    return counts


def release_payload(release, latest_id=None):
    return {
        "id": str(release.id),
        "name": release.name,
        "description": {
            "description_html": release.description_html,
            "description_json": release.description_json or None,
            "description_stripped": release.description_stripped,
        },
        "description_html": release.description_html,
        "status": release.status,
        "release_date": _iso(release.release_date),
        "target_date": _iso(release.target_date),
        "lead": str(release.lead_id) if release.lead_id else None,
        "tag": str(release.tag_id) if release.tag_id else None,
        "tag_version": release.tag.version if release.tag_id else None,
        "is_latest": latest_id is not None and release.id == latest_id,
        "is_prerelease": release.is_prerelease,
        "external_source": release.external_source,
        "external_id": release.external_id,
        "label_ids": [str(lid) for lid in release.label_links.values_list("label_id", flat=True)],
        "progress": progress(release),
        **_audit(release),
    }


def _apply(release, data, partial):
    if not partial or "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            raise ReleaseError("name is required", field="name")
        release.name = name[:255]
    if data.get("description_html") is not None:
        release.description_html = data["description_html"] or "<p></p>"
        release.description_stripped = html_to_plain_text(release.description_html)
        release.description_json = data.get("description_json") or {}
    if data.get("status"):
        status = str(data["status"]).lower()
        if status not in Release.STATUSES:
            raise ReleaseError(f"status is one of {', '.join(Release.STATUSES)}", field="status")
        release.status = status
    for field in ("release_date", "target_date"):
        if field in data:
            setattr(release, field, _date(data, field))
    if release.status == Release.RELEASED and release.release_date is None:
        release.release_date = timezone.now().date()
    if "lead" in data:
        lead = data.get("lead")
        if (
            lead
            and not WorkspaceMember.objects.filter(
                workspace_id=release.workspace_id, member_id=lead, is_active=True
            ).exists()
        ):
            raise ReleaseError("lead is not a member of this workspace", field="lead")
        release.lead_id = lead or None
    if "tag" in data:
        tag = data.get("tag")
        if tag and not ReleaseTag.objects.filter(workspace_id=release.workspace_id, pk=tag).exists():
            raise ReleaseError("tag is not a release tag of this workspace", field="tag")
        release.tag_id = tag or None
    if data.get("is_prerelease") is not None:
        release.is_prerelease = bool(data["is_prerelease"])
    for field in ("external_source", "external_id"):
        if field in data:
            setattr(release, field, data.get(field) or None)


def create_release(workspace_id, data):
    release = Release(workspace_id=workspace_id)
    _apply(release, data, partial=False)
    release.save()
    return release


def update_release(release, data):
    _apply(release, data, partial=True)
    release.save()
    return release


@transaction.atomic
def delete_release(release):
    release.label_links.all().delete()
    release.work_item_links.all().delete()
    release.delete()


def changelog_payload(release):
    return {
        "id": str(release.id),
        "release": str(release.id),
        "changelog": {
            "description_html": release.changelog_html,
            "description_json": release.changelog_json or None,
            "description_stripped": html_to_plain_text(release.changelog_html),
        },
        "created_at": _iso(release.created_at),
        "updated_at": _iso(release.changelog_updated_at or release.created_at),
        "created_by": str(release.created_by_id) if release.created_by_id else None,
        "updated_by": str(release.updated_by_id) if release.updated_by_id else None,
        "workspace": str(release.workspace_id),
    }


def update_changelog(release, data):
    html = data.get("description_html")
    if html is None:
        raise ReleaseError("description_html is required", field="description_html")
    release.changelog_html = html or "<p></p>"
    release.changelog_json = data.get("description_json") or {}
    release.changelog_updated_at = timezone.now()
    release.save(update_fields=["changelog_html", "changelog_json", "changelog_updated_at", "updated_at"])
    return release


# --- links ----------------------------------------------------------------------------------------


def _ids(data, name):
    value = data.get(name)
    if isinstance(value, str):
        value = [v.strip() for v in value.split(",") if v.strip()]
    if not isinstance(value, list) or not value:
        raise ReleaseError(f"{name} must be a non-empty list of ids", field=name)
    return [str(v) for v in value]


def _link(model, lookup):
    try:
        with transaction.atomic():
            model.objects.get_or_create(**lookup)
    except IntegrityError:
        pass


def add_work_items(release, data):
    ids = _ids(data, "work_item_ids")
    issues = list(Issue.issue_objects.filter(workspace_id=release.workspace_id, pk__in=ids))
    if len(issues) != len(set(ids)):
        raise ReleaseError("Some work items are not in this workspace", field="work_item_ids")
    for issue in issues:
        _link(ReleaseWorkItem, {"workspace_id": release.workspace_id, "release": release, "issue": issue})
    return issues


def remove_work_items(release, data):
    release.work_item_links.filter(issue_id__in=_ids(data, "work_item_ids")).delete()


def work_item_payload(issue):
    return {
        "id": str(issue.id),
        "name": issue.name,
        "project_id": str(issue.project_id),
        "project_identifier": issue.project.identifier,
        "sequence_id": issue.sequence_id,
        "state_id": str(issue.state_id) if issue.state_id else None,
        "state_group": issue.state.group if issue.state_id else None,
        "state_name": issue.state.name if issue.state_id else None,
    }


def attach_labels(release, data):
    ids = _ids(data, "label_ids")
    labels = list(ReleaseLabel.objects.filter(workspace_id=release.workspace_id, pk__in=ids))
    if len(labels) != len(set(ids)):
        raise ReleaseError("Some labels are not in this workspace's palette", field="label_ids")
    for label in labels:
        _link(ReleaseLabelLink, {"workspace_id": release.workspace_id, "release": release, "label": label})
    return labels


def detach_labels(release, data):
    release.label_links.filter(label_id__in=_ids(data, "label_ids")).delete()
