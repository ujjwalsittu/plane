# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Loops: a project runs a cloud agent on a schedule or on workspace events, as a person, with run history."""

import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import MagicMock, create_autospec, patch

import pytest
from anthropic.resources.beta.sessions.events import Events
from anthropic.resources.beta.sessions.sessions import Sessions
from anthropic.types.beta import BetaManagedAgentsSession
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from plane.db.models import AgentLoop, AgentRun, Project, ProjectMember, User, WorkspaceEvent, WorkspaceMember
from plane.utils import agents, loops, managed_agents
from plane.utils.ai_config import get_config
from plane.utils.events import emit_event


@pytest.fixture(autouse=True)
def _settings(settings, monkeypatch):
    settings.WEB_URL = "https://plane.example.com"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-instance")


@pytest.fixture
def client():
    client = MagicMock()
    client.with_options.return_value = client
    client.beta.sessions = create_autospec(Sessions, instance=True)
    client.beta.sessions.events = create_autospec(Events, instance=True)
    client.beta.sessions.create.return_value = BetaManagedAgentsSession.model_construct(id="sesn_1", status="idle")
    with patch("plane.utils.managed_agents.anthropic_client_for", return_value=client):
        yield client


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(name="Alpha", identifier="ALP", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


@pytest.fixture
def agent(workspace, create_user, project):
    agent, _ = agents.create_agent(
        workspace, {"name": "Builder", "owner": str(create_user.id), "project_ids": [str(project.id)]}, create_user
    )
    agent.ma_agent_id, agent.ma_agent_version, agent.ma_vault_id = "agent_1", 3, "vlt_1"
    agent.ma_vault_token_id = managed_agents.active_token(agent).id
    agent.save()
    config = get_config(workspace)
    config.ma_environment_id = "env_1"
    config.save()
    return agent


def _member(workspace, project, email, role=15):
    user = User.objects.create(email=email, username=email.split("@")[0], first_name=email.split("@")[0].title())
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=max(role, 5))
    ProjectMember.objects.create(project=project, member=user, workspace=workspace, role=role)
    return user


def _as(user):
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def _url(workspace, project, suffix=""):
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/loops/{suffix}"


def _loop(project, agent, owner, **fields):
    data = {
        "name": "Weekly project update",
        "agent_id": str(agent.id),
        "instructions": "Post a project update.",
        "trigger": "schedule",
        "schedule": {"every": "day", "at": "09:00"},
        **fields,
    }
    return loops.create_loop(project, data, owner)


def _utc(*args):
    return datetime(*args, tzinfo=dt_timezone.utc)


def _issue_event(workspace, project, actor, event="issue"):
    return emit_event(workspace.id, event, "created", uuid.uuid4(), project_id=project.id, actor=actor)


