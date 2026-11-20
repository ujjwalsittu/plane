# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The Brief's projects strip."""

from datetime import timedelta

import pytest
from django.utils import timezone

from plane.db.models import Issue, Project, ProjectMember, ProjectUpdate, State
from plane.utils.brief import brief_for


def _project(workspace, user, identifier):
    project = Project.objects.create(name=identifier, identifier=identifier, workspace=workspace, created_by=user)
    ProjectMember.objects.create(project=project, member=user, workspace=workspace, role=20)
    started = State.objects.create(name="Started", group="started", project=project, workspace=workspace)
    completed = State.objects.create(name="Done", group="completed", project=project, workspace=workspace)
    return project, started, completed


@pytest.mark.unit
@pytest.mark.django_db
def test_projects_entry_shape_and_bounded_queries(workspace, create_user, django_assert_max_num_queries):
    alpha, started, completed = _project(workspace, create_user, "ALP")
    for n in range(4):
        Issue.objects.create(name=f"o{n}", project=alpha, workspace=workspace, state=started)
    done = Issue.objects.create(name="d", project=alpha, workspace=workspace, state=completed)
    Issue.objects.filter(pk=done.pk).update(completed_at=timezone.now() - timedelta(days=2))
    ProjectUpdate.objects.create(
        project=alpha,
        workspace=workspace,
        health="off_track",
        body_html="<p>Vendor <b>late</b></p>",
        source="api",
        created_by=create_user,
    )
    idle, _, _ = _project(workspace, create_user, "IDL")  # nothing open, no update: left out

    row = None
    with django_assert_max_num_queries(40) as baseline:
        projects = brief_for(workspace.id, create_user)["projects"]
    first = len(baseline.captured_queries)
    assert [p["identifier"] for p in projects] == ["ALP"]
    row = projects[0]
    assert set(row) == {"id", "identifier", "name", "health", "latest_update", "predicted_finish", "target_date"}
    assert row["health"] == "off_track"
    assert row["latest_update"]["excerpt"] == "Vendor late"
    assert row["latest_update"]["by"]["is_agent"] is True
    assert set(row["latest_update"]) == {"health", "excerpt", "created_at", "by"}
    assert row["predicted_finish"] is not None

    # Many more projects must not add queries per project.
    for n in range(5):
        project, started2, _ = _project(workspace, create_user, f"P{n}X")
        Issue.objects.create(name="o", project=project, workspace=workspace, state=started2)
    with django_assert_max_num_queries(first + 2):
        projects = brief_for(workspace.id, create_user)["projects"]
    assert len(projects) == 6
