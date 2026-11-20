# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The upstream-release check: opens one work item per newer makeplane/plane release."""

from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command

from plane.db.models import Issue, Project
from plane.utils import upstream_sync


def _release(tag):
    return {"tag": tag, "url": f"https://github.com/makeplane/plane/releases/tag/{tag}", "published_at": None}


@pytest.fixture
def project(workspace, create_user):
    return Project.objects.create(name="Platform", identifier="PLAT", workspace=workspace, created_by=create_user)


@pytest.mark.unit
def test_parse_version():
    assert upstream_sync.parse_version("v1.5.0") == (1, 5, 0)
    assert upstream_sync.parse_version("1.10.2") == (1, 10, 2)
    assert upstream_sync.parse_version("v1.6.0-rc1") is None
    assert upstream_sync.parse_version("v1.10.0") > upstream_sync.parse_version("v1.9.9")


@pytest.mark.unit
def test_current_version_reads_package_json():
    assert upstream_sync.parse_version(upstream_sync.current_version()) is not None


@pytest.mark.unit
@pytest.mark.django_db
def test_check_creates_one_work_item_per_release(workspace, project):
    target = f"{workspace.slug}/plat"
    with mock.patch.object(upstream_sync, "current_version", return_value="1.5.0"):
        with mock.patch.object(upstream_sync, "latest_release", return_value=_release("v1.5.0")):
            assert upstream_sync.check(target)["status"] == "up_to_date"
        with mock.patch.object(upstream_sync, "latest_release", return_value=_release("v1.6.0")):
            assert upstream_sync.check(target, dry_run=True)["status"] == "would_create"
            assert not Issue.objects.exists()
            created = upstream_sync.check(target)
            assert created["status"] == "created" and created["work_item"].startswith("PLAT-")
            issue = Issue.objects.get()
            assert "v1.6.0" in issue.name and issue.external_id == "v1.6.0" and issue.priority == "high"
            assert "UPSTREAM_SYNC.md" in issue.description_html
            # Again, and after the work item was deleted: never a second one.
            assert upstream_sync.check(target)["status"] == "exists"
            issue.delete()
            assert upstream_sync.check(target)["status"] == "exists"
            assert Issue.all_objects.count() == 1
            # Without a target the check is off.
            assert upstream_sync.check("")["status"] == "off"


@pytest.mark.unit
@pytest.mark.django_db
def test_bad_target_and_command(workspace, project):
    with pytest.raises(upstream_sync.UpstreamSyncError):
        upstream_sync.check(f"{workspace.slug}/NOPE")
    out = StringIO()
    with mock.patch.object(upstream_sync, "current_version", return_value="1.5.0"):
        with mock.patch.object(upstream_sync, "latest_release", return_value=_release("v1.6.0")):
            call_command("check_upstream_release", target=f"{workspace.slug}/PLAT", dry_run=True, stdout=out)
    assert "v1.6.0 vs current v1.5.0: would_create" in out.getvalue()
