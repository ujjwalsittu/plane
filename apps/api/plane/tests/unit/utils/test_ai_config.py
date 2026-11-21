# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest.mock import patch

import anthropic
import httpx
import pytest

from plane.db.models import WorkspaceAIConfig
from plane.license.utils.encryption import encrypt_data
from plane.utils import ai_config
from plane.utils.agents import AgentError

WORKSPACE_KEY = "sk-ant-workspace"
INSTANCE_KEY = "sk-ant-instance"


def _auth_error():
    request = httpx.Request("GET", "https://api.anthropic.com/v1/models")
    return anthropic.AuthenticationError("bad key", response=httpx.Response(401, request=request), body=None)


@pytest.fixture(autouse=True)
def _instance_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", INSTANCE_KEY)


def _client_key(client):
    return client.api_key


@pytest.mark.unit
@pytest.mark.django_db
class TestAIConfig:
    def test_workspace_key_preferred_over_instance_key(self, workspace):
        WorkspaceAIConfig.objects.create(
            workspace=workspace, api_key_encrypted=encrypt_data(WORKSPACE_KEY), status="ok"
        )
        assert _client_key(ai_config.anthropic_client_for(workspace)) == WORKSPACE_KEY

    def test_falls_back_to_instance_key_when_unset(self, workspace, monkeypatch):
        assert _client_key(ai_config.anthropic_client_for(workspace)) == INSTANCE_KEY
        monkeypatch.delenv("ANTHROPIC_API_KEY")
        assert ai_config.anthropic_client_for(workspace) is None

    def test_key_unreadable_after_secret_key_change_marks_broken(self, workspace, settings):
        WorkspaceAIConfig.objects.create(
            workspace=workspace, api_key_encrypted=encrypt_data(WORKSPACE_KEY), status="ok"
        )
        settings.SECRET_KEY = "a-different-secret-key"

        # No fallback to the instance key: a broken key has to be noticed.
        assert ai_config.anthropic_client_for(workspace) is None
        config = WorkspaceAIConfig.objects.get(workspace=workspace)
        assert config.status == "broken"
        assert config.last_error == "reconnect"

    def test_rejected_key_is_not_stored(self, workspace, create_user):
        with patch("anthropic.Anthropic") as client_cls:
            client_cls.return_value.models.list.side_effect = _auth_error()
            with pytest.raises(AgentError) as exc:
                ai_config.set_api_key(workspace, "sk-ant-bad", create_user)
        assert exc.value.status_code == 400
        assert exc.value.field == "api_key"
        assert exc.value.message == "That key was rejected by Anthropic"
        assert not WorkspaceAIConfig.objects.filter(workspace=workspace).exclude(api_key_encrypted="").exists()

    def test_accepted_key_is_stored_encrypted(self, workspace, create_user):
        with patch("anthropic.Anthropic") as client_cls:
            ai_config.set_api_key(workspace, WORKSPACE_KEY, create_user)
        client_cls.return_value.models.list.assert_called_once_with(limit=1)
        config = WorkspaceAIConfig.objects.get(workspace=workspace)
        assert config.status == "ok"
        assert config.api_key_encrypted and WORKSPACE_KEY not in config.api_key_encrypted
        assert _client_key(ai_config.anthropic_client_for(workspace)) == WORKSPACE_KEY

    def test_model_for_prefers_workspace_model(self, workspace, settings):
        settings.CLAUDE_MODEL = "claude-default"
        assert ai_config.model_for(workspace) == "claude-default"
        WorkspaceAIConfig.objects.create(workspace=workspace, model="claude-custom")
        assert ai_config.model_for(workspace) == "claude-custom"

    def test_spent_is_zero_without_runs(self, workspace):
        assert ai_config.spent_this_month_cents(workspace) == 0

    def test_check_spend_blocks_over_limit(self, workspace, monkeypatch):
        WorkspaceAIConfig.objects.create(workspace=workspace, monthly_limit_cents=1000)
        monkeypatch.setattr(ai_config, "spent_this_month_cents", lambda ws: 990)

        ai_config.check_spend(workspace, extra_cents=10)
        with pytest.raises(AgentError) as exc:
            ai_config.check_spend(workspace, extra_cents=20)
        assert exc.value.status_code == 409
        assert exc.value.field == "spend_limit_reached"
        assert exc.value.message == "Monthly AI limit reached"

    def test_check_spend_without_limit_never_blocks(self, workspace, monkeypatch):
        monkeypatch.setattr(ai_config, "spent_this_month_cents", lambda ws: 10**9)
        ai_config.check_spend(workspace, extra_cents=10**9)
