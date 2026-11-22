# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The one wrapper every person-started Claude call goes through: checks the key and the monthly limit, makes the
call, and records its cost in AIUsage so it counts toward the same limit as cloud runs."""

import math

from django.core.cache import cache

from plane.db.models import AIUsage
from plane.utils.agents import AgentError
from plane.utils.ai_config import anthropic_client_for, check_spend, model_for
from plane.utils.exception_logger import log_exception

# {model_id: (input cents per million tokens, output cents per million tokens)}, USD.
# Copied from the claude-api skill's "Current Models" pricing table (cached 2026-11-03).
PRICES = {
    "claude-fable-5-2": (800, 4000),
    "claude-mythos-5-2": (800, 4000),
    "claude-fable-5-1": (1000, 5000),
    "claude-mythos-5-1": (1000, 5000),
    "claude-fable-5": (1000, 5000),
    "claude-opus-5-5": (400, 2000),
    "claude-opus-5": (500, 2500),
    "claude-opus-4-8": (500, 2500),
    "claude-opus-4-7": (500, 2500),
    "claude-opus-4-6": (500, 2500),
    "claude-sonnet-5-5": (200, 1000),
    "claude-sonnet-5": (200, 1000),
    "claude-sonnet-4-6": (300, 1500),
    "claude-haiku-5-5": (10, 50),
    "claude-haiku-4-5": (100, 500),
}
# Paid AI requests one person may make across Ask, Triage and Meeting notes extract in a rolling window
RATE_LIMIT = 20
RATE_WINDOW_SECONDS = 600

# An unknown model is charged the most expensive listed price
_MOST_EXPENSIVE = (max(p[0] for p in PRICES.values()), max(p[1] for p in PRICES.values()))


def cost_cents(model, input_tokens, output_tokens):
    """Cost of a call in whole cents, rounded up so any non-empty call costs at least 1 cent."""
    input_price, output_price = PRICES.get(model, _MOST_EXPENSIVE)
    return math.ceil((input_tokens * input_price + output_tokens * output_price) / 1_000_000)


def ai_message(workspace, user, kind, **kwargs):
    """Call the Claude Messages API for `user` and record the cost. `kwargs` go to `messages.create`."""
    import anthropic

    client = anthropic_client_for(workspace)
    if client is None:
        raise AgentError("AI is not set up for this workspace", 400, "ai")
    check_spend(workspace)
    model = model_for(workspace)
    try:
        # The client is built with max_retries=1
        response = client.messages.create(model=model, **kwargs)
    except anthropic.APIError as error:
        log_exception(error)
        raise AgentError("The AI service didn't answer; try again", 502, "ai")
    usage = response.usage
    AIUsage.objects.create(
        workspace=workspace,
        user=user,
        kind=kind,
        model=model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_cents=cost_cents(model, usage.input_tokens, usage.output_tokens),
    )
    return response


def rate_key(user):
    return f"ai:rate:{user.id}"


def check_ai_rate(user):
    """At most RATE_LIMIT paid AI requests per person per RATE_WINDOW_SECONDS, shared across the AI features."""
    key = rate_key(user)
    cache.add(key, 0, timeout=RATE_WINDOW_SECONDS)
    try:
        count = cache.incr(key)
    except ValueError:  # expired between add and incr
        cache.set(key, 1, timeout=RATE_WINDOW_SECONDS)
        count = 1
    if count > RATE_LIMIT:
        raise AgentError("You've made a lot of AI requests; try again in a few minutes", 429, "rate_limited")


def require_person(user):
    """Paid AI suggestions are for people: an agent calling the API does its own reasoning."""
    if getattr(user, "is_bot", False):
        raise AgentError("AI suggestions are for people; agents do their own reasoning", 403, "error")


def tool_answer(response, tool_name):
    """The input of the one `tool_name` call in a structured-output response. The call is made with
    tool_choice auto (forced tool use is rejected on current models), so a missing call, a cut-off answer or a
    refusal is an error rather than an empty answer."""
    if response.stop_reason == "refusal":
        raise AgentError("The AI declined to answer this request", 502, "ai")
    if response.stop_reason == "max_tokens":
        raise AgentError("The AI's answer was cut off; try again", 502, "ai")
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
            return block.input
    raise AgentError("The AI didn't return an answer; try again", 502, "ai")
