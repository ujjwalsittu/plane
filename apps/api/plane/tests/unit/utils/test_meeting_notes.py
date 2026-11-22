# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Meeting notes to work items: Claude proposes action items, the person accepts which ones become work items."""

import json
from datetime import date, timedelta
from types import SimpleNamespace
from unittest import mock
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import (
    AIUsage,
    Issue,
    IssueActivity,
    IssueAssignee,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceAIConfig,
    WorkspaceMember,
)
from plane.utils import ai_calls, meeting_notes
from plane.utils.agents import AgentError

MODEL = "claude-sonnet-5-5"
NOTES = "Weekly sync. Priya will fix the Safari login bug by Friday. Someone should update the docs."


def _project(workspace, identifier, member=None, role=20):
    project = Project.objects.create(name=f"{identifier} project", identifier=identifier, workspace=workspace)
    State.objects.create(name="Started", group="started", project=project, workspace=workspace)
    backlog = State.objects.create(name="Backlog", group="backlog", project=project, workspace=workspace, default=True)
    if member is not None:
        ProjectMember.objects.create(project=project, member=member, workspace=workspace, role=role)
    return project, backlog


def _person(workspace, email, project=None, role=15, **fields):
    local = email.split("@")[0]
    user = User.objects.create(email=email, username=local, display_name=local, **fields)
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role)
    if project is not None:
        ProjectMember.objects.create(project=project, member=user, workspace=workspace, role=role)
    return user


def _proposal_turn(tool_input):
    block = SimpleNamespace(type="tool_use", id="toolu_1", name="propose_work_items", input=tool_input)
    return SimpleNamespace(
        content=[block], stop_reason="tool_use", usage=SimpleNamespace(input_tokens=500, output_tokens=200)
    )


def _sent(call):
    return json.loads(call.kwargs["messages"][0]["content"])


def _item(name, **fields):
    return {
        "name": name,
        "description": fields.get("description", ""),
        "assignee_id": fields.get("assignee_id"),
        "owner_hint": fields.get("owner_hint", ""),
        "target_date": fields.get("target_date"),
        "priority": fields.get("priority", "none"),
    }


