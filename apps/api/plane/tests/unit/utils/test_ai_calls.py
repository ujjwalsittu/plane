# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import httpx
import pytest

from plane.db.models import AIUsage, WorkspaceAIConfig
from plane.utils import ai_calls, ai_config
from plane.utils.agents import AgentError

MODEL = "claude-sonnet-5-5"


def _client(response=None, error=None):
    client = MagicMock()
    if error is not None:
        client.messages.create.side_effect = error
    else:
        client.messages.create.return_value = response
    return client


def _response(input_tokens=1000, output_tokens=500):
    return SimpleNamespace(usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens))


@pytest.fixture
def patch_client(monkeypatch):
    def _patch(client):
        monkeypatch.setattr(ai_calls, "anthropic_client_for", lambda workspace: client)
        monkeypatch.setattr(ai_calls, "model_for", lambda workspace: MODEL)

    return _patch


@pytest.mark.unit
@pytest.mark.django_db
class TestAIMessage:
    def test_ai_message_records_usage_and_cost(self, workspace, create_user, patch_client):
        client = _client(_response(1000, 500))
        patch_client(client)

        response = ai_calls.ai_message(workspace, create_user, "ask", max_tokens=100, messages=[])

        assert response is client.messages.create.return_value
        client.messages.create.assert_called_once_with(model=MODEL, max_tokens=100, messages=[])
        row = AIUsage.objects.get()
        input_price, output_price = ai_calls.PRICES[MODEL]
        assert (row.workspace_id, row.user_id, row.kind, row.model) == (workspace.id, create_user.id, "ask", MODEL)
        assert (row.input_tokens, row.output_tokens) == (1000, 500)
        # 1000 in + 500 out, rounded up: 1 cent at the Sonnet 5.5 price
        assert row.cost_cents == -(-(1000 * input_price + 500 * output_price) // 1_000_000)

    def test_cost_rounds_up_and_unknown_model_is_most_expensive(self):
        assert ai_calls.cost_cents(MODEL, 1, 0) == 1
        assert ai_calls.cost_cents("claude-unknown", 1_000_000, 0) == max(p[0] for p in ai_calls.PRICES.values())
        assert ai_calls.cost_cents("claude-unknown", 0, 1_000_000) == max(p[1] for p in ai_calls.PRICES.values())

    def test_ai_message_refused_over_limit_records_nothing(self, workspace, create_user, patch_client):
        WorkspaceAIConfig.objects.create(workspace=workspace, monthly_limit_cents=0)
        AIUsage.objects.create(workspace=workspace, kind="ask", model=MODEL, cost_cents=5)
        client = _client(_response())
        patch_client(client)

        with pytest.raises(AgentError) as error:
            ai_calls.ai_message(workspace, create_user, "ask", max_tokens=10, messages=[])

        assert error.value.status_code == 409
        assert error.value.field == "spend_limit_reached"
        client.messages.create.assert_not_called()
        assert AIUsage.objects.count() == 1

    def test_ai_message_without_key_is_400(self, workspace, create_user, monkeypatch):
        monkeypatch.setattr(ai_calls, "anthropic_client_for", lambda workspace: None)

        with pytest.raises(AgentError) as error:
            ai_calls.ai_message(workspace, create_user, "triage", max_tokens=10, messages=[])

        assert (str(error.value), error.value.status_code, error.value.field) == (
            "AI is not set up for this workspace",
            400,
            "ai",
        )
        assert AIUsage.objects.count() == 0

    def test_api_error_is_502_and_records_nothing(self, workspace, create_user, patch_client):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        patch_client(_client(error=anthropic.APIConnectionError(request=request)))

        with pytest.raises(AgentError) as error:
            ai_calls.ai_message(workspace, create_user, "meeting_notes", max_tokens=10, messages=[])

        assert (str(error.value), error.value.status_code, error.value.field) == (
            "The AI service didn't answer; try again",
            502,
            "ai",
        )
        assert AIUsage.objects.count() == 0


@pytest.mark.unit
@pytest.mark.django_db
def test_spend_includes_usage_and_managed_runs_only(workspace, create_user):
    from datetime import datetime, timedelta, timezone

    from plane.db.models import AgentRun, Issue, Project, State

    project = Project.objects.create(name="Alpha", identifier="ALP", workspace=workspace, created_by=create_user)
    state = State.objects.create(name="Started", group="started", project=project, workspace=workspace)
    issue = Issue.objects.create(name="Item", project=project, workspace=workspace, state=state)
    AgentRun.objects.create(project=project, issue=issue, actor=create_user, kind="managed", cost_cents=30)
    AgentRun.objects.create(project=project, issue=issue, actor=create_user, kind="external", cost_cents=999)
    AIUsage.objects.create(workspace=workspace, user=create_user, kind="ask", model=MODEL, cost_cents=7)
    old = AIUsage.objects.create(workspace=workspace, kind="triage", model=MODEL, cost_cents=500)
    last_month = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0) - timedelta(days=1)
    AIUsage.objects.filter(pk=old.pk).update(created_at=last_month)

    assert ai_config.spent_this_month_cents(workspace) == 37
