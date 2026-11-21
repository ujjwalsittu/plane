# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Delegating a work item to a cloud agent: the session start, the run-log sync, follow-ups and cancelling."""

from datetime import timedelta
from unittest.mock import MagicMock, create_autospec, patch

import anthropic
import httpx
import pytest
from anthropic.resources.beta.sessions.events import Events
from anthropic.resources.beta.sessions.sessions import Sessions
from anthropic.types.beta import BetaManagedAgentsSession, BetaManagedAgentsSessionUsage
from anthropic.types.beta import sessions as ev
from anthropic.types.beta_monetary_amount import BetaMonetaryAmount
from django.utils import timezone
from rest_framework.test import APIClient

from plane.bgtasks import agent_runs_task
from plane.db.models import (
    AgentRun,
    DecisionRequest,
    GitHubInstallation,
    GitHubRepositoryLink,
    GitHubWorkItemLink,
    Issue,
    IssueComment,
    Milestone,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceAIConfig,
    WorkspaceMember,
)
from plane.utils import agent_runs, agents, managed_agents
from plane.utils.agents import AgentError
from plane.utils.ai_config import get_config


@pytest.fixture(autouse=True)
def _settings(settings, monkeypatch):
    settings.WEB_URL = "https://plane.example.com"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-instance")