@pytest.fixture
def client(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(ai_calls, "anthropic_client_for", lambda workspace: client)
    monkeypatch.setattr(ai_calls, "model_for", lambda workspace: MODEL)
    return client


@pytest.mark.unit
@pytest.mark.django_db
class TestExtract:
    def test_extract_maps_owner_names_to_members(self, workspace, create_user, client):
        project, _ = _project(workspace, "MTG", member=create_user)
        priya = _person(workspace, "priya.k@plane.so", project=project, first_name="Priya", last_name="Kumar")
        guest = _person(workspace, "guest@plane.so", project=project, role=5)
        bot = _person(workspace, "bot@plane.so", project=project, is_bot=True, bot_type="agent")
        inactive = _person(workspace, "gone@plane.so", project=project, is_active=False)
        left = _person(workspace, "left@plane.so", project=project)
        ProjectMember.objects.filter(project=project, member=left).update(is_active=False)
        friday = (timezone.now().date() + timedelta(days=3)).isoformat()
        client.messages.create.return_value = _proposal_turn(
            {
                "items": [
                    _item(
                        "Fix the Safari login bug",
                        description="Login button does nothing on Safari.",
                        assignee_id=str(priya.id),
                        owner_hint="Priya",
                        target_date=friday,
                        priority="high",
                    ),
                    _item("Guest task", assignee_id=str(guest.id), owner_hint="Guest"),
                    _item("Bot task", assignee_id=str(bot.id), owner_hint="Bot", priority="loud"),
                    "not an item",
                    {"name": "", "priority": "low"},
                ]
            }
        )

        items = meeting_notes.extract_action_items(project, create_user, NOTES, title="Weekly sync")

        call = client.messages.create.call_args
        assert call.kwargs["tool_choice"] == {"type": "tool", "name": "propose_work_items"}
        assert [tool["name"] for tool in call.kwargs["tools"]] == ["propose_work_items"]
        sent = _sent(call)
        assert sent["notes"] == NOTES and sent["title"] == "Weekly sync"
        members = {row["id"]: row for row in sent["members"]}
        assert set(members) == {str(create_user.id), str(priya.id)}
        assert members[str(priya.id)] == {
            "id": str(priya.id),
            "display_name": "priya.k",
            "full_name": "Priya Kumar",
            "email_name": "priya.k",
        }
        assert str(inactive.id) not in members and str(left.id) not in members

        assert items[0] == {
            "name": "Fix the Safari login bug",
            "description": "Login button does nothing on Safari.",
            "assignee_id": str(priya.id),
            "owner_hint": "Priya",
            "target_date": friday,
            "priority": "high",
        }
        # A guest and an agent are never assignees; a bad priority becomes none; malformed rows are dropped
        assert items[1]["assignee_id"] is None and items[1]["owner_hint"] == "Guest"
        assert items[2]["assignee_id"] is None and items[2]["priority"] == "none"
        assert len(items) == 3
        assert AIUsage.objects.filter(kind="meeting_notes", user=create_user).count() == 1

    def test_unknown_owner_left_unassigned_with_hint(self, workspace, create_user, client):
        project, _ = _project(workspace, "UNK", member=create_user)
        outsider = _person(workspace, "outsider@plane.so")
        client.messages.create.return_value = _proposal_turn(
            {
                "items": [
                    _item("Book the venue", assignee_id=str(outsider.id), owner_hint="Marco"),
                    _item("Send the recap", assignee_id="not-a-uuid", owner_hint="Dana"),
                    {"name": "Call the vendor", "assignee_id": 42, "owner_hint": ["x"], "description": 7},
                ]
            }
        )

        items = meeting_notes.extract_action_items(project, create_user, NOTES)

        assert [(i["assignee_id"], i["owner_hint"]) for i in items] == [(None, "Marco"), (None, "Dana"), (None, "")]
        assert items[2]["description"] == ""

    def test_past_dates_dropped(self, workspace, create_user, client):
        project, _ = _project(workspace, "DAT", member=create_user)
        client.messages.create.return_value = _proposal_turn(
            {
                "items": [
                    _item("Before the meeting", target_date="2026-03-01"),
                    _item("Meeting day", target_date="2026-03-10"),
                    _item("After", target_date="2026-03-17"),
                    _item("Bad date", target_date="next friday"),
                    _item("Not a string", target_date=False),
                ]
            }
        )

        items = meeting_notes.extract_action_items(project, create_user, NOTES, meeting_date=date(2026, 3, 10))
        assert [i["target_date"] for i in items] == [None, "2026-03-10", "2026-03-17", None, None]

        # Without a meeting date, dates before today are dropped
        client.messages.create.return_value = _proposal_turn(
            {"items": [_item("Yesterday", target_date=(timezone.now().date() - timedelta(days=1)).isoformat())]}
        )
        assert meeting_notes.extract_action_items(project, create_user, NOTES)[0]["target_date"] is None

    def test_extract_validates_input_and_caps_items(self, workspace, create_user, client):
        project, _ = _project(workspace, "VAL", member=create_user)
        for text in ("too short", "x" * 50_001, None, 5):
            with pytest.raises(AgentError) as error:
                meeting_notes.extract_action_items(project, create_user, text)
            assert (error.value.status_code, error.value.field) == (400, "text")
        assert client.messages.create.call_count == 0

        client.messages.create.return_value = _proposal_turn({"items": [_item(f"Task {n}") for n in range(40)]})
        assert len(meeting_notes.extract_action_items(project, create_user, NOTES)) == 30
        client.messages.create.return_value = _proposal_turn({"items": "nope"})
        assert meeting_notes.extract_action_items(project, create_user, NOTES) == []
        client.messages.create.return_value = _proposal_turn({"items": [_item("y" * 400)]})
        assert len(meeting_notes.extract_action_items(project, create_user, NOTES)[0]["name"]) == 255

    def test_extract_needs_member_role(self, workspace, create_user, client):
        project, _ = _project(workspace, "GST", member=create_user, role=5)
        with pytest.raises(AgentError) as error:
            meeting_notes.extract_action_items(project, create_user, NOTES)
        assert error.value.status_code == 403
        assert client.messages.create.call_count == 0

    def test_extract_refused_over_limit(self, workspace, create_user, client):
        project, _ = _project(workspace, "LIM", member=create_user)
        AIUsage.objects.create(
            workspace=workspace,
            user=create_user,
            kind="ask",
            model=MODEL,
            input_tokens=1,
            output_tokens=1,
            cost_cents=5,
        )
        WorkspaceAIConfig.objects.create(workspace=workspace, monthly_limit_cents=4)
        with pytest.raises(AgentError) as error:
            meeting_notes.extract_action_items(project, create_user, NOTES)
        assert error.value.status_code == 409
        assert client.messages.create.call_count == 0
        assert not AIUsage.objects.filter(kind="meeting_notes").exists()


@pytest.mark.unit
@pytest.mark.django_db
class TestCreate:
    def test_create_makes_items_with_activity(self, workspace, create_user, django_capture_on_commit_callbacks):
        project, backlog = _project(workspace, "NEW", member=create_user)
        priya = _person(workspace, "priya@plane.so", project=project)
        items = [
            _item(
                "Fix the Safari login bug",
                description="Login button does nothing.\nCheck Safari 17.",
                assignee_id=str(priya.id),
                target_date="2026-12-01",
                priority="high",
            ),
            _item("Update the docs", owner_hint="Someone"),
        ]

        with (
            mock.patch.object(meeting_notes, "issue_activity") as task,
            django_capture_on_commit_callbacks(execute=True),
        ):
            created = meeting_notes.create_action_items(project, create_user, items, title="Weekly sync")

        assert [issue.name for issue in created] == ["Fix the Safari login bug", "Update the docs"]
        rows = Issue.objects.filter(project=project).order_by("sequence_id")
        assert rows.count() == 2
        assert {row.state_id for row in rows} == {backlog.id}
        first, second = rows
        assert first.priority == "high" and str(first.target_date) == "2026-12-01"
        assert first.created_by_id == create_user.id
        assert list(IssueAssignee.objects.filter(issue=first).values_list("assignee_id", flat=True)) == [priya.id]
        assert not IssueAssignee.objects.filter(issue=second).exists()
        assert "Check Safari 17." in first.description_stripped
        assert first.description_html.endswith("<p>From meeting notes: Weekly sync</p>")
        assert second.description_html == "<p>From meeting notes: Weekly sync</p>"

        assert task.delay.call_count == 2
        for call in task.delay.call_args_list:
            assert call.kwargs["type"] == "issue.activity.created"
            assert call.kwargs["notification"] is True
            assert call.kwargs["actor_id"] == str(create_user.id)
            issue_activity(**{**call.kwargs, "notification": False})
        assert IssueActivity.objects.filter(issue=first, verb="created").exists()
        assert IssueActivity.objects.filter(issue=second, verb="created").exists()

    def test_create_source_line_uses_date_without_title(self, workspace, create_user):
        project, _ = _project(workspace, "SRC", member=create_user)
        with mock.patch.object(meeting_notes, "issue_activity"):
            meeting_notes.create_action_items(project, create_user, [_item("A")], meeting_date=date(2026, 3, 10))
            meeting_notes.create_action_items(project, create_user, [_item("B")])
        a, b = Issue.objects.filter(project=project).order_by("sequence_id")
        assert a.description_html == "<p>From meeting notes: 2026-03-10</p>"
        assert b.description_html == f"<p>From meeting notes: {timezone.now().date().isoformat()}</p>"

    def test_create_rejects_bot_assignee(self, workspace, create_user):
        project, _ = _project(workspace, "BOT", member=create_user)
        bot = _person(workspace, "bot@plane.so", project=project, is_bot=True, bot_type="agent")
        guest = _person(workspace, "guest@plane.so", project=project, role=5)
        with mock.patch.object(meeting_notes, "issue_activity") as task:
            for bad in (str(bot.id), str(guest.id), "not-a-uuid", 7):
                with pytest.raises(AgentError) as error:
                    meeting_notes.create_action_items(project, create_user, [_item("Ok"), _item("X", assignee_id=bad)])
                assert error.value.status_code == 400
        # Nothing is created when any item is refused
        assert not Issue.objects.filter(project=project).exists()
        assert task.delay.call_count == 0

    def test_create_validates_items(self, workspace, create_user):
        project, _ = _project(workspace, "CHK", member=create_user)
        bad_batches = [
            [],
            [_item(f"T{n}") for n in range(31)],
            "items",
            [_item("Bad priority", priority="loud")],
            [_item("")],
            [_item("z" * 256)],
            [_item("Bad date", target_date="soon")],
            [{"name": "Desc not text", "description": ["x"]}],
            ["not a dict"],
        ]
        with mock.patch.object(meeting_notes, "issue_activity"):
            for batch in bad_batches:
                with pytest.raises(AgentError) as error:
                    meeting_notes.create_action_items(project, create_user, batch)
                assert error.value.status_code == 400, batch
        assert not Issue.objects.filter(project=project).exists()

    def test_create_needs_member_role(self, workspace, create_user):
        project, _ = _project(workspace, "GUE", member=create_user, role=5)
        with pytest.raises(AgentError) as error:
            meeting_notes.create_action_items(project, create_user, [_item("A")])
        assert error.value.status_code == 403


@pytest.mark.unit
@pytest.mark.django_db
class TestMeetingNotesEndpoints:
    @pytest.fixture
    def setup(self, workspace, create_user, monkeypatch):
        project, _ = _project(workspace, "END", member=create_user)
        calls = []

        def fake_extract(project, user, text, title="", meeting_date=None):
            calls.append(("extract", text, title, meeting_date))
            return [_item("Do it")]

        monkeypatch.setattr(meeting_notes, "extract_action_items", fake_extract)
        return SimpleNamespace(project=project, calls=calls)

    def _url(self, setup, action, v1=False):
        prefix = "/api/v1" if v1 else "/api"
        return f"{prefix}/workspaces/test-workspace/projects/{setup.project.id}/meeting-notes/{action}/"

    def test_app_extract(self, session_client, create_user, setup):
        response = session_client.post(
            self._url(setup, "extract"), {"text": NOTES, "title": "Sync", "meeting_date": "2026-03-10"}, format="json"
        )
        assert response.status_code == 200, response.data
        assert response.data["items"][0]["name"] == "Do it"
        # The assignee picker offers only the people the server accepts
        assert response.data["members"] == [{"id": str(create_user.id), "display_name": create_user.display_name}]
        assert setup.calls == [("extract", NOTES, "Sync", date(2026, 3, 10))]

        response = session_client.post(self._url(setup, "extract"), {"text": NOTES, "meeting_date": "soon"})
        assert response.status_code == 400
        assert response.data == {"error": "Give the meeting date as YYYY-MM-DD", "field": "meeting_date"}

    def test_app_create(self, session_client, create_user, setup, django_capture_on_commit_callbacks):
        with (
            mock.patch.object(meeting_notes, "issue_activity") as task,
            mock.patch("plane.api.views.agents.base_host", return_value="http://testserver"),
            django_capture_on_commit_callbacks(execute=True),
        ):
            response = session_client.post(
                self._url(setup, "create"), {"items": [_item("Ship it")], "title": "Sync"}, format="json"
            )
        assert response.status_code == 201, response.data
        [row] = response.data
        issue = Issue.objects.get(pk=row["id"])
        assert row == {
            "id": str(issue.id),
            "name": "Ship it",
            "sequence_id": issue.sequence_id,
            "project_id": str(setup.project.id),
            "project_identifier": "END",
        }
        assert task.delay.call_args.kwargs["origin"] == "http://testserver"

    def test_app_needs_member_role(self, session_client, create_user, setup):
        ProjectMember.objects.filter(project=setup.project, member=create_user).update(role=5)
        assert session_client.post(self._url(setup, "extract"), {"text": NOTES}).status_code == 403
        assert (
            session_client.post(self._url(setup, "create"), {"items": [_item("A")]}, format="json").status_code == 403
        )
        assert setup.calls == []

    def test_v1_endpoints(self, api_key_client, create_user, setup):
        response = api_key_client.post(self._url(setup, "extract", v1=True), {"text": NOTES}, format="json")
        assert response.status_code == 200, response.data
        assert setup.calls == [("extract", NOTES, "", None)]

        with mock.patch.object(meeting_notes, "issue_activity"):
            response = api_key_client.post(
                self._url(setup, "create", v1=True), {"items": [_item("Ship it")]}, format="json"
            )
        assert response.status_code == 201, response.data

        # One error shape: {field: message}, as AgentError gives it
        response = api_key_client.post(self._url(setup, "create", v1=True), {"items": []}, format="json")
        assert response.status_code == 400 and set(response.data) == {"items"}
        ProjectMember.objects.filter(project=setup.project, member=create_user).update(role=5)
        response = api_key_client.post(self._url(setup, "extract", v1=True), {"text": NOTES}, format="json")
        assert response.status_code == 403 and set(response.data) == {"error"}
