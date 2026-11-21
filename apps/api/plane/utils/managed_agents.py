# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Cloud agents on Claude Managed Agents: one environment per workspace, and for every Plane agent a matching
Managed Agents agent plus a vault holding its Plane API token for the Plane MCP server. Nothing here runs until a
workspace admin sets cloud agents up (the workspace's environment id is set)."""

from urllib.parse import urlparse

from django.conf import settings
from django.db import transaction

from plane.db.models import APIToken, WorkspaceAgent, WorkspaceAIConfig
from plane.utils.agents import AgentError, _require_admin
from plane.utils.ai_config import anthropic_client_for, get_config, model_for
from plane.utils.exception_logger import log_exception

MCP_SERVER_NAME = "plane"
ERROR_PREFIX = "cloud_agents"
ALWAYS_ALLOW = {"type": "always_allow"}
# The setup endpoint runs in the request, so each of its calls is short and not retried.
SETUP_TIMEOUT_SECONDS = 10

AGENT_SYSTEM_PROMPT = """You work for the {workspace} workspace in Plane, through the Plane MCP tools.

- The work item in your first message is your brief. Read it, its comments and its links before you start.
- Post progress as comments on that work item, so the people following it can see where things stand.
- When you need a person's choice, create a decision request on the work item and stop until it is answered.
- Risky actions may answer `approval_required`. Note it in a comment and move on to other work; never retry it.
- Mounted repositories are under `/workspace`. Push a branch and open the pull request through the GitHub REST API;
  the git proxy authenticates those requests for you.
- Finish with a short summary of what changed and what is left."""


def _mcp_url():
    return getattr(settings, "PLANE_MCP_URL", "") or ""


def _client(workspace, client=None):
    if client is not None:
        return client
    client = anthropic_client_for(workspace)
    if client is None:
        raise AgentError("Add a Claude API key before setting up cloud agents", 400, ERROR_PREFIX)
    return client


def _plane_host():
    return urlparse(settings.WEB_URL or settings.APP_BASE_URL or "").hostname or ""


def _tools():
    return [
        {
            "type": "agent_toolset_20260401",
            "default_config": {"enabled": True, "permission_policy": ALWAYS_ALLOW},
            "configs": [
                {"name": "web_search", "enabled": False},
                {"name": "web_fetch", "enabled": False},
            ],
        },
        {
            "type": "mcp_toolset",
            "mcp_server_name": MCP_SERVER_NAME,
            "default_config": {"permission_policy": ALWAYS_ALLOW},
        },
    ]


def ensure_environment(workspace, client=None):
    """The workspace's cloud environment id, created on first use."""
    config = get_config(workspace)
    if config.ma_environment_id:
        return config.ma_environment_id
    hosts = [host for host in (_plane_host(), "api.github.com", "github.com") if host]
    environment = _client(workspace, client).beta.environments.create(
        name=f"plane-{workspace.slug}",
        config={
            "type": "cloud",
            "networking": {
                "type": "limited",
                "allow_package_managers": True,
                "allow_mcp_servers": True,
                "allowed_hosts": hosts,
            },
        },
    )
    config.ma_environment_id = environment.id
    config.save(update_fields=["ma_environment_id", "updated_at"])
    return environment.id


def sync_ma_agent(agent, client=None):
    """Create or update the agent's Managed Agents agent."""
    workspace = agent.workspace
    params = {
        "name": agent.name,
        "model": model_for(workspace),
        "system": AGENT_SYSTEM_PROMPT.format(workspace=workspace.name),
        "mcp_servers": [{"type": "url", "name": MCP_SERVER_NAME, "url": _mcp_url()}],
        "tools": _tools(),
    }
    agents_api = _client(workspace, client).beta.agents
    # No version on update: Plane owns this agent, so the latest definition always wins.
    remote = agents_api.update(agent.ma_agent_id, **params) if agent.ma_agent_id else agents_api.create(**params)
    agent.ma_agent_id = remote.id
    agent.ma_agent_version = remote.version
    agent.save(update_fields=["ma_agent_id", "ma_agent_version", "updated_at"])


def sync_vault(agent, token, client=None):
    """Put the agent's Plane token in its vault as the one credential for the Plane MCP server, replacing any
    earlier one (credential keys can't change, so the old credential is archived, which purges its secret).
    `ma_vault_token_id` is cleared first and set only once the new credential exists, so a failure part way
    never leaves the vault looking current."""
    vaults = _client(agent.workspace, client).beta.vaults
    token_id = APIToken.objects.filter(token=token).values_list("id", flat=True).first()
    agent.ma_vault_token_id = None
    agent.save(update_fields=["ma_vault_token_id", "updated_at"])
    if not agent.ma_vault_id:
        vault = vaults.create(display_name=f"plane-{agent.workspace.slug}-{agent.name}")
        agent.ma_vault_id = vault.id
        agent.save(update_fields=["ma_vault_id", "updated_at"])
    else:
        for credential in vaults.credentials.list(agent.ma_vault_id):
            if getattr(credential.auth, "type", "") == "static_bearer":
                vaults.credentials.archive(credential.id, vault_id=agent.ma_vault_id)
    vaults.credentials.create(
        agent.ma_vault_id, auth={"type": "static_bearer", "mcp_server_url": _mcp_url(), "token": token}
    )
    agent.ma_vault_token_id = token_id
    agent.save(update_fields=["ma_vault_token_id", "updated_at"])


def archive_ma_agent(agent, client=None):
    """A deactivated agent can't start new cloud sessions, and its vault (and token) is purged."""
    beta = _client(agent.workspace, client).beta
    if agent.ma_agent_id:
        beta.agents.archive(agent.ma_agent_id)
    if agent.ma_vault_id:
        beta.vaults.archive(agent.ma_vault_id)
    agent.ma_vault_token_id = None
    agent.save(update_fields=["ma_vault_token_id", "updated_at"])


def active_token(agent):
    """The agent's current API token row (id and token), or None."""
    return APIToken.objects.filter(user_id=agent.user_id, is_active=True).order_by("-created_at").first()


def _is_set_up(workspace):
    return WorkspaceAIConfig.objects.filter(workspace=workspace).exclude(ma_environment_id="").exists()


def _record_error(workspace, agent, exc):
    log_exception(exc)
    config = get_config(workspace)
    # The class name only: an error message is never allowed to carry a token into the settings payload.
    config.last_error = f"{ERROR_PREFIX}: could not sync {agent.name} ({type(exc).__name__})"
    config.save(update_fields=["last_error", "updated_at"])


def sync_agent(agent):
    """Bring the Managed Agents side in line with the agent as stored (the background task). A no-op until cloud
    agents are set up. The agent and vault steps run independently, so an agent-update failure never keeps a
    rotated token out of the vault. Errors are logged and recorded on the workspace's AI config."""
    if not _is_set_up(agent.workspace):
        return
    if not agent.is_active:
        try:
            archive_ma_agent(agent)
        except Exception as exc:
            _record_error(agent.workspace, agent, exc)
        return
    try:
        sync_ma_agent(agent)
    except Exception as exc:
        _record_error(agent.workspace, agent, exc)
    token = active_token(agent)
    if token is not None and agent.ma_vault_token_id != token.id:
        try:
            sync_vault(agent, token.token)
        except Exception as exc:
            _record_error(agent.workspace, agent, exc)


def queue_sync(agent):
    """Sync after the current transaction commits, in Celery, with only the agent id as the task argument."""
    if not _is_set_up(agent.workspace):
        return
    from plane.bgtasks.cloud_agents_task import sync_cloud_agent

    agent_id = str(agent.id)
    transaction.on_commit(lambda: sync_cloud_agent.delay(agent_id))


def setup_cloud_agents(workspace, actor):
    """Create the workspace environment (once) and sync every active agent with its current token. Runs in the
    request (an explicit admin action that reports errors), with a short timeout per call."""
    _require_admin(workspace, actor)
    if not _mcp_url():
        raise AgentError("PLANE_MCP_URL is not configured on this instance", 400, ERROR_PREFIX)
    client = _client(workspace).with_options(timeout=SETUP_TIMEOUT_SECONDS, max_retries=0)
    try:
        ensure_environment(workspace, client)
    except Exception as exc:
        log_exception(exc)
        raise AgentError(f"Could not create the cloud environment ({type(exc).__name__})", 400, ERROR_PREFIX)
    for agent in WorkspaceAgent.objects.filter(workspace=workspace, is_active=True).select_related("workspace"):
        try:
            sync_ma_agent(agent, client)
            token = active_token(agent)
            if token is not None and agent.ma_vault_token_id != token.id:
                sync_vault(agent, token.token, client)
        except Exception as exc:
            _record_error(workspace, agent, exc)
            raise AgentError(f"Could not set up {agent.name} ({type(exc).__name__})", 400, ERROR_PREFIX)
    config = get_config(workspace)
    if config.last_error.startswith(ERROR_PREFIX):
        config.last_error = ""
        config.save(update_fields=["last_error", "updated_at"])
    return config
