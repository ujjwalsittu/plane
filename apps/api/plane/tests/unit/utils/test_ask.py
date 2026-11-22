# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Ask the workspace: Claude answers from tools that read Plane data as the asking person."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from anthropic.types import TextBlock, ThinkingBlock, ToolUseBlock
from django.core.cache import cache

from plane.db.models import (
    AIUsage,
    GitHubPullRequest,
    GitHubWorkItemLink,
    Issue,
    IssueRelation,
    Page,
    Project,
    ProjectMember,
    ProjectPage,
    State,
    User,
    WorkspaceAIConfig,
    WorkspaceMember,
)
from plane.utils import ai_calls, ask
from plane.utils.agents import AgentError

MODEL = "claude-sonnet-5-5"
ASK_URL = "/api/workspaces/test-workspace/ask/"


def _project(workspace, identifier, member=None, role=20, guest_view_all_features=False):
    project = Project.objects.create(
        name=f"{identifier} project",
        identifier=identifier,
        workspace=workspace,
        guest_view_all_features=guest_view_all_features,
    )
    state = State.objects.create(name="Started", group="started", project=project, workspace=workspace)
    if member is not None:
        ProjectMember.objects.create(project=project, member=member, workspace=workspace, role=role)
    return project, state


def _issue(project, state, name, created_by=None):
    issue = Issue.objects.create(name=name, project=project, workspace=project.workspace, state=state)
    if created_by is not None:
        # save() overwrites created_by with the request's user, so set it afterwards
        Issue.objects.filter(pk=issue.pk).update(created_by=created_by)
    return issue


def _ident(issue):
    return f"{issue.project.identifier}-{issue.sequence_id}"


def _usage():
    return SimpleNamespace(input_tokens=100, output_tokens=20)


def _tool_turn(name, tool_input, tool_id="toolu_1"):
    block = ToolUseBlock(type="tool_use", id=tool_id, name=name, input=tool_input)
    return SimpleNamespace(content=[block], stop_reason="tool_use", usage=_usage())


def _text_turn(text):
    return SimpleNamespace(content=[TextBlock(type="text", text=text)], stop_reason="end_turn", usage=_usage())


