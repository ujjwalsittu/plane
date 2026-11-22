# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Checks for the fork's MCP bearer auth, agent tools and project_update tool; run inside the built image:

    docker run --rm -v "$PWD":/t --entrypoint python plane-mcp-p7 -m unittest -v /t/test_agent_tools.py

The image has no pytest, so these are plain unittest (pytest also collects them).
"""

import asyncio
import json
import unittest
from unittest import mock

import httpx
from fastmcp import Client, FastMCP
from fastmcp.server.auth.auth import AccessToken

from plane_mcp.auth import plane_header_auth_provider as provider_module
from plane_mcp.auth.plane_header_auth_provider import PlaneHeaderAuthProvider, PlaneUnavailableError
from plane_mcp.tools import agent_tools, project_update_tools

TOKEN = "plane_api_test_token_value"
RUN = "11111111-1111-1111-1111-111111111111"
PROJECT = "22222222-2222-2222-2222-222222222222"
ITEM = "33333333-3333-3333-3333-333333333333"


def _plane(status, body, calls):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, json=body)

    return handler


class BearerAuthTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        provider_module._validated.clear()
        self.calls: list[httpx.Request] = []
        self.provider = PlaneHeaderAuthProvider(required_scopes=["read", "write"])

    def plane_answers(self, status, body):
        real = httpx.AsyncClient
        transport = httpx.MockTransport(_plane(status, body, self.calls))
        return mock.patch.object(
            provider_module.httpx, "AsyncClient", lambda **kw: real(transport=transport, **kw)
        )

    async def verify(self, headers, token=TOKEN):
        with mock.patch("fastmcp.server.dependencies.get_http_headers", return_value=headers):
            return await self.provider.verify_token(token)

    async def test_bearer_without_slug_header_uses_token_workspace_slug(self):
        with self.plane_answers(200, {"id": "u", "token_workspace_slug": "acme"}):
            access = await self.verify({})
        self.assertEqual(access.claims["workspace_slug"], "acme")
        self.assertEqual(access.claims["auth_method"], "api_key_header")
        self.assertEqual(access.token, TOKEN)
        self.assertEqual(self.calls[0].headers["x-api-key"], TOKEN)

    async def test_slug_header_wins_over_token_slug(self):
        with self.plane_answers(200, {"token_workspace_slug": "acme"}):
            access = await self.verify({"x-workspace-slug": "other"})
        self.assertEqual(access.claims["workspace_slug"], "other")

    async def test_x_api_key_header_is_preferred_over_bearer(self):
        with self.plane_answers(200, {}):
            access = await self.verify({"x-api-key": "plane_api_header_key", "x-workspace-slug": "acme"})
        self.assertEqual(access.token, "plane_api_header_key")
        self.assertEqual(self.calls[0].headers["x-api-key"], "plane_api_header_key")

    async def test_token_without_workspace_and_no_header_is_rejected(self):
        with self.plane_answers(200, {"id": "u"}):
            self.assertIsNone(await self.verify({}))

    async def test_invalid_token_is_rejected_and_not_cached(self):
        with self.plane_answers(401, {"detail": "no"}):
            self.assertIsNone(await self.verify({"x-workspace-slug": "acme"}))
        self.assertEqual(provider_module._validated, {})

    async def test_slug_is_cached_with_the_validation(self):
        with self.plane_answers(200, {"token_workspace_slug": "acme"}):
            await self.verify({})
            access = await self.verify({})
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(access.claims["workspace_slug"], "acme")

    async def test_header_validation_without_slug_does_not_satisfy_a_later_bearer_only_call(self):
        provider_module._validated[provider_module._fingerprint(TOKEN)] = (provider_module.time.time(), None)
        with self.plane_answers(200, {"token_workspace_slug": "acme"}):
            access = await self.verify({})
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(access.claims["workspace_slug"], "acme")

    async def test_plane_unavailable_keeps_a_recently_validated_token_with_cached_slug(self):
        provider_module._validated[provider_module._fingerprint(TOKEN)] = (
            provider_module.time.time() - 3600,
            "acme",
        )
        with self.plane_answers(503, {}), mock.patch.object(provider_module.asyncio, "sleep", new=mock.AsyncMock()):
            access = await self.verify({})
        self.assertEqual(access.claims["workspace_slug"], "acme")

    async def test_plane_unavailable_for_an_unknown_token_is_retryable_not_invalid(self):
        with self.plane_answers(503, {}), mock.patch.object(provider_module.asyncio, "sleep", new=mock.AsyncMock()):
            with self.assertRaises(PlaneUnavailableError):
                await self.verify({})


class AuthHeaderTests(unittest.TestCase):
    """The agent tools authenticate the way the upstream tools do: by the token's auth_method claim."""

    def headers_for(self, token):
        with mock.patch.object(agent_tools, "get_access_token", return_value=token):
            return agent_tools._auth_headers()

    def test_oauth_connection_sends_bearer_not_api_key(self):
        token = AccessToken(token="oauth-access", client_id="c", scopes=[], claims={"auth_method": "oauth"})
        self.assertEqual(self.headers_for(token), {"Authorization": "Bearer oauth-access"})

    def test_token_without_auth_method_claim_is_oauth(self):
        token = AccessToken(token="oauth-access", client_id="c", scopes=[], claims={})
        self.assertEqual(self.headers_for(token), {"Authorization": "Bearer oauth-access"})

    def test_api_key_header_connection_sends_x_api_key(self):
        token = AccessToken(token="key-1", client_id="c", scopes=[], claims={"auth_method": "api_key_header"})
        self.assertEqual(self.headers_for(token), {"x-api-key": "key-1"})

    def test_api_key_env_connection_sends_x_api_key(self):
        token = AccessToken(token="key-2", client_id="c", scopes=[], claims={"auth_method": "api_key_env"})
        self.assertEqual(self.headers_for(token), {"x-api-key": "key-2"})

    def test_bearer_api_key_connection_sends_x_api_key(self):
        # Our bearer provider validates the bearer as an API key and marks it api_key_header.
        provider_module._validated.clear()
        provider = PlaneHeaderAuthProvider(required_scopes=["read", "write"])
        real = httpx.AsyncClient
        transport = httpx.MockTransport(_plane(200, {"id": "u", "token_workspace_slug": "acme"}, []))
        with mock.patch.object(provider_module.httpx, "AsyncClient", lambda **kw: real(transport=transport, **kw)):
            with mock.patch("fastmcp.server.dependencies.get_http_headers", return_value={}):
                access = asyncio.run(provider.verify_token(TOKEN))
        self.assertEqual(self.headers_for(access), {"x-api-key": TOKEN})

    def test_environment_fallback_uses_plane_api_key(self):
        with mock.patch.dict("os.environ", {"PLANE_API_KEY": "env-key"}):
            self.assertEqual(self.headers_for(None), {"x-api-key": "env-key"})


class AgentToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.requests: list[dict] = []
        patches = [
            mock.patch.object(agent_tools, "get_plane_client_context", return_value=(None, "acme")),
            mock.patch.object(agent_tools, "_auth_headers", return_value={"x-api-key": TOKEN}),
            mock.patch.object(agent_tools.httpx, "request", side_effect=self.fake_request),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.reply = (200, {"ok": True})
        self.mcp = FastMCP("test")
        for resource in agent_tools.RESOURCES:
            resource.register(self.mcp)

    def fake_request(self, method, url, **kwargs):
        self.requests.append({"method": method, "url": url, **kwargs})
        status, body = self.reply
        return httpx.Response(status, json=body, request=httpx.Request(method, url))

    async def call(self, tool, **arguments):
        async with Client(self.mcp) as client:
            result = await client.call_tool(tool, arguments, raise_on_error=False)
        return result.content[0].text if result.content else ""

    async def test_registers_the_three_tools(self):
        async with Client(self.mcp) as client:
            names = {tool.name for tool in await client.list_tools()}
        self.assertEqual(names, {"agent_run", "approval", "event"})

    async def test_start_posts_to_the_work_item_runs(self):
        self.reply = (201, {"id": RUN})
        await self.call("agent_run", action="start", project_id=PROJECT, workitem_id=ITEM, title="Fix bug")
        sent = self.requests[0]
        self.assertEqual(sent["method"], "POST")
        self.assertTrue(
            sent["url"].endswith(f"/api/v1/workspaces/acme/projects/{PROJECT}/work-items/{ITEM}/agent-runs/")
        )
        self.assertEqual(sent["json"], {"title": "Fix bug"})
        self.assertEqual(sent["headers"], {"x-api-key": TOKEN})

    async def test_step_posts_kind_text_and_data(self):
        await self.call(
            "agent_run",
            action="step",
            project_id=PROJECT,
            workitem_id=ITEM,
            run_id=RUN,
            kind="tool",
            text="ran tests",
            data=json.dumps({"exit": 0}),
        )
        sent = self.requests[0]
        self.assertEqual(sent["method"], "POST")
        self.assertTrue(sent["url"].endswith(f"/agent-runs/{RUN}/steps/"))
        self.assertEqual(sent["json"], {"kind": "tool", "text": "ran tests", "data": {"exit": 0}})

    async def test_finish_patches_terminal_status_summary_and_cost(self):
        await self.call(
            "agent_run",
            action="finish",
            project_id=PROJECT,
            workitem_id=ITEM,
            run_id=RUN,
            status="succeeded",
            summary="done",
            cost_cents=42,
        )
        sent = self.requests[0]
        self.assertEqual(sent["method"], "PATCH")
        self.assertTrue(sent["url"].endswith(f"/agent-runs/{RUN}/"))
        self.assertEqual(sent["json"], {"status": "succeeded", "summary": "done", "cost_cents": 42})

    async def test_finish_reports_zero_cost_and_omits_cost_when_not_given(self):
        common = dict(action="finish", project_id=PROJECT, workitem_id=ITEM, run_id=RUN, status="succeeded")
        await self.call("agent_run", cost_cents=0, **common)
        await self.call("agent_run", **common)
        self.assertEqual(self.requests[0]["json"], {"status": "succeeded", "cost_cents": 0})
        self.assertEqual(self.requests[1]["json"], {"status": "succeeded"})

    async def test_list_and_retrieve_are_gets(self):
        await self.call("agent_run", action="list", project_id=PROJECT, workitem_id=ITEM)
        await self.call("agent_run", action="retrieve", project_id=PROJECT, workitem_id=ITEM, run_id=RUN)
        self.assertEqual([r["method"] for r in self.requests], ["GET", "GET"])
        self.assertTrue(self.requests[1]["url"].endswith(f"/agent-runs/{RUN}/"))

    async def test_bad_input_is_refused_without_calling_plane(self):
        text = await self.call(
            "agent_run", action="finish", project_id=PROJECT, workitem_id=ITEM, run_id=RUN, status="done"
        )
        self.assertIn("status must be one of", text)
        text = await self.call("agent_run", action="step", project_id=PROJECT, workitem_id=ITEM, run_id=RUN, kind="x")
        self.assertIn("kind must be one of", text)
        text = await self.call("agent_run", action="step", project_id=PROJECT, workitem_id=ITEM)
        self.assertIn("run_id", text)
        self.assertEqual(self.requests, [])

    async def test_plane_errors_come_back_as_text(self):
        self.reply = (403, {"error": "Only the run's reporter can change it"})
        text = await self.call("agent_run", action="retrieve", project_id=PROJECT, workitem_id=ITEM, run_id=RUN)
        self.assertIn("403", text)
        self.assertIn("reporter", text)

    async def test_approval_retrieve(self):
        await self.call("approval", action="retrieve", approval_id=RUN)
        self.assertTrue(self.requests[0]["url"].endswith(f"/api/v1/workspaces/acme/approvals/{RUN}/"))

    async def test_event_list_maps_project_id_to_project(self):
        await self.call("event", action="list", after=7, types="issue,decision", project_id=PROJECT)
        sent = self.requests[0]
        self.assertTrue(sent["url"].endswith("/api/v1/workspaces/acme/events/"))
        self.assertEqual(sent["params"], {"after": 7, "types": "issue,decision", "project": PROJECT})


class ProjectUpdateToolTests(unittest.IsolatedAsyncioTestCase):
    """project_update goes through agent_tools' request helper, so it authenticates like the agent tools."""

    def setUp(self):
        self.requests: list[dict] = []
        patches = [
            mock.patch.object(project_update_tools, "get_plane_client_context", return_value=(None, "acme")),
            mock.patch.object(agent_tools, "_auth_headers", return_value={"x-api-key": TOKEN}),
            mock.patch.object(agent_tools.httpx, "request", side_effect=self.fake_request),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.mcp = FastMCP("test")
        for resource in project_update_tools.RESOURCES:
            resource.register(self.mcp)

    def fake_request(self, method, url, **kwargs):
        self.requests.append({"method": method, "url": url, **kwargs})
        return httpx.Response(201, json={"id": RUN}, request=httpx.Request(method, url))

    async def call(self, **arguments):
        async with Client(self.mcp) as client:
            result = await client.call_tool("project_update", arguments, raise_on_error=False)
        return result.content[0].text if result.content else ""

    async def test_project_update_create_posts_health_and_body(self):
        await self.call(action="create", project_id=PROJECT, health="at_risk", body_html="<p>Slipping</p>")
        sent = self.requests[0]
        self.assertEqual(sent["method"], "POST")
        self.assertTrue(sent["url"].endswith(f"/api/v1/workspaces/acme/projects/{PROJECT}/updates/"))
        self.assertEqual(sent["json"], {"health": "at_risk", "body_html": "<p>Slipping</p>"})
        self.assertEqual(sent["headers"], {"x-api-key": TOKEN})

    async def test_plain_text_body_is_escaped_into_paragraphs(self):
        await self.call(action="create", project_id=PROJECT, health="on_track", body="Done <b>\n\nNext: QA")
        self.assertEqual(
            self.requests[0]["json"],
            {"health": "on_track", "body_html": "<p>Done &lt;b&gt;</p><p>Next: QA</p>"},
        )

    async def test_health_only_and_list(self):
        await self.call(action="create", project_id=PROJECT, health="off_track")
        await self.call(action="list", project_id=PROJECT)
        self.assertEqual(self.requests[0]["json"], {"health": "off_track"})
        self.assertEqual(self.requests[1]["method"], "GET")
        self.assertTrue(self.requests[1]["url"].endswith(f"/projects/{PROJECT}/updates/"))

    async def test_bad_input_is_refused_without_calling_plane(self):
        self.assertIn("health must be one of", await self.call(action="create", project_id=PROJECT, health="ok"))
        self.assertIn("health", await self.call(action="create", project_id=PROJECT))
        self.assertIn("project_id", await self.call(action="list"))
        text = await self.call(action="create", project_id=PROJECT, health="at_risk", body="a", body_html="<p>b</p>")
        self.assertIn("not both", text)
        self.assertEqual(self.requests, [])


class RegistryTests(unittest.TestCase):
    def test_patched_registry_advertises_the_agent_tools_and_validates(self):
        from plane_mcp.tools import register_tools
        from plane_mcp.tools.registry import action_arguments, alias_table

        mcp = FastMCP("registry")
        count = register_tools(mcp)
        names = {tool.name for tool in asyncio.run(mcp.list_tools())}
        self.assertTrue({"agent_run", "approval", "event", "project_update", "workitem"} <= names)
        self.assertEqual(count, len(names))
        self.assertEqual(set(action_arguments()["agent_run"]), {"list", "retrieve", "start", "step", "finish"})
        self.assertEqual(set(action_arguments()["project_update"]), {"list", "create"})
        alias_table()  # raises on a collision


if __name__ == "__main__":
    unittest.main()
