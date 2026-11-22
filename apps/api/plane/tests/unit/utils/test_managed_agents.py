# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Cloud agents on Claude Managed Agents: one environment per workspace, one agent and one vault per Plane agent."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from rest_framework.test import APIClient

from plane.bgtasks.cloud_agents_task import sync_cloud_agent
from plane.db.models import APIToken, WorkspaceAgent, WorkspaceAIConfig
from plane.utils import agents, managed_agents
from plane.utils.agents import AgentError

MCP_URL = "https://mcp.plane.example/mcp"
SETTINGS_URL = "/api/workspaces/test-workspace/ai-settings/"
SETUP_URL = f"{SETTINGS_URL}cloud-agents/"


@pytest.fixture(autouse=True)
def _cloud_settings(settings, monkeypatch):
    settings.PLANE_MCP_URL = MCP_URL
    settings.WEB_URL = "https://plane.example.com"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-instance")


@pytest.fixture
def client():
    client = MagicMock()
    client.beta.environments.create.return_value = SimpleNamespace(id="env_1")
    client.beta.agents.create.return_value = SimpleNamespace(id="agent_1", version=1)
    client.beta.agents.update.return_value = SimpleNamespace(id="agent_1", version=2)
    client.beta.vaults.create.return_value = SimpleNamespace(id="vlt_1")
    client.beta.vaults.credentials.create.return_value = SimpleNamespace(id="cred_1")
    client.beta.vaults.credentials.list.return_value = [
        SimpleNamespace(id="cred_1", auth=SimpleNamespace(type="static_bearer", mcp_server_url=MCP_URL))
    ]
    client.with_options.return_value = client
    with patch("plane.utils.managed_agents.anthropic_client_for", return_value=client):
        yield client


@pytest.fixture
def run_tasks(django_capture_on_commit_callbacks):
    """Run queued cloud-agent syncs right away, as the worker would after commit."""

    @contextmanager
    def runner():
        with patch("plane.bgtasks.cloud_agents_task.sync_cloud_agent.delay", side_effect=sync_cloud_agent):
            with django_capture_on_commit_callbacks(execute=True):
                yield

    return runner


def _agent(workspace, owner, name="Builder"):
    return agents.create_agent(workspace, {"name": name, "owner": str(owner.id)}, owner)


def _setup(session_client):
    return session_client.post(SETUP_URL, {}, format="json")


