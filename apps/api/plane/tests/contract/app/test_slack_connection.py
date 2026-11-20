# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Workspace Slack settings endpoint: admin only, never returns the token."""

from unittest.mock import MagicMock, patch

import pytest

from plane.db.models import SlackConnection, WorkspaceMember

URL = "/api/workspaces/test-workspace/slack/"


def _slack(payload):
    response = MagicMock()
    response.json.return_value = payload
    return response


@pytest.mark.contract
@pytest.mark.django_db
class TestSlackConnectionEndpoint:
    def test_connect_status_and_disconnect(self, session_client, workspace):
        assert session_client.get(URL).data["connected"] is False

        def fake_post(url, **kwargs):
            if url.endswith("auth.test"):
                return _slack({"ok": True, "team_id": "T1", "team": "Acme"})
            return _slack({"ok": True, "user": {"id": "U1"}})

        with patch("plane.utils.slack_app.requests.post", side_effect=fake_post):
            response = session_client.put(URL, {"bot_token": "xoxb-abc"}, format="json")
        assert response.status_code == 200
        assert response.data["status"] == "ok"
        assert response.data["team_name"] == "Acme"
        assert response.data["linked_users"] == 1
        assert "xoxb-abc" not in str(session_client.get(URL).data)

        assert session_client.delete(URL).status_code == 204
        assert not SlackConnection.objects.filter(workspace=workspace).exists()

    def test_rejected_token_is_not_stored(self, session_client, workspace):
        with patch("plane.utils.slack_app.requests.post", return_value=_slack({"ok": False, "error": "invalid_auth"})):
            response = session_client.put(URL, {"bot_token": "xoxb-bad"}, format="json")
        assert response.status_code == 400
        assert not SlackConnection.objects.filter(workspace=workspace).exists()

    def test_members_cannot_use_it(self, session_client, workspace, create_user):
        WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(role=15)
        assert session_client.get(URL).status_code == 403
