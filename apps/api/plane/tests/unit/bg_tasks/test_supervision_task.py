# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Slack daily brief, milestone alerts, decision DMs and the Slack interactivity endpoint."""

import hashlib
import hmac
import json
from datetime import date, datetime
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import pytest

from plane.bgtasks import supervision_task
from plane.db.models import (
    BriefVisit,
    DecisionRequest,
    Issue,
    IssueAssignee,
    Milestone,
    Notification,
    Project,
    ProjectMember,
    SlackConnection,
    SlackUserLink,
    State,
    User,
)
from plane.utils import slack_app
from plane.utils.brief import brief_for, zone_for


def freeze_time(value):
    """Pin timezone.now(). freezegun is avoided: it leaks into DRF's throttle timer for later tests."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return patch("django.utils.timezone.now", return_value=value)


SECRET = "signing-secret"
INTERACTIVITY_URL = "/api/slack/interactivity/"


def _resp(payload):
    response = MagicMock()
    response.json.return_value = payload
    return response


class FakeSlack:
    """Stands in for requests.post to the Slack Web API; records calls per method."""

    def __init__(self, ratelimit_on=None):
        self.calls = []
        self.ratelimit_on = ratelimit_on

    def __call__(self, url, **kwargs):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, kwargs.get("data") or {}))
        if method == self.ratelimit_on:
            return _resp({"ok": False, "error": "ratelimited"})
        if method == "conversations.open":
            return _resp({"ok": True, "channel": {"id": "D" + kwargs["data"]["users"]}})
        return _resp({"ok": True})

    def posts(self):
        return [data for method, data in self.calls if method == "chat.postMessage"]


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(name="Alpha", identifier="ALP", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


@pytest.fixture
def states(project):
    return {
        group: State.objects.create(name=group.title(), group=group, project=project, workspace=project.workspace)
        for group in ("backlog", "started", "completed")
    }


@pytest.fixture
def connection(workspace):
    with patch("plane.utils.slack_app.requests.post", return_value=_resp({"ok": True, "team_id": "T1", "team": "A"})):
        return slack_app.connect(workspace, "xoxb-secret")


@pytest.fixture
def linked(workspace, create_user, connection):
    create_user.user_timezone = "Asia/Kolkata"
    create_user.save()
    SlackUserLink.objects.create(workspace=workspace, user=create_user, slack_user_id="U1")
    return create_user


def _issue(project, state, name="Item", **kwargs):
    return Issue.objects.create(name=name, project=project, workspace=project.workspace, state=state, **kwargs)


def _assign(issue, user):
    IssueAssignee.objects.create(issue=issue, assignee=user, project=issue.project, workspace=issue.workspace)


def _decision(issue, user, **kwargs):
    values = {"question": "Ship it?", "options": ["Yes", "No"]}
    values.update(kwargs)
    return DecisionRequest.objects.create(
        issue=issue,
        project=issue.project,
        workspace=issue.workspace,
        asked_user=user,
        created_by=user,
        **values,
    )


# 03:40 UTC is 09:10 in Kolkata
NINE_IST = datetime(2026, 11, 21, 3, 40, tzinfo=ZoneInfo("UTC"))


@pytest.mark.unit
@pytest.mark.django_db
class TestSlackBrief:
    def test_daily_brief_sent_once_at_9_local(self, workspace, project, states, linked):
        item = _issue(project, states["started"], "Fix <login> & more")
        _assign(item, linked)
        slack = FakeSlack()
        with patch("plane.utils.slack_app.requests.post", side_effect=slack), freeze_time(NINE_IST):
            supervision_task.send_slack_briefs()
            supervision_task.send_slack_briefs()  # the same hour again: nothing more
        assert len(slack.posts()) == 1
        post = slack.posts()[0]
        assert post["channel"] == "DU1"
        text = json.dumps(json.loads(post["blocks"]))
        assert "ALP-1" in text and "/test-workspace/browse/ALP-1/" in text
        assert "/test-workspace/brief/" in text
        assert "&lt;login&gt; &amp; more" in text and "<login>" not in text
        assert BriefVisit.objects.get(workspace=workspace, user=linked).slack_sent_on == date(2026, 11, 21)

        # Not 09:xx in Kolkata (04:40 UTC = 10:10), and not a new day yet: still one DM.
        slack2 = FakeSlack()
        with patch("plane.utils.slack_app.requests.post", side_effect=slack2), freeze_time("2026-11-21T04:40:00Z"):
            supervision_task.send_slack_briefs()
        assert slack2.posts() == []
        # Next day at 09:xx it goes out again.
        with patch("plane.utils.slack_app.requests.post", side_effect=slack2), freeze_time("2026-11-22T03:40:00Z"):
            supervision_task.send_slack_briefs()
        assert len(slack2.posts()) == 1

    def test_daily_brief_skips_broken_connection_and_unmatched_users(
        self, workspace, project, states, linked, connection
    ):
        other = User.objects.create(email="nolink@example.com", username="nolink", user_timezone="Asia/Kolkata")
        ProjectMember.objects.create(project=project, member=other, workspace=workspace, role=15)
        _assign(_issue(project, states["started"], "Mine"), other)
        _assign(_issue(project, states["started"], "Linked one"), linked)
        slack = FakeSlack()
        with patch("plane.utils.slack_app.requests.post", side_effect=slack), freeze_time(NINE_IST):
            supervision_task.send_slack_briefs()
        assert [post["channel"] for post in slack.posts()] == ["DU1"]  # the unlinked person got nothing

        SlackConnection.objects.filter(pk=connection.pk).update(status="broken")
        BriefVisit.objects.all().update(slack_sent_on=None)
        slack = FakeSlack()
        with patch("plane.utils.slack_app.requests.post", side_effect=slack), freeze_time(NINE_IST):
            supervision_task.send_slack_briefs()
        assert slack.calls == []

    def test_rate_limit_stops_the_connection_and_leaves_the_rest_unsent(self, workspace, project, states, linked):
        second = User.objects.create(email="two@example.com", username="two", user_timezone="Asia/Kolkata")
        ProjectMember.objects.create(project=project, member=second, workspace=workspace, role=15)
        SlackUserLink.objects.create(workspace=workspace, user=second, slack_user_id="U2")
        for person in (linked, second):
            _assign(_issue(project, states["started"], f"For {person.username}"), person)
        slack = FakeSlack(ratelimit_on="chat.postMessage")
        with patch("plane.utils.slack_app.requests.post", side_effect=slack), freeze_time(NINE_IST):
            supervision_task.send_slack_briefs()
        assert len(slack.posts()) == 1  # stopped after the first ratelimited post
        assert not BriefVisit.objects.filter(slack_sent_on__isnull=False).exists()
        # Next hour (still 09:xx for a Kolkata person at 09:50) they get it.
        slack = FakeSlack()
        with patch("plane.utils.slack_app.requests.post", side_effect=slack), freeze_time("2026-11-21T04:20:00Z"):
            supervision_task.send_slack_briefs()
        assert len(slack.posts()) == 2

    def test_one_workspace_failing_does_not_crash_the_task(self, workspace, linked):
        with patch.object(supervision_task, "_send_connection_briefs", side_effect=RuntimeError("boom")):
            supervision_task.send_slack_briefs()  # must not raise

    def test_marking_sent_never_changes_the_last_seen_window(self, workspace, project, states, linked):
        _assign(_issue(project, states["started"], "x"), linked)
        with freeze_time(NINE_IST):
            before = brief_for(workspace.id, linked)
        slack = FakeSlack()
        with patch("plane.utils.slack_app.requests.post", side_effect=slack), freeze_time(NINE_IST):
            supervision_task.send_slack_briefs()
            after = brief_for(workspace.id, linked)
        visit = BriefVisit.objects.get(workspace=workspace, user=linked)
        assert visit.slack_sent_on is not None and visit.last_seen_at is None
        assert after["since"] == before["since"]

        seen = datetime(2026, 11, 20, 1, 0, tzinfo=ZoneInfo("UTC"))
        BriefVisit.objects.filter(pk=visit.pk).update(last_seen_at=seen, slack_sent_on=None)
        with patch("plane.utils.slack_app.requests.post", side_effect=slack), freeze_time(NINE_IST):
            supervision_task.send_slack_briefs()
        visit.refresh_from_db()
        assert visit.last_seen_at == seen and visit.slack_sent_on == date(2026, 11, 21)


@pytest.mark.unit
class TestLocalZone:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("UTC", "Asia/Kolkata"),  # Plane's untouched default means "not set" for our India-based team
            ("", "Asia/Kolkata"),
            (None, "Asia/Kolkata"),
            ("Not/AZone", "Asia/Kolkata"),
            ("../../etc", "Asia/Kolkata"),
            ("Pacific/Auckland", "Pacific/Auckland"),
        ],
    )
    def test_zone_for(self, name, expected):
        user = MagicMock(user_timezone=name)
        assert zone_for(user).key == expected


@pytest.mark.unit
@pytest.mark.django_db
class TestMilestoneAlerts:
    def test_milestone_alert_due_tomorrow(self, workspace, project, states, linked):
        tomorrow = Milestone.objects.create(
            title="Beta", project=project, workspace=workspace, target_date=date(2026, 11, 22)
        )
        overdue = Milestone.objects.create(
            title="Alpha", project=project, workspace=workspace, target_date=date(2026, 11, 1)
        )
        later = Milestone.objects.create(
            title="Later", project=project, workspace=workspace, target_date=date(2026, 11, 28)
        )
        done_only = Milestone.objects.create(
            title="Done", project=project, workspace=workspace, target_date=date(2026, 11, 22)
        )
        for milestone in (tomorrow, overdue, later):
            _issue(project, states["started"], f"In {milestone.title}", milestone=milestone)
        _issue(project, states["completed"], "Finished", milestone=done_only)
        slack = FakeSlack()
        with patch("plane.utils.slack_app.requests.post", side_effect=slack), freeze_time("2026-11-21T03:30:00Z"):
            supervision_task.send_milestone_alerts()
        assert len(slack.posts()) == 1
        text = slack.posts()[0]["blocks"]
        assert "Beta" in text and "Alpha" in text
        assert "Later" not in text and "Done" not in text

    def test_no_alert_when_nothing_is_due(self, workspace, project, states, linked):
        slack = FakeSlack()
        with patch("plane.utils.slack_app.requests.post", side_effect=slack), freeze_time("2026-11-21T03:30:00Z"):
            supervision_task.send_milestone_alerts()
        assert slack.posts() == []


@pytest.mark.unit
@pytest.mark.django_db
class TestDecisionDm:
    def test_decision_dm_has_option_buttons(self, workspace, project, states, linked):
        decision = _decision(_issue(project, states["started"], "Pick <one>"), linked, question="Use A & B?")
        slack = FakeSlack()
        with patch("plane.utils.slack_app.requests.post", side_effect=slack):
            supervision_task.notify_decision(str(decision.id))
            supervision_task.notify_decision(str(decision.id))  # a retry must not duplicate the inbox row
        blocks = json.loads(slack.posts()[0]["blocks"])
        buttons = [el for block in blocks if block["type"] == "actions" for el in block["elements"]]
        assert [b["action_id"] for b in buttons] == [f"decision:{decision.id}:0", f"decision:{decision.id}:1"]
        assert [b["text"]["text"] for b in buttons] == ["Yes", "No"]
        assert "Use A &amp; B?" in json.dumps(blocks)
        notes = Notification.objects.filter(receiver=linked, entity_name="decision")
        assert notes.count() == 1
        note = notes.get()
        assert note.sender == "decision" and note.entity_identifier == decision.issue_id
        assert note.project_id == project.id and note.workspace_id == workspace.id

    def test_free_text_decision_links_to_plane(self, workspace, project, states, linked):
        decision = _decision(_issue(project, states["started"]), linked, options=[])
        slack = FakeSlack()
        with patch("plane.utils.slack_app.requests.post", side_effect=slack):
            supervision_task.notify_decision(str(decision.id))
        blocks = json.loads(slack.posts()[0]["blocks"])
        elements = [el for block in blocks if block["type"] == "actions" for el in block["elements"]]
        assert (
            len(elements) == 1
            and "action_id" not in elements[0]
            or not elements[0]["action_id"].startswith("decision:")
        )
        assert elements[0]["url"].endswith("/test-workspace/browse/ALP-1/")
        assert elements[0]["text"]["text"] == "Answer in Plane"

    def test_answered_decision_is_not_sent(self, workspace, project, states, linked):
        decision = _decision(_issue(project, states["started"]), linked, status="answered", answer="Yes")
        slack = FakeSlack()
        with patch("plane.utils.slack_app.requests.post", side_effect=slack):
            supervision_task.notify_decision(str(decision.id))
        assert slack.calls == []

    def test_on_decision_created_enqueues(self):
        from plane.utils import decisions

        with patch("plane.bgtasks.supervision_task.notify_decision.delay") as delay:
            decisions.on_decision_created(MagicMock(id="abc"))
        delay.assert_called_once_with("abc")


def _signed(client_payload, secret=SECRET, timestamp=None, tamper=False):
    import time

    body = urlencode({"payload": json.dumps(client_payload)}).encode()
    timestamp = str(timestamp or int(time.time()))
    signature = "v0=" + hmac.new(secret.encode(), f"v0:{timestamp}:".encode() + body, hashlib.sha256).hexdigest()
    if tamper:
        body = body + b"&x=1"
    return body, {"HTTP_X_SLACK_REQUEST_TIMESTAMP": timestamp, "HTTP_X_SLACK_SIGNATURE": signature}


def _click(decision, index=0, slack_user="U1", team="T1"):
    return {
        "type": "block_actions",
        "team": {"id": team},
        "user": {"id": slack_user},
        "response_url": "https://hooks.slack.com/actions/T1/1/abc",
        "actions": [{"action_id": f"decision:{decision.id}:{index}", "type": "button"}],
    }


@pytest.mark.unit
@pytest.mark.django_db
class TestInteractivity:
    @pytest.fixture(autouse=True)
    def _secret(self, settings):
        settings.SLACK_SIGNING_SECRET = SECRET
        settings.WEB_URL = "https://plane.example.com"

    def test_interactivity_answers_decision(self, client, workspace, project, states, linked):
        decision = _decision(_issue(project, states["started"]), linked)
        body, headers = _signed(_click(decision, 1))
        with patch("plane.app.views.slack_interactivity.requests.post") as post:
            response = client.post(
                INTERACTIVITY_URL, data=body, content_type="application/x-www-form-urlencoded", **headers
            )
        assert response.status_code == 200
        decision.refresh_from_db()
        assert decision.status == "answered" and decision.answer == "No" and decision.answered_by_id == linked.id
        assert post.call_args.args[0] == "https://hooks.slack.com/actions/T1/1/abc"
        sent = post.call_args.kwargs["json"]
        assert sent["replace_original"] is True and "Answered: No" in json.dumps(sent)
        assert post.call_args.kwargs["timeout"]

    def test_already_answered(self, client, workspace, project, states, linked):
        decision = _decision(_issue(project, states["started"]), linked, status="answered", answer="Yes")
        body, headers = _signed(_click(decision, 0))
        with patch("plane.app.views.slack_interactivity.requests.post") as post:
            response = client.post(
                INTERACTIVITY_URL, data=body, content_type="application/x-www-form-urlencoded", **headers
            )
        assert response.status_code == 200
        assert "Already answered" in json.dumps(post.call_args.kwargs["json"])
        decision.refresh_from_db()
        assert decision.answer == "Yes"

    def test_unlinked_slack_user_gets_ephemeral_hint(self, client, workspace, project, states, linked):
        decision = _decision(_issue(project, states["started"]), linked)
        body, headers = _signed(_click(decision, 0, slack_user="UOTHER"))
        with patch("plane.app.views.slack_interactivity.requests.post") as post:
            response = client.post(
                INTERACTIVITY_URL, data=body, content_type="application/x-www-form-urlencoded", **headers
            )
        assert response.status_code == 200
        sent = post.call_args.kwargs["json"]
        assert sent["response_type"] == "ephemeral" and sent["replace_original"] is False
        assert "link your account" in sent["text"].lower()
        decision.refresh_from_db()
        assert decision.status == "open"

    def test_interactivity_rejects_bad_signature(self, client, workspace, project, states, linked):
        decision = _decision(_issue(project, states["started"]), linked)
        for kwargs in ({"tamper": True}, {"secret": "wrong"}, {"timestamp": 1000}):
            body, headers = _signed(_click(decision, 0), **kwargs)
            with patch("plane.app.views.slack_interactivity.requests.post") as post:
                response = client.post(
                    INTERACTIVITY_URL, data=body, content_type="application/x-www-form-urlencoded", **headers
                )
            assert response.status_code == 401
            assert not post.called
        response = client.post(
            INTERACTIVITY_URL, data=b"payload=%7B%7D", content_type="application/x-www-form-urlencoded"
        )
        assert response.status_code == 401
        decision.refresh_from_db()
        assert decision.status == "open"

    def test_unknown_team_or_option_is_ignored_safely(self, client, workspace, project, states, linked):
        decision = _decision(_issue(project, states["started"]), linked)
        for payload in (_click(decision, 0, team="TNOPE"), _click(decision, 9)):
            body, headers = _signed(payload)
            with patch("plane.app.views.slack_interactivity.requests.post"):
                response = client.post(
                    INTERACTIVITY_URL, data=body, content_type="application/x-www-form-urlencoded", **headers
                )
            assert response.status_code == 200
        decision.refresh_from_db()
        assert decision.status == "open"


@pytest.mark.unit
@pytest.mark.django_db
class TestInteractivityChecks:
    @pytest.fixture(autouse=True)
    def _secret(self, settings):
        settings.SLACK_SIGNING_SECRET = SECRET
        settings.WEB_URL = "https://plane.example.com"

    def _post(self, client, payload):
        body, headers = _signed(payload)
        with patch("plane.app.views.slack_interactivity.requests.post") as post:
            response = client.post(
                INTERACTIVITY_URL, data=body, content_type="application/x-www-form-urlencoded", **headers
            )
        return response, post

    def test_deleted_item_gets_ephemeral_reply(self, client, workspace, project, states, linked):
        issue = _issue(project, states["started"])
        decision = _decision(issue, linked)
        Issue.objects.filter(pk=issue.pk).update(deleted_at="2020-01-01T00:00:00Z")
        response, post = self._post(client, _click(decision, 0))
        assert response.status_code == 200
        sent = post.call_args.kwargs["json"]
        assert sent["response_type"] == "ephemeral" and sent["replace_original"] is False
        assert "not found" in sent["text"].lower()
        decision.refresh_from_db()
        assert decision.status == "open"

    def test_removed_member_gets_ephemeral_reply(self, client, workspace, project, states, linked):
        decision = _decision(_issue(project, states["started"]), linked)
        ProjectMember.objects.filter(project=project, member=linked).update(is_active=False)
        response, post = self._post(client, _click(decision, 0))
        assert response.status_code == 200
        assert post.call_args.kwargs["json"]["response_type"] == "ephemeral"
        decision.refresh_from_db()
        assert decision.status == "open"
