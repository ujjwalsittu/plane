# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Workspace AI settings endpoint: admin only, never returns the key."""

from unittest.mock import patch

import pytest

from plane.db.models import WorkspaceAIConfig, WorkspaceMember

URL = "/api/workspaces/test-workspace/ai-settings/"


@pytest.mark.contract
@pytest.mark.django_db
class TestAISettingsEndpoint:
    def test_set_read_and_clear(self, session_client, workspace, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        body = session_client.get(URL).data
        assert body["has_key"] is False and body["status"] == "unset" and body["cloud_agents_ready"] is False

        with patch("anthropic.Anthropic"):
            response = session_client.put(
                URL, {"api_key": "sk-ant-secret", "model": "claude-x", "monthly_limit_cents": 5000}, format="json"
            )
        assert response.status_code == 200
        assert response.data["has_key"] is True and response.data["status"] == "ok"
        assert response.data["model"] == "claude-x" and response.data["monthly_limit_cents"] == 5000
        # A key alone isn't enough: cloud agents need their own setup (see test_managed_agents).
        assert response.data["spent_this_month_cents"] == 0 and response.data["cloud_agents_ready"] is False
        assert "sk-ant-secret" not in str(session_client.get(URL).data)

        response = session_client.put(URL, {"monthly_limit_cents": None}, format="json")
        assert response.data["monthly_limit_cents"] is None and response.data["has_key"] is True

        response = session_client.delete(URL)
        assert response.status_code == 200
        assert response.data["has_key"] is False and response.data["status"] == "unset"
        assert not WorkspaceAIConfig.objects.get(workspace=workspace).api_key_encrypted

    def test_invalid_values_are_rejected_and_nothing_is_saved(self, session_client, workspace):
        response = session_client.put(URL, {"model": "claude-x", "monthly_limit_cents": -5}, format="json")
        assert response.status_code == 400 and "monthly_limit_cents" in response.data
        assert session_client.put(URL, {"monthly_limit_cents": "10"}, format="json").status_code == 400
        assert session_client.get(URL).data["model"] == ""

    def test_members_cannot_use_it(self, session_client, workspace, create_user):
        WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(role=15)
        assert session_client.get(URL).status_code == 403
        assert session_client.put(URL, {"model": "x"}, format="json").status_code == 403
        assert session_client.delete(URL).status_code == 403