@pytest.fixture
def client():
    """An Anthropic client whose session resources are spec'd on the installed SDK, so a mistyped call fails."""
    client = MagicMock()
    client.with_options.return_value = client
    client.beta.sessions = create_autospec(Sessions, instance=True)
    client.beta.sessions.events = create_autospec(Events, instance=True)
    client.beta.sessions.create.return_value = BetaManagedAgentsSession.model_construct(id="sesn_1", status="idle")
    client.beta.sessions.events.list.return_value = []
    with patch("plane.utils.managed_agents.anthropic_client_for", return_value=client):
        yield client


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(name="Alpha", identifier="ALP", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


@pytest.fixture
def issue(project):
    state = State.objects.create(name="Started", group="started", project=project, workspace=project.workspace)
    return Issue.objects.create(
        name="Fix the login bug",
        project=project,
        workspace=project.workspace,
        state=state,
        priority="high",
        description_html="<p>Users get logged out after 5 minutes.</p>",
    )


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


def _app(workspace, project, issue, suffix):
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/agent-runs/{suffix}"


def _ext(workspace, project, issue, suffix):
    return f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/work-items/{issue.id}/agent-runs/{suffix}"


def _api_error(cls, code):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/sessions")
    return cls("boom", response=httpx.Response(code, request=request), body=None)


def _text(text):
    return [ev.BetaManagedAgentsTextBlock.model_construct(type="text", text=text)]


def _message(eid, text):
    return ev.BetaManagedAgentsAgentMessageEvent.model_construct(id=eid, type="agent.message", content=_text(text))


def _user_message(eid):
    return ev.BetaManagedAgentsUserMessageEvent.model_construct(id=eid, type="user.message", content=_text("brief"))


def _idle(eid, reason, event_ids=None):
    stop = {
        "end_turn": ev.BetaManagedAgentsSessionEndTurn,
        "budget_reached": ev.BetaManagedAgentsSessionBudgetReached,
        "requires_action": ev.BetaManagedAgentsSessionRequiresAction,
    }[reason].model_construct(type=reason, **({"event_ids": event_ids} if event_ids else {}))
    return ev.BetaManagedAgentsSessionStatusIdleEvent.model_construct(
        id=eid, type="session.status_idle", stop_reason=stop
    )


def _session(status, cents="0", input_tokens=0, output_tokens=0):
    usage = BetaManagedAgentsSessionUsage.model_construct(
        list_cost=BetaMonetaryAmount.model_construct(amount=cents, currency="USD"),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    return BetaManagedAgentsSession.model_construct(id="sesn_1", status=status, usage=usage)


def _running_run(issue, agent, user, session_id="sesn_1", status="running"):
    now = timezone.now()
    return AgentRun.objects.create(
        project=issue.project,
        issue=issue,
        agent=agent,
        actor=agent.user,
        delegated_by=user,
        kind="managed",
        status=status,
        external_session_id=session_id,
        started_at=now,
        last_event_at=now,
    )


@pytest.mark.unit
@pytest.mark.django_db
class TestManagedRuns:
    def test_delegate_starts_session_with_brief_budget_and_repos(
        self, session_client, workspace, project, issue, agent, client, create_user
    ):
        milestone = Milestone.objects.create(title="Beta launch", project=project, workspace=workspace)
        Issue.objects.filter(pk=issue.pk).update(milestone=milestone)
        IssueComment.objects.create(
            issue=issue, project=project, workspace=workspace, actor=create_user, comment_html="<p>Seen on Safari</p>"
        )
        DecisionRequest.objects.create(
            issue=issue, project=project, workspace=workspace, asked_user=create_user, question="Keep the 5 min TTL?"
        )
        GitHubWorkItemLink.objects.create(
            issue=issue,
            project=project,
            workspace=workspace,
            kind=GitHubWorkItemLink.PULL_REQUEST,
            repository_id=1,
            repository_full_name="acme/web",
            ref="42",
            title="Session refresh",
            url="https://github.com/acme/web/pull/42",
        )
        installation = GitHubInstallation.objects.create(workspace=workspace, installation_id=77, account_login="acme")
        for number, name in enumerate(["acme/web", "acme/api", "acme/docs", "acme/zeta"]):
            GitHubRepositoryLink.objects.create(
                project=project,
                workspace=workspace,
                installation=installation,
                repository_id=number + 1,
                full_name=name,
                html_url=f"https://github.com/{name}",
            )

        with (
            patch("plane.utils.github_app.is_configured", return_value=True),
            patch("plane.utils.github_app.forget_installation_token") as forget,
            patch("plane.utils.github_app.installation_token", return_value="ghs_fresh") as token,
        ):
            response = session_client.post(
                _app(workspace, project, issue, "delegate/"),
                {"agent_id": str(agent.id), "instructions": "Keep the fix small."},
                format="json",
            )

        assert response.status_code == 201, response.data
        run = AgentRun.objects.get(pk=response.data["id"])
        assert (run.kind, run.status, run.agent_id, run.actor_id) == ("managed", "queued", agent.id, agent.user_id)
        assert run.delegated_by_id == create_user.id and run.instructions == "Keep the fix small."
        assert run.external_session_id == "sesn_1"
        assert run.external_url == "https://platform.claude.com/workspaces/default/sessions/sesn_1"
        forget.assert_called_once_with(77)
        token.assert_called_with(77)

        kwargs = client.beta.sessions.create.call_args.kwargs
        assert kwargs["agent"] == {"type": "agent", "id": "agent_1", "version": 3}
        assert kwargs["environment_id"] == "env_1" and kwargs["vault_ids"] == ["vlt_1"]
        assert kwargs["title"] == "ALP-1: Fix the login bug"
        assert kwargs["metadata"] == {"plane_run_id": str(run.id), "plane_workspace": "test-workspace"}
        assert kwargs["budget"] == {"type": "limit", "max_list_cost": {"amount": "500", "currency": "USD"}}
        assert kwargs["resources"] == [
            {
                "type": "github_repository",
                "url": f"https://github.com/acme/{name}",
                "authorization_token": "ghs_fresh",
                "mount_path": f"/workspace/{name}",
            }
            for name in ("api", "docs", "web")
        ]

        args, send = client.beta.sessions.events.send.call_args
        assert args == ("sesn_1",)
        (message,) = send["events"]
        assert message["type"] == "user.message"
        brief = message["content"][0]["text"]
        for expected in (
            "ALP-1: Fix the login bug",
            "https://plane.example.com/test-workspace/browse/ALP-1/",
            "State: Started (started)",
            "Priority: high",
            "Milestone: Beta launch",
            "Users get logged out after 5 minutes.",
            "Seen on Safari",
            "Keep the 5 min TTL?",
            "acme/web#42 Session refresh https://github.com/acme/web/pull/42",
            "Keep the fix small.",
        ):
            assert expected in brief, expected
        assert brief.rstrip().endswith("Keep the fix small.")

    def test_start_refused_without_key_or_over_limit(self, workspace, project, issue, agent, create_user, client):
        def refused(field, code, who=create_user, target=agent):
            with pytest.raises(AgentError) as exc:
                managed_agents.start_managed_run(issue, target, who)
            assert (exc.value.field, exc.value.status_code) == (field, code)

        with patch("plane.utils.managed_agents.anthropic_client_for", return_value=None):
            refused("cloud_agents", 400)
        config = WorkspaceAIConfig.objects.get(workspace=workspace)
        config.ma_environment_id = ""
        config.save()
        refused("cloud_agents", 400)
        config.ma_environment_id = "env_1"
        config.monthly_limit_cents = 100
        config.save()
        refused("spend_limit_reached", 409)
        config.monthly_limit_cents = None
        config.save()

        guest = _member(workspace, project, "guest@example.com", role=5)
        refused("error", 403, who=guest)
        other = Project.objects.create(name="Beta", identifier="BET", workspace=workspace, created_by=create_user)
        ProjectMember.objects.create(project=other, member=create_user, workspace=workspace, role=20)
        outsider, _ = agents.create_agent(workspace, {"name": "Outsider", "owner": str(create_user.id)}, create_user)
        refused("agent_id", 400, target=outsider)
        agents.deactivate_agent(agent, create_user)
        refused("agent_id", 400)

        assert AgentRun.objects.count() == 0
        client.beta.sessions.create.assert_not_called()

        # Through the API too: a guest is turned away and nothing starts.
        response = _as(guest).post(_ext(workspace, project, issue, "delegate/"), {"agent_id": str(agent.id)})
        assert response.status_code == 403 and AgentRun.objects.count() == 0

    def test_start_marks_failed_when_api_errors(self, workspace, project, issue, agent, create_user, client):
        client.beta.sessions.create.side_effect = _api_error(anthropic.InternalServerError, 500)
        run = managed_agents.start_managed_run(issue, agent, create_user, "Go")
        run.refresh_from_db()
        assert run.status == "failed" and run.ended_at is not None
        assert run.error == "Could not start the cloud session (InternalServerError 500)"
        assert client.beta.sessions.create.call_count == 1
        client.beta.sessions.events.send.assert_not_called()
        client.with_options.assert_called_once_with(max_retries=0)

        # The session started but the brief could not be sent: the run fails and keeps its session id.
        client.beta.sessions.create.side_effect = None
        client.beta.sessions.events.send.side_effect = _api_error(anthropic.RateLimitError, 429)
        run = managed_agents.start_managed_run(issue, agent, create_user)
        run.refresh_from_db()
        assert (run.status, run.external_session_id) == ("failed", "sesn_1")
        assert "RateLimitError 429" in run.error

    def test_sync_maps_events_to_steps_and_finishes_with_cost(self, issue, agent, create_user, client):
        run = _running_run(issue, agent, create_user, status="queued")
        push = (
            "Enumerating objects: 5, done.\n"
            "To https://github.com/acme/web.git\n"
            " * [new branch]      fix/login -> fix/login\n"
        )
        events = [
            _user_message("sevt_0"),
            ev.BetaManagedAgentsSessionStatusRunningEvent.model_construct(id="sevt_1", type="session.status_running"),
            _message("sevt_2", "Reading the auth module"),
            ev.BetaManagedAgentsAgentToolUseEvent.model_construct(
                id="sevt_3", type="agent.tool_use", name="bash", input={"command": "git push -u origin fix/login"}
            ),
            ev.BetaManagedAgentsAgentToolResultEvent.model_construct(
                id="sevt_4", type="agent.tool_result", tool_use_id="sevt_3", content=_text(push)
            ),
            ev.BetaManagedAgentsAgentMCPToolUseEvent.model_construct(
                id="sevt_5",
                type="agent.mcp_tool_use",
                mcp_server_name="plane",
                name="create_comment",
                input={"text": "Opened a PR"},
            ),
            ev.BetaManagedAgentsAgentToolResultEvent.model_construct(
                id="sevt_6",
                type="agent.tool_result",
                tool_use_id="sevt_3",
                content=_text('{"html_url": "https://github.com/acme/web/pull/43", "number": 43}'),
            ),
            ev.BetaManagedAgentsSessionErrorEvent.model_construct(
                id="sevt_7",
                type="session.error",
                error=ev.BetaManagedAgentsUnknownError.model_construct(type="unknown_error", message="MCP hiccup"),
            ),
            _message("sevt_8", "Done: opened acme/web#43"),
            _idle("sevt_9", "end_turn"),
        ]
        client.beta.sessions.events.list.return_value = events
        client.beta.sessions.retrieve.return_value = _session("idle", "137", 1000, 200)

        agent_runs_task.sync_agent_runs()

        client.beta.sessions.events.list.assert_called_with("sesn_1", order="asc", limit=100)
        run.refresh_from_db()
        steps = [(s.kind, s.text) for s in run.steps.order_by("seq")]
        assert steps == [
            ("message", "Reading the auth module"),
            ("tool", 'bash {"command": "git push -u origin fix/login"}'),
            ("commit", "Pushed fix/login to acme/web"),
            ("tool", 'plane.create_comment {"text": "Opened a PR"}'),
            ("pr", "Pull request https://github.com/acme/web/pull/43"),
            ("error", "MCP hiccup"),
            ("message", "Done: opened acme/web#43"),
        ]
        assert run.status == "succeeded" and run.summary == "Done: opened acme/web#43"
        assert run.cost_cents == 137 and (run.input_tokens, run.output_tokens) == (1000, 200)

    def test_sync_denies_confirmations_and_stops_at_budget(self, issue, agent, create_user, client):
        run = _running_run(issue, agent, create_user)
        asking = [_user_message("sevt_0"), _idle("sevt_1", "requires_action", ["sevt_x"])]
        client.beta.sessions.events.list.return_value = asking
        client.beta.sessions.retrieve.return_value = _session("idle", "20")
        managed_agents.sync_run(run)
        managed_agents.sync_run(run)
        client.beta.sessions.events.send.assert_called_once_with(
            "sesn_1",
            events=[
                {
                    "type": "user.tool_confirmation",
                    "tool_use_id": "sevt_x",
                    "result": "deny",
                    "deny_message": managed_agents.DENY_MESSAGE,
                }
            ],
        )
        run.refresh_from_db()
        assert run.status == "running" and [s.kind for s in run.steps.all()] == ["error"]

        client.beta.sessions.events.list.return_value = [_user_message("sevt_0"), _idle("sevt_2", "budget_reached")]
        client.beta.sessions.retrieve.return_value = _session("idle", "512")
        managed_agents.sync_run(run)
        run.refresh_from_db()
        assert (run.status, run.error, run.cost_cents) == ("failed", "Run budget reached", 512)

    def test_sync_is_idempotent_and_ends_lost_runs(self, issue, agent, create_user, client):
        run = _running_run(issue, agent, create_user)
        lost = _running_run(issue, agent, create_user, session_id="sesn_lost")
        stalled = _running_run(issue, agent, create_user, session_id="sesn_stalled")
        broken = _running_run(issue, agent, create_user, session_id="sesn_broken")
        AgentRun.objects.filter(pk=stalled.pk).update(last_event_at=timezone.now() - timedelta(hours=7))
        events = [_user_message("sevt_0"), _message("sevt_1", "Working on it")]

        def listing(session_id, **kwargs):
            if session_id == "sesn_lost":
                raise _api_error(anthropic.NotFoundError, 404)
            if session_id == "sesn_broken":
                raise RuntimeError("bad payload")
            return events if session_id == "sesn_1" else []

        client.beta.sessions.events.list.side_effect = listing
        client.beta.sessions.retrieve.return_value = _session("running", "12")

        agent_runs_task.sync_agent_runs()
        agent_runs_task.sync_agent_runs()

        run.refresh_from_db()
        assert run.status == "running" and run.cost_cents == 12
        assert [s.text for s in run.steps.all()] == ["Working on it"]
        lost.refresh_from_db()
        assert (lost.status, lost.error) == ("failed", "Session no longer exists")
        stalled.refresh_from_db()
        assert (stalled.status, stalled.error) == ("failed", "No progress for 6 hours")
        client.beta.sessions.events.send.assert_called_once_with("sesn_stalled", events=[{"type": "user.interrupt"}])
        # A run whose sync blew up is left as it was; the others were still synced.
        broken.refresh_from_db()
        assert broken.status == "running"

    def test_deactivating_agent_cancels_running_runs(
        self, issue, agent, create_user, client, django_capture_on_commit_callbacks
    ):
        running = _running_run(issue, agent, create_user)
        waiting = _running_run(issue, agent, create_user, session_id="sesn_2", status="waiting")
        done = _running_run(issue, agent, create_user, session_id="sesn_3", status="succeeded")
        with (
            patch("plane.bgtasks.cloud_agents_task.sync_cloud_agent.delay") as archive,
            patch(
                "plane.bgtasks.agent_runs_task.interrupt_sessions.delay",
                side_effect=agent_runs_task.interrupt_sessions,
            ),
            django_capture_on_commit_callbacks(execute=True),
        ):
            agents.deactivate_agent(agent, create_user)

        archive.assert_called_once_with(str(agent.id))
        for run in (running, waiting):
            run.refresh_from_db()
            assert run.status == "cancelled" and run.ended_at is not None
        done.refresh_from_db()
        assert done.status == "succeeded"
        sent = [c.args[0] for c in client.beta.sessions.events.send.call_args_list]
        assert sorted(sent) == ["sesn_1", "sesn_2"]
        for call in client.beta.sessions.events.send.call_args_list:
            assert call.kwargs == {"events": [{"type": "user.interrupt"}]}

    def test_follow_up_and_cancel(self, session_client, workspace, project, issue, agent, create_user, client):
        run = _running_run(issue, agent, create_user)
        follow = _app(workspace, project, issue, f"{run.id}/follow-up/")
        cancel = _app(workspace, project, issue, f"{run.id}/cancel/")

        assert session_client.post(follow, {"text": "Also add a test"}, format="json").status_code == 409
        agent_runs.finish_run(run, "succeeded", summary="Fixed")
        assert session_client.post(follow, {"text": ""}, format="json").status_code == 400

        response = session_client.post(follow, {"text": "Also add a test"}, format="json")
        assert response.status_code == 200, response.data
        assert response.data["status"] == "running" and response.data["ended_at"] is None
        client.beta.sessions.events.send.assert_called_once_with(
            "sesn_1", events=[{"type": "user.message", "content": [{"type": "text", "text": "Also add a test"}]}]
        )
        assert response.data["steps"][-1]["kind"] == "status"

        guest = _member(workspace, project, "guest@example.com", role=5)
        guest_cancel = _ext(workspace, project, issue, f"{run.id}/cancel/")
        assert _as(guest).post(guest_cancel).status_code == 403

        response = session_client.post(cancel)
        assert response.status_code == 200, response.data
        assert response.data["status"] == "cancelled"
        client.beta.sessions.events.send.assert_called_with("sesn_1", events=[{"type": "user.interrupt"}])
        assert session_client.post(cancel).status_code == 409

    def test_run_helpers_guard_finished_runs(self, issue, agent, create_user):
        run = _running_run(issue, agent, create_user)
        with pytest.raises(AgentError) as exc:
            agent_runs.update_run(run, {"status": "queued"}, agent.user)
        assert exc.value.status_code == 400
        before = run.last_event_at
        agent_runs.update_run(run, {"status": "waiting"}, agent.user)
        assert run.status == "waiting" and run.last_event_at > before

        agent_runs.update_managed_run(run, status="running", input_tokens=5, cost_cents=3)
        run.refresh_from_db()
        assert (run.status, run.input_tokens, run.cost_cents) == ("running", 5, 3)
        with pytest.raises(AgentError):
            agent_runs.update_managed_run(run, status="succeeded")

        # A finish that lands while the caller still holds the old row: the step is refused.
        stale = AgentRun.objects.get(pk=run.pk)
        agent_runs.finish_run(run, "failed", error="x")
        with pytest.raises(AgentError) as exc:
            agent_runs.add_step(stale, "message", "late")
        assert exc.value.status_code == 409
        with pytest.raises(AgentError) as exc:
            agent_runs.finish_run(stale, "succeeded")
        assert exc.value.status_code == 409

    def test_stalled_runs_end_even_when_sync_keeps_failing(self, workspace, issue, agent, create_user, client):
        no_key = _running_run(issue, agent, create_user, session_id="sesn_no_key")
        AgentRun.objects.filter(pk=no_key.pk).update(last_event_at=timezone.now() - timedelta(hours=7))
        with patch("plane.utils.managed_agents.anthropic_client_for", return_value=None):
            agent_runs_task.sync_agent_runs()
        no_key.refresh_from_db()
        assert (no_key.status, no_key.error) == ("failed", "No progress for 6 hours")

        revoked = _running_run(issue, agent, create_user, session_id="sesn_revoked")
        fresh = _running_run(issue, agent, create_user, session_id="sesn_fresh")
        AgentRun.objects.filter(pk=revoked.pk).update(last_event_at=timezone.now() - timedelta(hours=7))
        client.beta.sessions.events.list.side_effect = _api_error(anthropic.AuthenticationError, 401)
        client.beta.sessions.events.send.side_effect = _api_error(anthropic.AuthenticationError, 401)
        agent_runs_task.sync_agent_runs()
        agent_runs_task.sync_agent_runs()
        revoked.refresh_from_db()
        assert (revoked.status, revoked.error) == ("failed", "No progress for 6 hours")
        # The interrupt was tried (and failed), which never keeps the run open
        client.beta.sessions.events.send.assert_called_once_with("sesn_revoked", events=[{"type": "user.interrupt"}])
        fresh.refresh_from_db()
        assert fresh.status == "running"

    def test_runs_without_a_session_never_stay_queued(self, workspace, project, issue, agent, create_user, client):
        with patch("plane.utils.managed_agents._repository_resources", side_effect=RuntimeError("boom")):
            run = managed_agents.start_managed_run(issue, agent, create_user)
        run.refresh_from_db()
        assert (run.status, run.error) == ("failed", "Could not start the cloud session (RuntimeError)")
        client.beta.sessions.create.assert_not_called()

        # A run left queued with no session (the request died) can be cancelled, without any interrupt...
        orphan = _running_run(issue, agent, create_user, session_id="", status="queued")
        assert managed_agents.cancel_run(orphan, create_user).status == "cancelled"
        client.beta.sessions.events.send.assert_not_called()

        # ...and the beat fails one after 5 minutes, leaving a run still starting alone.
        old = _running_run(issue, agent, create_user, session_id="", status="queued")
        starting = _running_run(issue, agent, create_user, session_id="", status="queued")
        AgentRun.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(minutes=6))
        agent_runs_task.sync_agent_runs()
        old.refresh_from_db()
        starting.refresh_from_db()
        assert (old.status, old.error) == ("failed", "The cloud session never started")
        assert starting.status == "queued"

    def test_follow_up_never_races_an_in_flight_sync(self, issue, agent, create_user, client):
        run = _running_run(issue, agent, create_user, status="waiting")
        attempts = []

        def listing(session_id, **kwargs):
            # A person follows up (and another cancels) while the sync works from this list
            for action in (
                lambda: managed_agents.send_follow_up(run, create_user, "More please"),
                lambda: managed_agents.cancel_run(run, create_user),
            ):
                with pytest.raises(AgentError) as exc:
                    action()
                attempts.append((exc.value.status_code, exc.value.message))
            return [_user_message("sevt_0"), _message("sevt_1", "All done"), _idle("sevt_2", "end_turn")]

        client.beta.sessions.events.list.side_effect = listing
        client.beta.sessions.retrieve.return_value = _session("idle", "40")
        with patch("plane.utils.managed_agents.LOCK_WAIT_SECONDS", 0):
            managed_agents.sync_run(run)

        message = "The run is syncing with its session, try again in a moment"
        assert attempts == [(409, message), (409, message)]
        client.beta.sessions.events.send.assert_not_called()
        run.refresh_from_db()
        assert (run.status, run.summary) == ("succeeded", "All done")

        # Once the sync is done the follow-up goes through and reopens the run; the session's next listing
        # carries the follow-up, so the old end_turn no longer counts.
        client.beta.sessions.events.list.side_effect = None
        managed_agents.send_follow_up(run, create_user, "More please")
        run.refresh_from_db()
        assert run.status == "running"
        client.beta.sessions.events.list.return_value = [
            _user_message("sevt_0"),
            _message("sevt_1", "All done"),
            _idle("sevt_2", "end_turn"),
            _user_message("sevt_3"),
        ]
        client.beta.sessions.retrieve.return_value = _session("running", "41")
        managed_agents.sync_run(run)
        run.refresh_from_db()
        assert run.status == "running"

    def test_deactivation_still_archives_when_cancelling_fails(
        self, issue, agent, create_user, client, django_capture_on_commit_callbacks
    ):
        with (
            patch("plane.utils.managed_agents.cancel_agent_runs", side_effect=RuntimeError("boom")),
            patch("plane.utils.agents.log_exception") as logged,
            patch("plane.bgtasks.cloud_agents_task.sync_cloud_agent.delay") as archive,
            django_capture_on_commit_callbacks(execute=True),
        ):
            agents.deactivate_agent(agent, create_user)
        agent.refresh_from_db()
        assert agent.is_active is False
        archive.assert_called_once_with(str(agent.id))
        logged.assert_called_once()

    def test_overlapping_syncs_skip(self, issue, agent, create_user, client):
        from django.core.cache import cache

        run = _running_run(issue, agent, create_user)
        with patch("plane.utils.managed_agents.sync_run") as sync:
            # Another sync is still going: this one does nothing
            assert cache.add(agent_runs_task.SYNC_ALL_LOCK, 1, 60)
            try:
                agent_runs_task.sync_agent_runs()
                sync.assert_not_called()
            finally:
                cache.delete(agent_runs_task.SYNC_ALL_LOCK)
            # Free again: it runs, and releases the lock when done (even if a run fails)
            sync.side_effect = RuntimeError("boom")
            agent_runs_task.sync_agent_runs()
            agent_runs_task.sync_agent_runs()
        assert [c.args[0].pk for c in sync.call_args_list] == [run.pk, run.pk]
        assert cache.get(agent_runs_task.SYNC_ALL_LOCK) is None

    def test_sync_beat_entry_expires(self):
        from plane.celery import app

        entry = app.conf.beat_schedule["sync-agent-runs"]
        assert entry["options"] == {"expires": 14}
