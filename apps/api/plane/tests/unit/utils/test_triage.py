# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Triage suggestions: Claude picks an assignee, labels, a project and duplicates from candidates the person can see."""

import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.core.cache import cache
from django.utils import timezone

from plane.db.models import (
    AIUsage,
    Issue,
    IssueRelation,
    Label,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceAIConfig,
    WorkspaceMember,
)
from plane.utils import ai_calls, triage
from plane.utils.agents import AgentError

MODEL = "claude-sonnet-5-5"


def _project(workspace, identifier, member=None, role=20, guest_view_all_features=False):
    project = Project.objects.create(
        name=f"{identifier} project",
        identifier=identifier,
        workspace=workspace,
        description=f"Everything about {identifier}",
        guest_view_all_features=guest_view_all_features,
    )
    state = State.objects.create(name="Started", group="started", project=project, workspace=workspace)
    if member is not None:
        ProjectMember.objects.create(project=project, member=member, workspace=workspace, role=role)
    return project, state


def _issue(project, state, name, description="", created_by=None):
    issue = Issue.objects.create(
        name=name,
        description_html=f"<p>{description}</p>" if description else "<p></p>",
        project=project,
        workspace=project.workspace,
        state=state,
    )
    if created_by is not None:
        Issue.objects.filter(pk=issue.pk).update(created_by=created_by)
    return issue


def _person(workspace, email, project=None, role=15, **fields):
    user = User.objects.create(email=email, username=email.split("@")[0], display_name=email.split("@")[0], **fields)
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role)
    if project is not None:
        ProjectMember.objects.create(project=project, member=user, workspace=workspace, role=role)
    return user


def _suggestion_turn(tool_input):
    block = SimpleNamespace(type="tool_use", id="toolu_1", name="record_suggestions", input=tool_input)
    return SimpleNamespace(
        content=[block], stop_reason="tool_use", usage=SimpleNamespace(input_tokens=300, output_tokens=60)
    )


def _sent(call):
    """The candidates JSON sent to the model in a messages.create call."""
    return json.loads(call.kwargs["messages"][0]["content"])