@pytest.fixture
def client(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(ai_calls, "anthropic_client_for", lambda workspace: client)
    monkeypatch.setattr(ai_calls, "model_for", lambda workspace: MODEL)
    return client


def _tool_result_text(call):
    """The text of the first tool_result block sent in a messages.create call."""
    for message in reversed(call.kwargs["messages"]):
        if message["role"] == "user" and isinstance(message["content"], list):
            return message["content"][0]["content"]
    raise AssertionError("no tool result sent")


@pytest.mark.unit
@pytest.mark.django_db
class TestAsk:
    def test_ask_runs_tools_and_returns_cited_sources(self, workspace, create_user, client):
        project, state = _project(workspace, "PLAT", member=create_user)
        _issue(project, state, "Set up CI")
        login = _issue(project, state, "Login fails on Safari")
        client.messages.create.side_effect = [
            _tool_turn("search_work_items", {"query": "login"}),
            _text_turn(f"The Safari login bug is tracked in [{_ident(login)}]."),
        ]

        result = ask.ask(workspace, create_user, "Is anyone on the Safari login bug?")

        assert result["answer"] == f"The Safari login bug is tracked in [{_ident(login)}]."
        assert result["sources"] == [
            {
                "kind": "work_item",
                "id": str(login.id),
                "identifier": _ident(login),
                "title": "Login fails on Safari",
                "url": f"/test-workspace/browse/{_ident(login)}/",
            }
        ]
        first, second = client.messages.create.call_args_list
        assert first.kwargs["tools"] == ask.TOOLS
        assert first.kwargs["messages"] == [{"role": "user", "content": "Is anyone on the Safari login bug?"}]
        assert "[OSMG-12]" in first.kwargs["system"]
        rows = json.loads(_tool_result_text(second))["results"]
        assert [row["identifier"] for row in rows] == [_ident(login)]
        assert second.kwargs["messages"][1]["content"][0]["type"] == "tool_use"

    def test_history_is_sent_before_the_question(self, workspace, create_user, client):
        client.messages.create.return_value = _text_turn("Nothing found.")
        history = [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}]

        ask.ask(workspace, create_user, "And now?", history=history)

        assert client.messages.create.call_args.kwargs["messages"] == history + [
            {"role": "user", "content": "And now?"}
        ]

    @pytest.mark.parametrize("question", ["", "   ", "x" * 2001, None])
    def test_question_must_be_1_to_2000_characters(self, workspace, create_user, client, question):
        with pytest.raises(AgentError) as error:
            ask.ask(workspace, create_user, question)
        assert (error.value.status_code, error.value.field) == (400, "question")
        client.messages.create.assert_not_called()

    def test_tools_only_see_visible_items(self, workspace, create_user, client):
        other = User.objects.create(email="other@plane.so", username="other")
        WorkspaceMember.objects.create(workspace=workspace, member=other, role=20)
        mine, mine_state = _project(workspace, "MINE", member=create_user)
        theirs, theirs_state = _project(workspace, "THEIRS", member=other)
        guest, guest_state = _project(workspace, "GST", member=create_user, role=5)
        visible = _issue(mine, mine_state, "Alpha visible")
        secret = _issue(theirs, theirs_state, "Alpha secret")
        guest_hidden = _issue(guest, guest_state, "Alpha guest hidden", created_by=other)
        guest_mine = _issue(guest, guest_state, "Alpha guest mine", created_by=create_user)
        IssueRelation.objects.create(
            issue=visible, related_issue=secret, relation_type="blocked_by", project=mine, workspace=workspace
        )
        pull = GitHubPullRequest.objects.create(
            workspace=workspace,
            repository_id=1,
            repository_full_name="acme/app",
            number=7,
            title="Secret PR",
            html_url="https://github.com/acme/app/pull/7",
        )
        GitHubWorkItemLink.objects.create(
            issue=secret,
            kind="pull_request",
            pull_request=pull,
            repository_id=1,
            repository_full_name="acme/app",
            ref="7",
            project=theirs,
            workspace=workspace,
        )
        public = Page.objects.create(workspace=workspace, name="Alpha plan", owned_by=other, access=0)
        private = Page.objects.create(workspace=workspace, name="Alpha private", owned_by=other, access=1)
        hidden_project_page = Page.objects.create(workspace=workspace, name="Alpha theirs", owned_by=other, access=0)
        # A project guest only opens pages they own (unless the project lets guests see everything)
        guest_public = Page.objects.create(workspace=workspace, name="Alpha guest public", owned_by=other, access=0)
        guest_own = Page.objects.create(workspace=workspace, name="Alpha guest own", owned_by=create_user, access=1)
        for page, project in (
            (public, mine),
            (private, mine),
            (hidden_project_page, theirs),
            (guest_public, guest),
            (guest_own, guest),
        ):
            ProjectPage.objects.create(page=page, project=project, workspace=workspace)
        context = ask.AskContext(workspace, create_user)

        found = json.loads(ask.run_tool(context, "search_work_items", {"query": "Alpha"}))["results"]
        assert sorted(row["identifier"] for row in found) == sorted([_ident(visible), _ident(guest_mine)])
        assert _ident(guest_hidden) not in json.dumps(found)

        for name in ("get_work_item", "github_activity"):
            for hidden in (secret, guest_hidden):
                assert "error" in json.loads(ask.run_tool(context, name, {"identifier": _ident(hidden)}))
        detail = json.loads(ask.run_tool(context, "get_work_item", {"identifier": _ident(visible)}))
        assert "Alpha secret" not in json.dumps(detail) and detail["blocked_by"] == ["a work item you can't see"]

        blocked = json.loads(ask.run_tool(context, "blocked_items", {}))["results"]
        assert [row["identifier"] for row in blocked] == [_ident(visible)]
        assert "Alpha secret" not in json.dumps(blocked)

        pages = json.loads(ask.run_tool(context, "search_pages", {"query": "Alpha"}))["results"]
        assert sorted(row["title"] for row in pages) == ["Alpha guest own", "Alpha plan"]
        assert "Alpha guest public" not in json.dumps(pages)

        # With guest_view_all_features the guest sees the project's public pages too
        Project.objects.filter(pk=guest.pk).update(guest_view_all_features=True)
        pages = json.loads(ask.run_tool(context, "search_pages", {"query": "Alpha guest"}))["results"]
        assert sorted(row["title"] for row in pages) == ["Alpha guest own", "Alpha guest public"]

        # Only entities the person could see become citable sources
        assert {source["title"] for source in context.sources.values()} <= {
            "Alpha visible",
            "Alpha guest mine",
            "Alpha plan",
            "Alpha guest own",
            "Alpha guest public",
        }

    def test_project_filter_accepts_identifier_or_name(self, workspace, create_user):
        alpha, alpha_state = _project(workspace, "ALP", member=create_user)
        beta, beta_state = _project(workspace, "BET", member=create_user)
        a = _issue(alpha, alpha_state, "Task a")
        _issue(beta, beta_state, "Task b")
        context = ask.AskContext(workspace, create_user)

        for project in ("ALP", "alp", "ALP project"):
            rows = json.loads(ask.run_tool(context, "search_work_items", {"query": "", "project": project}))
            assert [row["identifier"] for row in rows["results"]] == [_ident(a)]
        assert "error" in json.loads(ask.run_tool(context, "search_work_items", {"query": "", "project": "nope"}))

    def test_results_are_capped_at_20_rows_and_8000_characters(self, workspace, create_user):
        project, state = _project(workspace, "BIG", member=create_user)
        for n in range(25):
            _issue(project, state, f"Item {n}")
        context = ask.AskContext(workspace, create_user)

        data = json.loads(ask.run_tool(context, "search_work_items", {"query": "Item"}))
        assert len(data["results"]) == ask.MAX_ROWS and data["truncated"] is True

        text = ask._fit({"results": [{"title": "x" * 1000} for _ in range(20)], "truncated": False}, "results")
        assert len(text) <= ask.MAX_RESULT_CHARS
        data = json.loads(text)
        assert 0 < len(data["results"]) < 20 and data["truncated"] is True

    def test_ask_stops_after_8_tool_rounds(self, workspace, create_user, client):
        def respond(**kwargs):
            if kwargs.get("tool_choice") == {"type": "none"}:
                return _text_turn("Here is what I found so far.")
            return _tool_turn("search_work_items", {"query": "loop"})

        client.messages.create.side_effect = respond

        result = ask.ask(workspace, create_user, "Keep looking")

        assert ask.MAX_TOOL_ROUNDS == 8
        assert client.messages.create.call_count == 9
        assert client.messages.create.call_args.kwargs["tool_choice"] == {"type": "none"}
        assert result == {"answer": "Here is what I found so far.", "sources": []}

    def test_ask_stops_tool_rounds_after_the_deadline(self, workspace, create_user, client, monkeypatch):
        # Started at 0; round 1 begins at 10s, round 2 at 46s, past the 45 second deadline
        ticks = iter([0, 10, 46])
        monkeypatch.setattr(ask, "_clock", lambda: next(ticks))

        def respond(**kwargs):
            if kwargs.get("tool_choice") == {"type": "none"}:
                return _text_turn("Here is what I found in time.")
            return _tool_turn("search_work_items", {"query": "slow"})

        client.messages.create.side_effect = respond

        result = ask.ask(workspace, create_user, "Keep looking")

        assert ask.ASK_DEADLINE_SECONDS == 45
        assert client.messages.create.call_count == 2
        first, second = client.messages.create.call_args_list
        assert "tool_choice" not in first.kwargs
        assert second.kwargs["tool_choice"] == {"type": "none"}
        assert result["answer"] == "Here is what I found in time."

    def test_thinking_blocks_sent_back_unchanged(self, workspace, create_user, client):
        thinking = ThinkingBlock(type="thinking", thinking="", signature="sig-round-1")
        lookup = ToolUseBlock(type="tool_use", id="toolu_9", name="blocked_items", input={})
        client.messages.create.side_effect = [
            SimpleNamespace(content=[thinking, lookup], stop_reason="tool_use", usage=_usage()),
            _text_turn("Nothing is blocked."),
        ]

        ask.ask(workspace, create_user, "What is blocked?")

        first, second = client.messages.create.call_args_list
        assert first.kwargs["max_tokens"] == 8000
        assert first.kwargs["output_config"] == {"effort": "low"}
        assert second.kwargs["messages"][1] == {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "", "signature": "sig-round-1"},
                {"type": "tool_use", "id": "toolu_9", "name": "blocked_items", "input": {}},
            ],
        }

    def test_refusal_gets_a_short_answer(self, workspace, create_user, client):
        client.messages.create.return_value = SimpleNamespace(content=[], stop_reason="refusal", usage=_usage())

        assert ask.ask(workspace, create_user, "Anything?") == {"answer": "I can't help with that.", "sources": []}

    def test_answer_cut_off_before_any_text_is_502(self, workspace, create_user, client):
        client.messages.create.return_value = SimpleNamespace(
            content=[ThinkingBlock(type="thinking", thinking="", signature="sig")],
            stop_reason="max_tokens",
            usage=_usage(),
        )

        with pytest.raises(AgentError) as error:
            ask.ask(workspace, create_user, "Summarise everything")
        assert (error.value.status_code, error.value.field) == (502, "ai")

    def test_failed_lookup_still_gets_an_answer(self, workspace, create_user, client, monkeypatch):
        def broken(context, tool_input):
            raise RuntimeError("database went away")

        logged = []
        monkeypatch.setattr(ask, "_search_work_items", broken)
        monkeypatch.setattr(ask, "log_exception", logged.append)
        client.messages.create.side_effect = [
            _tool_turn("search_work_items", {"query": "login"}),
            _text_turn("I couldn't look that up."),
        ]

        result = ask.ask(workspace, create_user, "Is login broken?")

        assert json.loads(_tool_result_text(client.messages.create.call_args)) == {"error": "That lookup failed"}
        assert len(logged) == 1
        assert result["answer"] == "I couldn't look that up."

    def test_long_history_turns_keep_their_end(self, workspace, create_user, client):
        client.messages.create.return_value = _text_turn("Nothing found.")
        long_answer = "a" * 1000 + "b" * ask.MAX_HISTORY_CONTENT
        history = [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": long_answer}]

        ask.ask(workspace, create_user, "And now?", history=history)

        sent = client.messages.create.call_args.kwargs["messages"]
        assert sent[1] == {"role": "assistant", "content": "b" * ask.MAX_HISTORY_CONTENT}

    def test_ask_refused_without_key_or_over_limit(self, workspace, create_user, monkeypatch):
        monkeypatch.setattr(ai_calls, "anthropic_client_for", lambda workspace: None)
        with pytest.raises(AgentError) as error:
            ask.ask(workspace, create_user, "Anything?")
        assert error.value.status_code == 400

        client = MagicMock()
        monkeypatch.setattr(ai_calls, "anthropic_client_for", lambda workspace: client)
        monkeypatch.setattr(ai_calls, "model_for", lambda workspace: MODEL)
        WorkspaceAIConfig.objects.create(workspace=workspace, monthly_limit_cents=0)
        AIUsage.objects.create(workspace=workspace, kind="ask", model=MODEL, cost_cents=5)
        with pytest.raises(AgentError) as error:
            ask.ask(workspace, create_user, "Anything?")
        assert error.value.status_code == 409
        client.messages.create.assert_not_called()

    def test_usage_recorded_per_model_call(self, workspace, create_user, client):
        _project(workspace, "USE", member=create_user)
        client.messages.create.side_effect = [
            _tool_turn("blocked_items", {}),
            _tool_turn("list_milestones", {"due_within_days": 7}, tool_id="toolu_2"),
            _text_turn("Nothing is blocked."),
        ]

        ask.ask(workspace, create_user, "What is blocked?")

        rows = AIUsage.objects.filter(kind="ask", user=create_user)
        assert rows.count() == 3
        assert all(row.model == MODEL for row in rows)


@pytest.mark.unit
@pytest.mark.django_db
class TestAskEndpoint:
    @pytest.fixture(autouse=True)
    def _fake_ask(self, monkeypatch, create_user):
        cache.delete(ai_calls.rate_key(create_user))
        calls = []

        def fake(workspace, user, question, history=()):
            calls.append((question, list(history)))
            return {"answer": "ok", "sources": []}

        monkeypatch.setattr(ask, "ask", fake)
        yield calls
        cache.delete(ai_calls.rate_key(create_user))

    def test_ask_answers(self, session_client, workspace, _fake_ask):
        history = [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}]
        response = session_client.post(ASK_URL, {"question": "What's due?", "history": history}, format="json")

        assert response.status_code == 200
        assert response.data == {"answer": "ok", "sources": []}
        assert _fake_ask == [("What's due?", history)]

    def test_ask_rate_limited(self, session_client, workspace):
        for _ in range(ai_calls.RATE_LIMIT):
            assert session_client.post(ASK_URL, {"question": "Hi"}, format="json").status_code == 200

        response = session_client.post(ASK_URL, {"question": "Hi"}, format="json")

        assert ai_calls.RATE_LIMIT == 20
        assert response.status_code == 429
        assert response.data["error"]

    def test_refusal_message_is_returned(self, session_client, workspace, monkeypatch):
        def refuse(*args, **kwargs):
            raise AgentError("AI is not set up for this workspace", 400, "ai")

        monkeypatch.setattr(ask, "ask", refuse)
        response = session_client.post(ASK_URL, {"question": "Hi"}, format="json")

        assert response.status_code == 400
        assert response.data == {"error": "AI is not set up for this workspace", "field": "ai"}

    def test_guests_cannot_ask(self, session_client, workspace, create_user):
        WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(role=5)

        assert session_client.post(ASK_URL, {"question": "Hi"}, format="json").status_code == 403
