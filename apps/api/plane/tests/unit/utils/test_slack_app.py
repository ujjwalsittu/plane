# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import hashlib
import hmac
import time
from unittest.mock import MagicMock, patch

import pytest

from plane.db.models import SlackConnection, SlackUserLink, User, WorkspaceMember
from plane.utils import slack_app

TOKEN = "xoxb-secret-token"


def _resp(payload):
    response = MagicMock()
    response.json.return_value = payload
    return response


def _connect(workspace):
    with patch("plane.utils.slack_app.requests.post") as post:
        post.return_value = _resp({"ok": True, "team_id": "T1", "team": "Acme"})
        return slack_app.connect(workspace, TOKEN), post


@pytest.mark.unit
@pytest.mark.django_db
class TestSlackApp:
    def test_connect_stores_encrypted_token(self, workspace):
        connection, post = _connect(workspace)

        assert connection.status == "ok"
        assert connection.team_id == "T1"
        assert connection.team_name == "Acme"
        assert connection.bot_token_encrypted
        assert TOKEN not in connection.bot_token_encrypted
        assert slack_app.bot_token(connection) == TOKEN
        assert post.call_args.kwargs["timeout"] == 10
        assert post.call_args.args[0] == "https://slack.com/api/auth.test"

    def test_revoked_token_marks_broken(self, workspace):
        connection, _ = _connect(workspace)
        with patch("plane.utils.slack_app.requests.post") as post:
            post.return_value = _resp({"ok": False, "error": "token_revoked"})
            result = slack_app.slack_call(connection, "chat.postMessage", channel="C1")

        connection.refresh_from_db()
        assert result["ok"] is False
        assert connection.status == "broken"
        assert connection.last_error == "token_revoked"

    def test_link_users_by_email(self, workspace, create_user):
        other = User.objects.create(email="other@example.com", username="other")
        WorkspaceMember.objects.create(workspace=workspace, member=other, role=15)
        connection, _ = _connect(workspace)

        def fake_post(url, **kwargs):
            email = kwargs["data"]["email"]
            if email == create_user.email:
                return _resp({"ok": True, "user": {"id": "U1"}})
            return _resp({"ok": False, "error": "users_not_found"})

        with patch("plane.utils.slack_app.requests.post", side_effect=fake_post):
            count = slack_app.link_users(connection)

        assert count == 1
        link = SlackUserLink.objects.get(workspace=workspace)
        assert link.user == create_user
        assert link.slack_user_id == "U1"

    def test_verify_signature_rejects_old_or_wrong(self, settings):
        settings.SLACK_SIGNING_SECRET = "shh"
        body = b"payload=1"

        def sign(ts, secret="shh"):
            digest = hmac.new(secret.encode(), f"v0:{ts}:".encode() + body, hashlib.sha256).hexdigest()
            return f"v0={digest}"

        now = str(int(time.time()))
        good = {"X-Slack-Request-Timestamp": now, "X-Slack-Signature": sign(now)}
        assert slack_app.verify_signature(good, body) is True

        wrong = {"X-Slack-Request-Timestamp": now, "X-Slack-Signature": sign(now, "nope")}
        assert slack_app.verify_signature(wrong, body) is False

        old = str(int(time.time()) - 60 * 6)
        stale = {"X-Slack-Request-Timestamp": old, "X-Slack-Signature": sign(old)}
        assert slack_app.verify_signature(stale, body) is False

        assert slack_app.verify_signature({}, body) is False
        settings.SLACK_SIGNING_SECRET = ""
        assert slack_app.verify_signature(good, body) is False

    def test_connection_status_after_secret_key_change(self, workspace, settings):
        connection, _ = _connect(workspace)
        settings.SECRET_KEY = "a-completely-different-secret-key"

        assert slack_app.bot_token(connection) is None

        connection.refresh_from_db()
        assert connection.status == "broken"
        assert connection.last_error == "reconnect"
        assert SlackConnection.objects.filter(workspace=workspace).count() == 1