@pytest.fixture
def client(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(ai_calls, "anthropic_client_for", lambda workspace: client)
    monkeypatch.setattr(ai_calls, "model_for", lambda workspace: MODEL)
    return client


@pytest.fixture(autouse=True)
def _clear_cache():
    yield
    cache.delete_pattern("triage:*")


@pytest.mark.unit
@pytest.mark.django_db
class TestTriage:
    def test_suggestions_limited_to_candidates(self, workspace, create_user, client):
        project, state = _project(workspace, "APP", member=create_user)
        other_project, other_state = _project(workspace, "WEB", member=create_user)
        hidden_project, hidden_state = _project(workspace, "SEC")
        dev = _person(workspace, "dev@plane.so", project=project)
        outsider = _person(workspace, "outsider@plane.so")
        bug = Label.objects.create(name="bug", project=project, workspace=workspace)
        ui = Label.objects.create(name="ui", project=project, workspace=workspace)
        foreign = Label.objects.create(name="bug", project=other_project, workspace=workspace)
        issue = _issue(project, state, "Login fails on Safari", "The login button does nothing on Safari")
        twin = _issue(project, state, "Safari login broken", "Login fails in Safari 17")
        hidden_twin = _issue(hidden_project, hidden_state, "Login fails on Safari too")
        client.messages.create.return_value = _suggestion_turn(
            {
                "assignee": {"id": str(outsider.id), "reason": "Knows Safari"},
                "labels": [
                    {"id": str(foreign.id), "reason": "A bug"},
                    {"id": str(bug.id), "reason": "A bug"},
                    {"id": "not-a-uuid", "reason": "?"},
                    {"id": str(ui.id), "reason": "Button"},
                    {"id": str(bug.id), "reason": "Again"},
                ],
                "project": {"id": str(hidden_project.id), "reason": "Security"},
                "duplicates": [
                    {"id": str(hidden_twin.id), "reason": "Same title"},
                    {"id": str(twin.id), "reason": "Same bug"},
                ],
            }
        )

        result = triage.suggest(issue, create_user)

        assert result["assignee"] is None
        assert result["labels"] == [
            {"id": str(bug.id), "name": "bug", "reason": "A bug"},
            {"id": str(ui.id), "name": "ui", "reason": "Button"},
        ]
        assert result["project"] is None
        assert result["duplicates"] == [
            {"id": str(twin.id), "identifier": f"APP-{twin.sequence_id}", "name": twin.name, "reason": "Same bug"}
        ]
        assert result["generated_at"]
        call = client.messages.create.call_args
        assert call.kwargs["tool_choice"] == {"type": "tool", "name": "record_suggestions"}
        assert call.kwargs["tools"] == [triage.TOOL]
        sent = _sent(call)
        assert {m["id"] for m in sent["members"]} == {str(create_user.id), str(dev.id)}
        assert {lb["id"] for lb in sent["labels"]} == {str(bug.id), str(ui.id)}
        assert {p["id"] for p in sent["projects"]} == {str(project.id), str(other_project.id)}
        assert [d["id"] for d in sent["duplicate_candidates"]] == [str(twin.id)]

        # A valid project other than the current one is kept; the current one never is
        client.messages.create.return_value = _suggestion_turn(
            {
                "assignee": {"id": str(dev.id), "reason": "Owns login"},
                "labels": [],
                "project": {"id": str(other_project.id), "reason": "It is a web bug"},
                "duplicates": [],
            }
        )
        result = triage.suggest(issue, create_user, refresh=True)
        assert result["assignee"] == {"id": str(dev.id), "display_name": "dev", "reason": "Owns login"}
        assert result["project"] == {"id": str(other_project.id), "name": "WEB project", "reason": "It is a web bug"}

        client.messages.create.return_value = _suggestion_turn(
            {
                "assignee": None,
                "labels": "bug",
                "project": {"id": str(project.id), "reason": "Here"},
                "duplicates": None,
            }
        )
        result = triage.suggest(issue, create_user, refresh=True)
        assert (result["assignee"], result["labels"], result["project"], result["duplicates"]) == (None, [], None, [])

    def test_at_most_one_assignee_three_labels_three_duplicates(self, workspace, create_user, client):
        project, state = _project(workspace, "CAP", member=create_user)
        labels = [Label.objects.create(name=f"l{n}", project=project, workspace=workspace) for n in range(5)]
        issue = _issue(project, state, "Export crashes")
        twins = [_issue(project, state, f"Export crashes again {n}") for n in range(5)]
        client.messages.create.return_value = _suggestion_turn(
            {
                "assignee": {"id": str(create_user.id), "reason": "r"},
                "labels": [{"id": str(label.id), "reason": "r"} for label in labels],
                "project": None,
                "duplicates": [{"id": str(twin.id), "reason": "r"} for twin in twins],
            }
        )

        result = triage.suggest(issue, create_user)

        assert result["assignee"]["id"] == str(create_user.id)
        assert len(result["labels"]) == 3
        assert len(result["duplicates"]) == 3

    def test_bots_never_suggested_as_assignee(self, workspace, create_user, client):
        project, state = _project(workspace, "BOT", member=create_user)
        bot = _person(workspace, "agent@plane.so", project=project, is_bot=True, bot_type="agent")
        guest = _person(workspace, "guest@plane.so", project=project, role=5)
        gone = _person(workspace, "gone@plane.so", project=project)
        ProjectMember.objects.filter(project=project, member=gone).update(is_active=False)
        issue = _issue(project, state, "Nightly sync fails")
        client.messages.create.return_value = _suggestion_turn(
            {"assignee": {"id": str(bot.id), "reason": "Agents are fast"}, "labels": [], "duplicates": []}
        )

        result = triage.suggest(issue, create_user)

        assert result["assignee"] is None
        members = {m["id"] for m in _sent(client.messages.create.call_args)["members"]}
        assert members == {str(create_user.id)}
        assert str(bot.id) not in members and str(guest.id) not in members and str(gone.id) not in members

    def test_duplicate_candidates_respect_visibility(self, workspace, create_user):
        other = _person(workspace, "other@plane.so")
        mine, mine_state = _project(workspace, "MINE", member=create_user)
        theirs, theirs_state = _project(workspace, "THEIRS", member=other)
        guest, guest_state = _project(workspace, "GST", member=create_user, role=5)
        left, left_state = _project(workspace, "LEFT", member=create_user)
        ProjectMember.objects.filter(project=left, member=create_user).update(deleted_at=timezone.now())
        issue = _issue(mine, mine_state, "Payment webhook times out")
        visible = _issue(mine, mine_state, "Payment webhook timeout on retry")
        related = _issue(mine, mine_state, "Payment webhook times out in staging")
        old = _issue(mine, mine_state, "Payment webhook times out last year")
        Issue.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=181))
        _issue(mine, mine_state, "Dark mode colours")
        secret = _issue(theirs, theirs_state, "Payment webhook times out for them")
        guest_other = _issue(guest, guest_state, "Payment webhook times out as guest", created_by=other)
        guest_mine = _issue(guest, guest_state, "Payment webhook times out, my report", created_by=create_user)
        departed = _issue(left, left_state, "Payment webhook times out after leaving")
        IssueRelation.objects.create(
            issue=issue, related_issue=related, relation_type="relates_to", project=mine, workspace=workspace
        )

        found = triage.duplicate_candidates(issue, create_user)

        ids = {candidate.id for candidate in found}
        assert ids == {visible.id, guest_mine.id}
        for hidden in (issue, related, old, secret, guest_other, departed):
            assert hidden.id not in ids
        assert len(triage.duplicate_candidates(issue, create_user, limit=1)) == 1

        # A soft-deleted relation no longer hides the item
        IssueRelation.objects.filter(issue=issue, related_issue=related).update(deleted_at=timezone.now())
        assert related.id in {candidate.id for candidate in triage.duplicate_candidates(issue, create_user)}

    def test_cached_until_item_changes(self, workspace, create_user, client):
        project, state = _project(workspace, "CCH", member=create_user)
        issue = _issue(project, state, "Search is slow")
        client.messages.create.return_value = _suggestion_turn(
            {"assignee": {"id": str(create_user.id), "reason": "r"}, "labels": [], "duplicates": []}
        )

        first = triage.suggest(issue, create_user)
        second = triage.suggest(issue, create_user)
        assert client.messages.create.call_count == 1
        assert second == first
        assert triage.cache_key(issue, create_user) == (
            f"triage:{issue.id}:{create_user.id}:{int(issue.updated_at.timestamp())}"
        )
        assert cache.get(triage.cache_key(issue, create_user)) is not None

        triage.suggest(issue, create_user, refresh=True)
        assert client.messages.create.call_count == 2

        Issue.objects.filter(pk=issue.pk).update(updated_at=issue.updated_at + timedelta(minutes=5))
        issue.refresh_from_db()
        triage.suggest(issue, create_user)
        assert client.messages.create.call_count == 3

    def test_each_viewer_gets_their_own_answer(self, workspace, create_user, client):
        project, state = _project(workspace, "SHR", member=create_user)
        side, side_state = _project(workspace, "SIDE", member=create_user)
        other = _person(workspace, "colleague@plane.so", project=project)
        issue = _issue(project, state, "Upload fails for big files")
        twin = _issue(side, side_state, "Upload fails for big files on mobile")
        client.messages.create.return_value = _suggestion_turn(
            {
                "assignee": {"id": str(other.id), "reason": f"Same root cause as {twin.name}"},
                "labels": [],
                "project": {"id": str(side.id), "reason": "Mobile"},
                "duplicates": [{"id": str(twin.id), "reason": "Same"}],
            }
        )
        assert triage.suggest(issue, create_user)["duplicates"][0]["id"] == str(twin.id)

        # A colleague who isn't in SIDE never gets the first answer (its reasons name SIDE's items): own call
        client.messages.create.return_value = _suggestion_turn(
            {"assignee": {"id": str(create_user.id), "reason": "Owns uploads"}, "labels": [], "duplicates": []}
        )
        result = triage.suggest(issue, other)

        assert client.messages.create.call_count == 2
        assert twin.name not in json.dumps(result)
        assert result["assignee"]["reason"] == "Owns uploads"
        assert twin.name not in client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert triage.cache_key(issue, create_user) != triage.cache_key(issue, other)

    def test_cached_answer_rechecked_when_access_changes(self, workspace, create_user, client):
        project, state = _project(workspace, "RCK", member=create_user)
        side, side_state = _project(workspace, "RSIDE", member=create_user)
        issue = _issue(project, state, "Upload fails for big files")
        twin = _issue(side, side_state, "Upload fails for big files on mobile")
        client.messages.create.return_value = _suggestion_turn(
            {
                "assignee": None,
                "labels": [],
                "project": {"id": str(side.id), "reason": "Mobile"},
                "duplicates": [{"id": str(twin.id), "reason": "Same"}],
            }
        )
        triage.suggest(issue, create_user)

        # Leaving RSIDE within the 24 hours drops what came from it from the cached answer
        ProjectMember.objects.filter(project=side, member=create_user).update(is_active=False)
        result = triage.suggest(issue, create_user)

        assert client.messages.create.call_count == 1
        assert result["duplicates"] == [] and result["project"] is None

    def test_usage_recorded_and_limit_enforced(self, workspace, create_user, client, monkeypatch):
        project, state = _project(workspace, "USE", member=create_user)
        issue = _issue(project, state, "Charts render blank")
        client.messages.create.return_value = _suggestion_turn({"labels": [], "duplicates": []})

        triage.suggest(issue, create_user)

        row = AIUsage.objects.get(kind="triage", user=create_user)
        assert (row.model, row.input_tokens, row.output_tokens) == (MODEL, 300, 60)

        WorkspaceAIConfig.objects.create(workspace=workspace, monthly_limit_cents=0)
        with pytest.raises(AgentError) as error:
            triage.suggest(issue, create_user, refresh=True)
        assert error.value.status_code == 409
        assert client.messages.create.call_count == 1

        monkeypatch.setattr(ai_calls, "anthropic_client_for", lambda workspace: None)
        with pytest.raises(AgentError) as error:
            triage.suggest(issue, create_user, refresh=True)
        assert error.value.status_code == 400