@pytest.mark.unit
@pytest.mark.django_db
class TestManagedAgents:
    def test_setup_creates_environment_once(self, session_client, workspace, create_user, client):
        agent, _ = _agent(workspace, create_user)
        # Before setup, creating an agent never calls Anthropic.
        client.beta.agents.create.assert_not_called()

        response = _setup(session_client)
        assert response.status_code == 200, response.data
        assert response.data["cloud_agents_ready"] is True
        client.beta.environments.create.assert_called_once_with(
            name="plane-test-workspace",
            config={
                "type": "cloud",
                "networking": {
                    "type": "limited",
                    "allow_package_managers": True,
                    "allow_mcp_servers": True,
                    "allowed_hosts": ["plane.example.com", "api.github.com", "github.com"],
                },
            },
        )
        assert WorkspaceAIConfig.objects.get(workspace=workspace).ma_environment_id == "env_1"
        agent.refresh_from_db()
        assert (agent.ma_agent_id, agent.ma_agent_version, agent.ma_vault_id) == ("agent_1", 1, "vlt_1")

        assert _setup(session_client).status_code == 200
        client.beta.environments.create.assert_called_once()
        assert managed_agents.ensure_environment(workspace) == "env_1"
        client.beta.environments.create.assert_called_once()

    def test_agent_sync_declares_plane_mcp_and_disables_web_tools(self, workspace, create_user, client, settings):
        settings.CLAUDE_MODEL = "claude-opus-5-5"
        agent, _ = _agent(workspace, create_user)
        managed_agents.sync_ma_agent(agent)

        kwargs = client.beta.agents.create.call_args.kwargs
        assert kwargs["name"] == "Builder"
        assert kwargs["model"] == "claude-opus-5-5"
        assert "Test Workspace" in kwargs["system"] and "approval_required" in kwargs["system"]
        assert kwargs["mcp_servers"] == [{"type": "url", "name": "plane", "url": MCP_URL}]
        toolset, mcp = kwargs["tools"]
        assert toolset["type"] == "agent_toolset_20260401"
        assert toolset["default_config"]["permission_policy"] == {"type": "always_allow"}
        assert {"name": "web_search", "enabled": False} in toolset["configs"]
        assert {"name": "web_fetch", "enabled": False} in toolset["configs"]
        assert mcp == {
            "type": "mcp_toolset",
            "mcp_server_name": "plane",
            "default_config": {"permission_policy": {"type": "always_allow"}},
        }

        # A second sync updates the same Managed Agents agent instead of making another.
        agent.refresh_from_db()
        managed_agents.sync_ma_agent(agent)
        client.beta.agents.create.assert_called_once()
        assert client.beta.agents.update.call_args.args == ("agent_1",)
        agent.refresh_from_db()
        assert agent.ma_agent_version == 2

    def test_vault_holds_agent_token_for_mcp_url(self, workspace, create_user, client):
        agent, token = _agent(workspace, create_user)
        managed_agents.sync_vault(agent, token)

        client.beta.vaults.create.assert_called_once_with(display_name="plane-test-workspace-Builder")
        client.beta.vaults.credentials.create.assert_called_once_with(
            "vlt_1", auth={"type": "static_bearer", "mcp_server_url": MCP_URL, "token": token}
        )
        agent.refresh_from_db()
        assert agent.ma_vault_id == "vlt_1"

    def test_create_and_rotate_queue_the_sync_with_ids_only(
        self, session_client, workspace, create_user, client, django_capture_on_commit_callbacks
    ):
        assert _setup(session_client).status_code == 200
        with patch("plane.bgtasks.cloud_agents_task.sync_cloud_agent.delay") as delay:
            with django_capture_on_commit_callbacks(execute=True):
                agent, token = _agent(workspace, create_user)
            # Nothing reaches Anthropic in the request; the task gets the agent id and nothing else.
            client.beta.agents.create.assert_not_called()
            client.beta.vaults.create.assert_not_called()
            delay.assert_called_once_with(str(agent.id))

            delay.reset_mock()
            with django_capture_on_commit_callbacks(execute=True):
                new_token = agents.rotate_token(WorkspaceAgent.objects.get(pk=agent.pk), create_user)
            delay.assert_called_once_with(str(agent.id))
            assert token not in str(delay.call_args) and new_token not in str(delay.call_args)
        client.beta.vaults.credentials.create.assert_not_called()

        # The task reads the active token itself and does the sync.
        sync_cloud_agent(str(agent.id))
        client.beta.agents.create.assert_called_once()
        client.beta.vaults.credentials.create.assert_called_once_with(
            "vlt_1", auth={"type": "static_bearer", "mcp_server_url": MCP_URL, "token": new_token}
        )
        assert session_client.get(SETTINGS_URL).data["cloud_agents_ready"] is True

    def test_rotate_token_replaces_vault_credential(self, session_client, workspace, create_user, client, run_tasks):
        agent, _ = _agent(workspace, create_user)
        assert _setup(session_client).status_code == 200
        client.beta.vaults.credentials.create.reset_mock()

        with run_tasks():
            new_token = agents.rotate_token(WorkspaceAgent.objects.get(pk=agent.pk), create_user)

        client.beta.vaults.credentials.archive.assert_called_once_with("cred_1", vault_id="vlt_1")
        client.beta.vaults.credentials.create.assert_called_once_with(
            "vlt_1", auth={"type": "static_bearer", "mcp_server_url": MCP_URL, "token": new_token}
        )
        client.beta.vaults.create.assert_called_once()
        agent.refresh_from_db()
        assert agent.ma_vault_token_id == APIToken.objects.get(token=new_token).id

    def test_agent_update_failure_on_rotate_still_recreates_credential(
        self, session_client, workspace, create_user, client, run_tasks
    ):
        agent, _ = _agent(workspace, create_user)
        assert _setup(session_client).status_code == 200
        client.beta.vaults.credentials.create.reset_mock()
        client.beta.agents.update.side_effect = RuntimeError("outage")

        with run_tasks():
            new_token = agents.rotate_token(WorkspaceAgent.objects.get(pk=agent.pk), create_user)

        client.beta.vaults.credentials.create.assert_called_once_with(
            "vlt_1", auth={"type": "static_bearer", "mcp_server_url": MCP_URL, "token": new_token}
        )
        assert APIToken.objects.get(token=new_token).is_active
        config = WorkspaceAIConfig.objects.get(workspace=workspace)
        assert config.last_error.startswith("cloud_agents") and new_token not in config.last_error

    def test_archive_ok_create_fail_leaves_readiness_false(
        self, session_client, workspace, create_user, client, run_tasks
    ):
        agent, _ = _agent(workspace, create_user)
        assert _setup(session_client).status_code == 200
        assert session_client.get(SETTINGS_URL).data["cloud_agents_ready"] is True
        client.beta.vaults.credentials.create.side_effect = RuntimeError("boom")

        with run_tasks():
            new_token = agents.rotate_token(WorkspaceAgent.objects.get(pk=agent.pk), create_user)

        client.beta.vaults.credentials.archive.assert_called_once()
        assert APIToken.objects.get(token=new_token).is_active
        agent.refresh_from_db()
        assert agent.ma_vault_token_id is None
        assert session_client.get(SETTINGS_URL).data["cloud_agents_ready"] is False

        # Setup repairs it.
        client.beta.vaults.credentials.create.side_effect = None
        assert _setup(session_client).data["cloud_agents_ready"] is True

    def test_deactivation_archives_the_managed_agent(self, session_client, workspace, create_user, client, run_tasks):
        agent, _ = _agent(workspace, create_user)
        assert _setup(session_client).status_code == 200
        with run_tasks():
            agents.deactivate_agent(WorkspaceAgent.objects.get(pk=agent.pk), create_user)
        client.beta.agents.archive.assert_called_once_with("agent_1")
        client.beta.vaults.archive.assert_called_once_with("vlt_1")

    def test_setup_uses_a_short_timeout(self, session_client, workspace, client):
        assert _setup(session_client).status_code == 200
        client.with_options.assert_called_once_with(timeout=managed_agents.SETUP_TIMEOUT_SECONDS, max_retries=0)

    def test_setup_requires_mcp_url_and_key(self, session_client, workspace, settings, monkeypatch):
        settings.PLANE_MCP_URL = ""
        with patch("plane.utils.managed_agents.anthropic_client_for", return_value=MagicMock()) as client_for:
            response = _setup(session_client)
        assert response.status_code == 400 and "cloud_agents" in response.data
        client_for.return_value.beta.environments.create.assert_not_called()

        settings.PLANE_MCP_URL = MCP_URL
        monkeypatch.delenv("ANTHROPIC_API_KEY")
        with pytest.raises(AgentError) as exc:
            managed_agents.setup_cloud_agents(workspace, workspace.owner)
        assert exc.value.status_code == 400 and exc.value.field == "cloud_agents"
        assert not WorkspaceAIConfig.objects.filter(workspace=workspace).exclude(ma_environment_id="").exists()
        assert session_client.get(SETTINGS_URL).data["cloud_agents_ready"] is False

    def test_rename_updates_the_vault_display_name(self, session_client, workspace, create_user, client, run_tasks):
        agent, _ = _agent(workspace, create_user)
        assert _setup(session_client).status_code == 200
        client.beta.vaults.retrieve.return_value = SimpleNamespace(
            id="vlt_1", display_name="plane-test-workspace-Builder"
        )
        with run_tasks():
            agents.update_agent(WorkspaceAgent.objects.get(pk=agent.pk), {"name": "Maker"}, create_user)
        client.beta.vaults.update.assert_called_once_with("vlt_1", display_name="plane-test-workspace-Maker")

        # Already named right: nothing to update
        client.beta.vaults.update.reset_mock()
        client.beta.vaults.retrieve.return_value = SimpleNamespace(
            id="vlt_1", display_name="plane-test-workspace-Maker"
        )
        managed_agents.sync_agent(WorkspaceAgent.objects.get(pk=agent.pk))
        client.beta.vaults.update.assert_not_called()

    def test_model_change_resyncs_cloud_agents(
        self, session_client, workspace, create_user, client, django_capture_on_commit_callbacks
    ):
        first, _ = _agent(workspace, create_user, "One")
        second, _ = _agent(workspace, create_user, "Two")
        deactivated, _ = _agent(workspace, create_user, "Three")
        agents.deactivate_agent(WorkspaceAgent.objects.get(pk=deactivated.pk), create_user)
        model = "claude-opus-4-7"

        # Not set up for cloud agents: nothing queued
        with patch("plane.bgtasks.cloud_agents_task.sync_cloud_agent.delay") as delay:
            with django_capture_on_commit_callbacks(execute=True):
                assert session_client.put(SETTINGS_URL, {"model": model}, format="json").status_code == 200
        delay.assert_not_called()

        assert _setup(session_client).status_code == 200
        with patch("plane.bgtasks.cloud_agents_task.sync_cloud_agent.delay") as delay:
            with django_capture_on_commit_callbacks(execute=True):
                response = session_client.put(SETTINGS_URL, {"model": "claude-sonnet-4-6"}, format="json")
            assert response.status_code == 200, response.data
            assert sorted(c.args[0] for c in delay.call_args_list) == sorted([str(first.id), str(second.id)])

            # A limit-only change does not resync
            delay.reset_mock()
            with django_capture_on_commit_callbacks(execute=True):
                session_client.put(SETTINGS_URL, {"monthly_limit_cents": 5000}, format="json")
            delay.assert_not_called()

            # A new key does
            with patch("anthropic.Anthropic"), django_capture_on_commit_callbacks(execute=True):
                assert session_client.put(SETTINGS_URL, {"api_key": "sk-ant-new-key"}, format="json").status_code == 200
            assert delay.call_count == 2


@pytest.mark.contract
@pytest.mark.django_db
def test_users_me_reports_token_workspace(workspace, create_user, api_key_client):
    # A token with no workspace: nothing new in the response.
    response = api_key_client.get("/api/v1/users/me/")
    assert response.status_code == 200
    assert "token_workspace_slug" not in response.data

    _, token = _agent(workspace, create_user)
    agent_client = APIClient()
    agent_client.credentials(HTTP_X_API_KEY=token)
    response = agent_client.get("/api/v1/users/me/")
    assert response.status_code == 200
    assert response.data["token_workspace_slug"] == "test-workspace"
    assert response.data["display_name"] == "Builder"