@pytest.mark.unit
@pytest.mark.django_db
class TestLoops:
    def test_schedule_next_run(self):
        hour = {"every": "hour"}
        assert loops.next_run_after(hour, _utc(2026, 11, 22, 10, 20)) == _utc(2026, 11, 22, 11, 0)
        assert loops.next_run_after(hour, _utc(2026, 11, 22, 10, 0)) == _utc(2026, 11, 22, 11, 0)
        assert loops.next_run_after(hour, _utc(2026, 11, 22, 23, 30)) == _utc(2026, 11, 23, 0, 0)

        day = {"every": "day", "at": "09:00"}
        assert loops.next_run_after(day, _utc(2026, 11, 22, 8, 0)) == _utc(2026, 11, 22, 9, 0)
        assert loops.next_run_after(day, _utc(2026, 11, 22, 9, 0)) == _utc(2026, 11, 23, 9, 0)
        assert loops.next_run_after(day, _utc(2026, 11, 22, 10, 0)) == _utc(2026, 11, 23, 9, 0)

        # 2026-11-22 is a Sunday; Monday is weekday 0
        monday = {"every": "week", "at": "09:00", "weekday": 0}
        assert loops.next_run_after(monday, _utc(2026, 11, 22, 12, 0)) == _utc(2026, 11, 23, 9, 0)
        assert loops.next_run_after(monday, _utc(2026, 11, 23, 9, 0)) == _utc(2026, 11, 30, 9, 0)
        assert loops.next_run_after(monday, _utc(2026, 11, 23, 8, 59)) == _utc(2026, 11, 23, 9, 0)
        sunday = {"every": "week", "at": "18:30", "weekday": 6}
        assert loops.next_run_after(sunday, _utc(2026, 11, 22, 19, 0)) == _utc(2026, 11, 29, 18, 30)

    def test_due_loop_starts_managed_run_as_owner(self, workspace, project, agent, client, create_user):
        loop = _loop(project, agent, create_user)
        AgentLoop.objects.filter(pk=loop.pk).update(next_run_at=timezone.now() - timedelta(minutes=1))

        loops.run_due_loops()

        run = AgentRun.objects.get(loop=loop)
        assert run.delegated_by_id == create_user.id
        assert run.issue_id is None
        assert run.kind == "managed" and run.agent_id == agent.id
        loop.refresh_from_db()
        assert loop.next_run_at > timezone.now()
        assert loop.last_run_at is not None and loop.last_error == ""
        title = client.beta.sessions.create.call_args.kwargs["title"]
        assert title.startswith("ALP · ")
        brief = client.beta.sessions.events.send.call_args.kwargs["events"][0]["content"][0]["text"]
        assert "Alpha" in brief and "Post a project update." in brief

        # Not due again until the next slot
        loops.run_due_loops()
        assert AgentRun.objects.filter(loop=loop).count() == 1

    def test_event_loop_respects_cooldown_and_types(self, workspace, project, agent, client, create_user):
        loop = _loop(project, agent, create_user, trigger="event", event_types=["issue"], cooldown_minutes=60)
        for _ in range(3):
            _issue_event(workspace, project, create_user)

        loops.run_due_loops()
        assert AgentRun.objects.filter(loop=loop).count() == 1
        brief = client.beta.sessions.events.send.call_args.kwargs["events"][0]["content"][0]["text"]
        assert "issue created" in brief

        # More events inside the cooldown start nothing
        _issue_event(workspace, project, create_user)
        loops.run_due_loops()
        assert AgentRun.objects.filter(loop=loop).count() == 1

        # Past the cooldown, with the first run finished, the event that waited starts the next run
        AgentRun.objects.filter(loop=loop).update(status="succeeded")
        AgentLoop.objects.filter(pk=loop.pk).update(last_run_at=timezone.now() - timedelta(hours=2))
        loops.run_due_loops()
        assert AgentRun.objects.filter(loop=loop).count() == 2

        # Past the cooldown again, but only events of another type or from the loop's own agent
        AgentRun.objects.filter(loop=loop).update(status="succeeded")
        AgentLoop.objects.filter(pk=loop.pk).update(last_run_at=timezone.now() - timedelta(hours=2))
        loop.refresh_from_db()
        cursor = loop.last_event_id
        _issue_event(workspace, project, create_user, event="milestone")
        newest = _issue_event(workspace, project, agent.user)
        loops.run_due_loops()
        assert AgentRun.objects.filter(loop=loop).count() == 2
        loop.refresh_from_db()
        assert loop.last_event_id > cursor
        assert loop.last_event_id == newest.id

    def test_event_loop_finds_match_behind_many_other_events(self, workspace, project, agent, client, create_user):
        loop = _loop(project, agent, create_user, trigger="event", event_types=["issue"])
        WorkspaceEvent.objects.bulk_create(
            [
                WorkspaceEvent(
                    workspace=workspace,
                    project_id=project.id,
                    event="agent_run",
                    action="step",
                    entity_id=uuid.uuid4(),
                    actor_id=agent.user_id,
                )
                for _ in range(loops.EVENTS_READ_MAX + 20)
            ]
        )
        match = _issue_event(workspace, project, create_user)
        _issue_event(workspace, project, create_user, event="milestone")

        loops.run_due_loops()

        assert AgentRun.objects.filter(loop=loop).count() == 1
        loop.refresh_from_db()
        assert loop.last_event_id == match.id

    def test_event_loop_cursor_skips_past_non_matching_events(self, workspace, project, agent, client, create_user):
        loop = _loop(project, agent, create_user, trigger="event", event_types=["issue"])
        _issue_event(workspace, project, create_user, event="milestone")
        newest = _issue_event(workspace, project, agent.user)

        loops.run_due_loops()

        assert not AgentRun.objects.filter(loop=loop).exists()
        loop.refresh_from_db()
        assert loop.last_event_id == newest.id

    def test_due_loop_skips_while_previous_run_open(self, workspace, project, agent, client, create_user):
        scheduled = _loop(project, agent, create_user, name="Scheduled")
        assert loops.run_loop(scheduled, "manual") is not None
        AgentLoop.objects.filter(pk=scheduled.pk).update(next_run_at=timezone.now() - timedelta(minutes=1))
        listening = _loop(project, agent, create_user, name="Listening", trigger="event", event_types=["issue"])
        assert loops.run_loop(listening, "manual") is not None
        AgentLoop.objects.filter(pk=listening.pk).update(last_run_at=timezone.now() - timedelta(hours=2))
        listening.refresh_from_db()
        cursor = listening.last_event_id
        _issue_event(workspace, project, create_user)

        loops.run_due_loops()

        # The scheduled slot is skipped, not queued
        scheduled.refresh_from_db()
        assert AgentRun.objects.filter(loop=scheduled).count() == 1
        assert scheduled.next_run_at > timezone.now()
        assert scheduled.last_error == "Skipped: the previous run is still open"
        # The event loop keeps its cursor, so the event waits for the open run to end
        listening.refresh_from_db()
        assert AgentRun.objects.filter(loop=listening).count() == 1
        assert listening.last_event_id == cursor

        AgentRun.objects.filter(loop=listening).update(status="succeeded")
        loops.run_due_loops()
        assert AgentRun.objects.filter(loop=listening).count() == 2

    def test_loop_refused_over_limit_records_error(self, workspace, project, agent, client, create_user):
        config = get_config(workspace)
        config.monthly_limit_cents = 100
        config.save()
        loop = _loop(project, agent, create_user)

        assert loops.run_loop(loop, "manual") is None

        loop.refresh_from_db()
        assert loop.is_active is True
        assert loop.last_error == "Monthly AI limit reached"
        assert not AgentRun.objects.filter(loop=loop).exists()

    def test_loop_paused_when_agent_deactivated_or_owner_removed(self, workspace, project, agent, client, create_user):
        owner = _member(workspace, project, "owner@example.com", role=15)
        by_owner = _loop(project, agent, create_user, name="Owned", owner_id=str(owner.id))
        ProjectMember.objects.filter(project=project, member=owner).update(is_active=False)

        assert loops.run_loop(by_owner, "manual") is None
        by_owner.refresh_from_db()
        assert by_owner.is_active is False and by_owner.last_error
        assert not AgentRun.objects.filter(loop=by_owner).exists()

        other = _loop(project, agent, create_user, name="Other")
        agents.deactivate_agent(agent, create_user)
        other.refresh_from_db()
        assert other.is_active is False and other.last_error

    def test_only_project_admin_manages_loops(self, workspace, project, agent, client, create_user):
        member = _member(workspace, project, "member@example.com", role=15)
        body = {
            "name": "Daily triage sweep",
            "agent_id": str(agent.id),
            "trigger": "schedule",
            "schedule": {"every": "day", "at": "08:00"},
            "instructions": "Suggest owners.",
        }

        response = _as(member).post(_url(workspace, project), body, format="json")
        assert response.status_code == 403

        response = _as(create_user).post(_url(workspace, project), body, format="json")
        assert response.status_code == 201, response.data
        loop_id = response.data["id"]
        assert response.data["owner"]["id"] == str(create_user.id)
        assert response.data["next_run_at"] is not None

        assert _as(member).get(_url(workspace, project)).status_code == 200
        external = _as(member).get(f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/loops/")
        assert external.status_code == 200 and [row["id"] for row in external.data] == [loop_id]
        assert (
            _as(member).patch(_url(workspace, project, f"{loop_id}/"), {"is_active": False}, format="json").status_code
            == 403
        )
        assert _as(member).delete(_url(workspace, project, f"{loop_id}/")).status_code == 403
        assert _as(member).post(_url(workspace, project, f"{loop_id}/run/")).status_code == 403

        response = _as(create_user).patch(_url(workspace, project, f"{loop_id}/"), {"is_active": False}, format="json")
        assert response.status_code == 200 and response.data["is_active"] is False
        assert _as(create_user).delete(_url(workspace, project, f"{loop_id}/")).status_code == 204

    def test_run_now_refused_while_open(self, workspace, project, agent, client, create_user):
        loop = _loop(project, agent, create_user)
        api = _as(create_user)

        response = api.post(_url(workspace, project, f"{loop.id}/run/"))
        assert response.status_code == 201, response.data
        assert response.data["issue_id"] is None

        response = api.post(_url(workspace, project, f"{loop.id}/run/"))
        assert response.status_code == 409
        assert AgentRun.objects.filter(loop=loop).count() == 1

        runs = api.get(_url(workspace, project, f"{loop.id}/runs/"))
        assert runs.status_code == 200 and len(runs.data) == 1

    def test_overlapping_due_runs_skip(self, workspace, project, agent, client, create_user):
        loop = _loop(project, agent, create_user)
        AgentLoop.objects.filter(pk=loop.pk).update(next_run_at=timezone.now() - timedelta(minutes=1))
        assert cache.add(loops.DUE_LOCK, 1, 120)
        try:
            loops.run_due_loops()
        finally:
            cache.delete(loops.DUE_LOCK)
        assert not AgentRun.objects.filter(loop=loop).exists()

    def test_same_loop_claimed_twice_starts_one_run(self, workspace, project, agent, client, create_user):
        now = timezone.now()
        scheduled = _loop(project, agent, create_user, name="Scheduled")
        AgentLoop.objects.filter(pk=scheduled.pk).update(next_run_at=now - timedelta(minutes=1))
        # Two sweeps that read the same row: only the first to claim the slot starts a run
        first, second = AgentLoop.objects.get(pk=scheduled.pk), AgentLoop.objects.get(pk=scheduled.pk)
        loops._run_schedule_loop(first, now)
        loops._run_schedule_loop(second, now)
        assert AgentRun.objects.filter(loop=scheduled).count() == 1

        listening = _loop(project, agent, create_user, name="Listening", trigger="event", event_types=["issue"])
        _issue_event(workspace, project, create_user)
        first, second = AgentLoop.objects.get(pk=listening.pk), AgentLoop.objects.get(pk=listening.pk)
        loops._run_event_loop(first, now)
        loops._run_event_loop(second, now)
        assert AgentRun.objects.filter(loop=listening).count() == 1

        # A manual run made from the state a sweep already claimed is refused, not started alongside it
        manual = _loop(project, agent, create_user, name="Manual")
        AgentLoop.objects.filter(pk=manual.pk).update(next_run_at=now - timedelta(minutes=1))
        stale, fresh = AgentLoop.objects.get(pk=manual.pk), AgentLoop.objects.get(pk=manual.pk)
        loops._run_schedule_loop(fresh, now)
        with pytest.raises(agents.AgentError) as error:
            loops.run_now(stale, create_user)
        assert (error.value.status_code, error.value.message) == (409, "The loop is starting already")
        assert AgentRun.objects.filter(loop=manual).count() == 1

    def test_due_lock_released_only_by_its_holder(self, monkeypatch):
        loops.run_due_loops()
        assert cache.get(loops.DUE_LOCK) is None

        # This sweep outlived its lock and another sweep took it: the other sweep's lock stays
        def lock_taken_over():
            cache.set(loops.DUE_LOCK, "another-sweep", 120)
            return AgentLoop.objects.none()

        monkeypatch.setattr(loops, "_due_loops", lock_taken_over)
        try:
            loops.run_due_loops()
            assert cache.get(loops.DUE_LOCK) == "another-sweep"
        finally:
            cache.delete(loops.DUE_LOCK)

    def test_delete_cancels_open_runs(self, workspace, project, agent, client, create_user):
        loop = _loop(project, agent, create_user)
        stuck = loops.run_loop(loop, "manual")
        running = loops.run_loop(loop, "manual")
        real_cancel = managed_agents._cancel_run

        def cancel(run, user):
            if run.pk == stuck.pk:
                raise RuntimeError("session unreachable")
            return real_cancel(run, user)

        with (
            patch.object(managed_agents, "_cancel_run", side_effect=cancel),
            patch.object(managed_agents, "log_exception") as logged,
        ):
            loops.delete_loop(loop, create_user)

        running.refresh_from_db()
        assert running.status == "cancelled"
        assert client.beta.sessions.events.send.call_args.kwargs["events"] == [{"type": "user.interrupt"}]
        # One run failing to cancel is logged and doesn't stop the delete
        assert logged.call_count == 1
        assert not AgentLoop.objects.filter(pk=loop.pk).exists()

    def test_refused_event_start_keeps_cursor(self, workspace, project, agent, client, create_user):
        loop = _loop(project, agent, create_user, trigger="event", event_types=["issue"])
        cursor = loop.last_event_id
        config = get_config(workspace)
        config.monthly_limit_cents = 100
        config.save()
        event = _issue_event(workspace, project, create_user)

        loops.run_due_loops()

        loop.refresh_from_db()
        assert not AgentRun.objects.filter(loop=loop).exists()
        assert loop.last_error == "Monthly AI limit reached"
        assert loop.last_event_id == cursor

        # Once the limit allows it, the next sweep retries the same event
        config.monthly_limit_cents = None
        config.save()
        loops.run_due_loops()
        loop.refresh_from_db()
        assert AgentRun.objects.filter(loop=loop).count() == 1
        assert loop.last_event_id == event.id

    def test_other_agents_events_never_trigger_a_loop(self, workspace, project, agent, client, create_user):
        reviewer, _ = agents.create_agent(
            workspace, {"name": "Reviewer", "owner": str(create_user.id), "project_ids": [str(project.id)]}, create_user
        )
        loop = _loop(project, agent, create_user, trigger="event", event_types=["issue_comment"])
        newest = _issue_event(workspace, project, reviewer.user, event="issue_comment")

        loops.run_due_loops()

        assert not AgentRun.objects.filter(loop=loop).exists()
        loop.refresh_from_db()
        assert loop.last_event_id == newest.id

        # Events with no actor still count
        _issue_event(workspace, project, None, event="issue_comment")
        loops.run_due_loops()
        assert AgentRun.objects.filter(loop=loop).count() == 1
