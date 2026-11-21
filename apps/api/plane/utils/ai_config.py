# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Per-workspace Claude key, model and monthly spend limit. The workspace key wins over the instance key."""

import os
from datetime import datetime, timezone

from django.conf import settings
from django.db.models import Sum

from plane.db.models import AgentRun, APIToken, WorkspaceAgent, WorkspaceAIConfig
from plane.license.utils.encryption import decrypt_data, encrypt_data
from plane.utils.agents import AgentError, _require_admin

CLIENT_TIMEOUT_SECONDS = 30
MODEL_MAX_LENGTH = 100


def get_config(workspace):
    config, _ = WorkspaceAIConfig.objects.get_or_create(workspace=workspace)
    return config


def instance_key():
    return os.environ.get("ANTHROPIC_API_KEY", "")


def anthropic_client_for(workspace):
    """The workspace's client, else the instance's, else None. A stored key that no longer decrypts (SECRET_KEY
    changed) marks the config broken and returns None, with no fallback, so the break is noticed."""
    import anthropic

    config = WorkspaceAIConfig.objects.filter(workspace=workspace).first()
    key = ""
    if config is not None and config.api_key_encrypted:
        try:
            key = decrypt_data(config.api_key_encrypted)
        except Exception:
            key = ""
        if not key:
            config.status = "broken"
            config.last_error = "reconnect"
            config.save(update_fields=["status", "last_error", "updated_at"])
            return None
    key = key or instance_key()
    if not key:
        return None
    return anthropic.Anthropic(api_key=key, timeout=CLIENT_TIMEOUT_SECONDS, max_retries=1)


def model_for(workspace):
    config = WorkspaceAIConfig.objects.filter(workspace=workspace).first()
    return (config.model if config else "") or settings.CLAUDE_MODEL


def spent_this_month_cents(workspace):
    """Sum of this UTC month's agent run cost."""
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = AgentRun.objects.filter(workspace=workspace, created_at__gte=start).aggregate(total=Sum("cost_cents"))
    return int(total["total"] or 0)


def check_spend(workspace, extra_cents=0):
    config = WorkspaceAIConfig.objects.filter(workspace=workspace).first()
    limit = config.monthly_limit_cents if config else None
    if limit is None:
        return
    if spent_this_month_cents(workspace) + extra_cents > limit:
        raise AgentError("Monthly AI limit reached", 409, "spend_limit_reached")


def set_api_key(workspace, key, actor):
    """Check the key with Anthropic, then store it encrypted. A rejected key is never stored."""
    import anthropic

    _require_admin(workspace, actor)
    if not isinstance(key, str) or not key.strip():
        raise AgentError("An API key is required", 400, "api_key")
    key = key.strip()
    try:
        anthropic.Anthropic(api_key=key, timeout=CLIENT_TIMEOUT_SECONDS, max_retries=0).models.list(limit=1)
    except anthropic.AuthenticationError:
        raise AgentError("That key was rejected by Anthropic", 400, "api_key")
    except anthropic.APIError:
        raise AgentError("Could not reach Anthropic to check the key", 502, "api_key")
    encrypted = encrypt_data(key)
    if not encrypted:
        raise AgentError("Could not store the key", 500, "api_key")
    config = get_config(workspace)
    config.api_key_encrypted = encrypted
    config.status = "ok"
    config.last_error = ""
    config.save(update_fields=["api_key_encrypted", "status", "last_error", "updated_at"])
    return config


def clear_api_key(workspace, actor):
    _require_admin(workspace, actor)
    config = get_config(workspace)
    config.api_key_encrypted = ""
    config.status = "unset"
    config.last_error = ""
    config.save(update_fields=["api_key_encrypted", "status", "last_error", "updated_at"])
    return config


def _clean_limit(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2_000_000_000:
        raise AgentError("The monthly limit must be a whole number of cents", 400, "monthly_limit_cents")
    return value


def _clean_model(value):
    if not isinstance(value, str) or len(value.strip()) > MODEL_MAX_LENGTH:
        raise AgentError("Invalid model", 400, "model")
    return value.strip()


def update_settings(workspace, data, actor):
    """Apply an admin PUT: api_key, model, monthly_limit_cents (null clears). Everything is checked before saving."""
    _require_admin(workspace, actor)
    fields = {}
    if "model" in data:
        fields["model"] = _clean_model(data["model"])
    if "monthly_limit_cents" in data:
        fields["monthly_limit_cents"] = _clean_limit(data["monthly_limit_cents"])
    if data.get("api_key") is not None:
        set_api_key(workspace, data["api_key"], actor)
    config = get_config(workspace)
    if fields:
        for name, value in fields.items():
            setattr(config, name, value)
        config.save(update_fields=[*fields, "updated_at"])
    return config


def agent_cloud_ready(agent):
    """The agent has its Managed Agents agent and a vault holding its current active token."""
    token_id = (
        APIToken.objects.filter(user_id=agent.user_id, is_active=True)
        .order_by("-created_at")
        .values_list("id", flat=True)
        .first()
    )
    has_handles = bool(agent.ma_agent_id and agent.ma_vault_id)
    return has_handles and token_id is not None and agent.ma_vault_token_id == token_id


def cloud_agents_ready(workspace, config):
    """The cloud environment is set and every active agent is ready (see agent_cloud_ready)."""
    if not config.ma_environment_id:
        return False
    return all(agent_cloud_ready(agent) for agent in WorkspaceAgent.objects.filter(workspace=workspace, is_active=True))


def settings_payload(workspace):
    """Never includes the key."""
    config = get_config(workspace)
    has_key = bool(config.api_key_encrypted)
    return {
        "has_key": has_key,
        "uses_instance_key": not has_key and bool(instance_key()),
        "status": config.status,
        "last_error": config.last_error,
        "model": config.model,
        "monthly_limit_cents": config.monthly_limit_cents,
        "spent_this_month_cents": spent_this_month_cents(workspace),
        "cloud_agents_ready": cloud_agents_ready(workspace, config),
    }
