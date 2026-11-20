# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Upstream-sync check for this fork: when makeplane/plane publishes a release newer than the one
this build is based on, open a work item (once per release) in the project named by
UPSTREAM_SYNC_TARGET ("<workspace slug>/<PROJECT IDENTIFIER>"). Unset means the check is off."""

# Python imports
import html
import json
import os
import re
from pathlib import Path

# Third party imports
import requests

# Module imports
from plane.db.models import Issue, Project

RELEASES_URL = "https://api.github.com/repos/makeplane/plane/releases/latest"
EXTERNAL_SOURCE = "upstream-release"
CHECKLIST_URL = "https://github.com/ujjwalsittu/plane/blob/custom/UPSTREAM_SYNC.md"
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


class UpstreamSyncError(RuntimeError):
    pass


def parse_version(value):
    """(major, minor, patch) for "v1.5.0" / "1.5.0"; None for anything else (e.g. release candidates)."""
    match = _VERSION.match(str(value or "").strip())
    return tuple(int(part) for part in match.groups()) if match else None


def current_version():
    """The upstream version this build is based on: apps/api/package.json, as register_instance reads it."""
    path = Path(__file__).resolve().parents[2] / "package.json"
    try:
        return json.loads(path.read_text())["version"]
    except (OSError, ValueError, KeyError) as exc:
        raise UpstreamSyncError(f"Can't read the current version from {path}: {exc}") from exc


def latest_release():
    """The newest published (non-draft, non-prerelease) upstream release: {tag, url, published_at}."""
    try:
        response = requests.get(RELEASES_URL, headers={"Accept": "application/vnd.github+json"}, timeout=15)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise UpstreamSyncError(f"Couldn't read the latest makeplane/plane release: {exc}") from exc
    return {"tag": data.get("tag_name"), "url": data.get("html_url"), "published_at": data.get("published_at")}


def target_project(target=None):
    """The project named by UPSTREAM_SYNC_TARGET, or None when the check is off."""
    target = (target if target is not None else os.environ.get("UPSTREAM_SYNC_TARGET", "")).strip()
    if not target:
        return None
    slug, _, identifier = target.partition("/")
    project = Project.objects.filter(
        workspace__slug=slug, identifier__iexact=identifier, archived_at__isnull=True
    ).first()
    if project is None:
        raise UpstreamSyncError(f"UPSTREAM_SYNC_TARGET {target!r} doesn't name an active project")
    return project


def _description(release, current):
    tag = html.escape(release["tag"])
    return (
        f'<p>makeplane/plane published <a href="{html.escape(release["url"] or "")}">{tag}</a>; '
        f"this fork is based on v{html.escape(current)}.</p>"
        f'<p>Follow the merge-and-deploy checklist: <a href="{CHECKLIST_URL}">UPSTREAM_SYNC.md</a></p>'
        "<ul>"
        f"<li><p>Merge {tag} into the custom branch and resolve conflicts</p></li>"
        "<li><p>Regenerate migrations_lockfile.txt if both sides added migrations</p></li>"
        "<li><p>Run the backend suite, web type checks and i18n sync check</p></li>"
        "<li><p>Take a database backup, deploy, and check the version and our features</p></li>"
        "</ul>"
    )


def check(target=None, dry_run=False):
    """Compare the latest upstream release with this build; open a work item when it's newer.

    Returns a dict: status is "off", "up_to_date", "exists" or "created" (or "would_create" on a dry run)."""
    project = target_project(target)
    current = current_version()
    release = latest_release()
    result = {"current": current, "latest": release["tag"], "url": release["url"]}
    latest, base = parse_version(release["tag"]), parse_version(current)
    if latest is None or base is None or latest <= base:
        return {**result, "status": "up_to_date"}
    if project is None:
        return {**result, "status": "off"}
    # Once per release, even if the work item was later archived or deleted.
    existing = Issue.all_objects.filter(
        project=project, external_source=EXTERNAL_SOURCE, external_id=release["tag"]
    ).first()
    if existing:
        return {**result, "status": "exists", "work_item": f"{project.identifier}-{existing.sequence_id}"}
    if dry_run:
        return {**result, "status": "would_create", "project": project.identifier}
    issue = Issue.objects.create(
        project=project,
        workspace_id=project.workspace_id,
        name=f"Merge upstream Plane {release['tag']} into the custom branch and redeploy",
        description_html=_description(release, current),
        priority="high",
        external_source=EXTERNAL_SOURCE,
        external_id=release["tag"],
    )
    return {**result, "status": "created", "work_item": f"{project.identifier}-{issue.sequence_id}"}