@pytest.mark.unit
@pytest.mark.django_db
class TestTriageEndpoints:
    @pytest.fixture
    def setup(self, workspace, create_user, monkeypatch):
        project, state = _project(workspace, "END", member=create_user)
        issue = _issue(project, state, "Intake: CSV import drops rows")
        # Intake items sit in a triage state, which the default work item manager hides
        triage_state = State.all_state_objects.create(
            name="Triage", group="triage", project=project, workspace=workspace
        )
        intake = _issue(project, triage_state, "Intake: emails bounce")
        calls = []

        def fake(issue, user, refresh=False):
            calls.append((issue.id, user.id, refresh))
            return {"assignee": None, "labels": [], "project": None, "duplicates": [], "generated_at": "now"}

        monkeypatch.setattr(triage, "suggest", fake)
        return SimpleNamespace(project=project, issue=issue, intake=intake, calls=calls)

    def _app(self, setup, issue=None, query=""):
        issue = issue or setup.issue
        return f"/api/workspaces/test-workspace/projects/{setup.project.id}/work-items/{issue.id}/triage/{query}"

    def _v1(self, setup):
        return f"/api/v1/workspaces/test-workspace/projects/{setup.project.id}/work-items/{setup.issue.id}/triage/"

    def test_app_endpoint_returns_suggestions(self, session_client, create_user, setup):
        response = session_client.get(self._app(setup, query="?refresh=1"))
        assert response.status_code == 200
        assert response.data["duplicates"] == []
        assert setup.calls == [(setup.issue.id, create_user.id, True)]

        assert session_client.get(self._app(setup, query="?refresh=false")).status_code == 200
        assert session_client.get(self._app(setup, issue=setup.intake)).status_code == 200
        assert [refresh for _, _, refresh in setup.calls] == [True, False, False]

    def test_app_endpoint_needs_member_role(self, session_client, create_user, setup):
        ProjectMember.objects.filter(project=setup.project, member=create_user).update(role=5)
        assert session_client.get(self._app(setup)).status_code == 403
        assert setup.calls == []

    def test_app_endpoint_returns_refusal(self, session_client, setup, monkeypatch):
        def refuse(*args, **kwargs):
            raise AgentError("AI is not set up for this workspace", 400, "ai")

        monkeypatch.setattr(triage, "suggest", refuse)
        response = session_client.get(self._app(setup))
        assert response.status_code == 400
        assert response.data == {"error": "AI is not set up for this workspace", "field": "ai"}

    def test_v1_endpoint(self, api_key_client, create_user, setup):
        response = api_key_client.get(self._v1(setup))
        assert response.status_code == 200
        assert setup.calls == [(setup.issue.id, create_user.id, False)]

        ProjectMember.objects.filter(project=setup.project, member=create_user).update(role=5)
        assert api_key_client.get(self._v1(setup)).status_code == 403
