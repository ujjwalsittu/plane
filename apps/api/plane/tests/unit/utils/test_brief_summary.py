# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic
import httpx
import pytest
from django.core.cache import cache

from plane.utils import brief_summary

ISSUE = {
    "id": "i1",
    "name": "Fix login",
    "identifier": "OSMG-12",
    "project_identifier": "OSMG",
    "state_name": "In Progress",
    "state_group": "started",
    "priority": "high",
    "target_date": None,
}

BRIEF = {
    "since": "2026-11-19T00:00:00+00:00",
    "generated_at": "2026-11-20T10:00:00+00:00",
    "needs_me": [{"issue": ISSUE, "why": "assigned", "decision_id": None, "due": "2026-11-21", "overdue": False}],
    "blocked": [],
    "done": [],
    "milestones_due": [],
}


def _response(text="OSMG-12 needs you. OSMG-99 is imaginary.", stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="thinking", text="ignored"), SimpleNamespace(type="text", text=text)],
    )


@pytest.fixture(autouse=True)
def _env(settings, monkeypatch):
    cache.clear()
    settings.CLAUDE_MODEL = "claude-test-model"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    yield
    cache.clear()


@pytest.mark.unit
@pytest.mark.django_db
class TestBriefSummary:
    def test_summary_uses_configured_model_and_low_effort(self, workspace):
        with patch("anthropic.Anthropic") as client_cls:
            create = client_cls.return_value.beta.messages.create
            create.return_value = _response()
            result = brief_summary.summarize(BRIEF, "u1", workspace)

        kwargs = create.call_args.kwargs
        assert kwargs["model"] == "claude-test-model"
        assert kwargs["output_config"] == {"effort": "low"}
        assert kwargs["betas"] == ["server-side-fallback-2026-07-01"]
        assert kwargs["fallbacks"] == "default"
        assert kwargs["max_tokens"] == 1024
        assert client_cls.call_args.kwargs["max_retries"] == 1
        assert client_cls.call_args.kwargs["timeout"] == 30
        # Only identifiers and titles go out: nothing like an email or description.
        sent = kwargs["messages"][0]["content"]
        assert "OSMG-12" in sent and "Fix login" in sent
        # Only text blocks are used, and only identifiers that exist in the brief are returned.
        assert result["text"] == "OSMG-12 needs you. OSMG-99 is imaginary."
        assert result["item_ids"] == ["OSMG-12"]

    def test_summary_none_on_refusal_or_error(self, workspace):
        with patch("anthropic.Anthropic") as client_cls:
            create = client_cls.return_value.beta.messages.create
            create.return_value = _response(stop_reason="refusal")
            assert brief_summary.summarize(BRIEF, "u1", workspace) is None

            create.return_value = None
            create.side_effect = anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
            assert brief_summary.summarize(BRIEF, "u1", workspace) is None

    def test_summary_cached_for_an_hour(self, workspace):
        with patch("anthropic.Anthropic") as client_cls:
            create = client_cls.return_value.beta.messages.create
            create.return_value = _response()
            first = brief_summary.summarize(BRIEF, "u1", workspace)
            second = brief_summary.summarize(BRIEF, "u1", workspace)
            assert first == second
            assert create.call_count == 1
            # Another user does not share the entry; failures are not cached.
            brief_summary.summarize(BRIEF, "u2", workspace)
            assert create.call_count == 2
            create.side_effect = anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
            other = {**BRIEF, "needs_me": [{**BRIEF["needs_me"][0], "overdue": True}]}
            assert brief_summary.summarize(other, "u1", workspace) is None
            create.side_effect = None
            create.return_value = _response("OSMG-12 is fine.")
            assert brief_summary.summarize(other, "u1", workspace)["text"] == "OSMG-12 is fine."

    def test_cache_key_follows_the_data_not_the_clock(self):
        key = brief_summary._cache_key(BRIEF, "u1", "w1")
        later = {**BRIEF, "since": "2026-11-19T00:05:00+00:00", "generated_at": "2026-11-20T10:30:00+00:00"}
        assert brief_summary._cache_key(later, "u1", "w1") == key
        renamed = {**BRIEF, "needs_me": [{**BRIEF["needs_me"][0], "issue": {**ISSUE, "name": "Fix logout"}}]}
        assert brief_summary._cache_key(renamed, "u1", "w1") != key
        assert brief_summary._cache_key(BRIEF, "u2", "w1") != key

    def test_no_key_returns_none(self, monkeypatch, workspace):
        for value in (None, ""):
            if value is None:
                monkeypatch.delenv("ANTHROPIC_API_KEY")
            else:
                monkeypatch.setenv("ANTHROPIC_API_KEY", value)
            with patch("anthropic.Anthropic", MagicMock()) as client_cls:
                assert brief_summary.summarize(BRIEF, "u1", workspace) is None
                client_cls.assert_not_called()
