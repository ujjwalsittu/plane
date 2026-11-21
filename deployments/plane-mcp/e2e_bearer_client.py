# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Client half of e2e_bearer.sh: only `Authorization: Bearer`, no x-workspace-slug, no x-api-key."""

import asyncio
import json
import os
import urllib.request

import httpx
from fastmcp import Client
from fastmcp.client.auth import BearerAuth

URL = "http://127.0.0.1:8211/http/api-key/mcp"
TOKEN = os.environ["STUB_TOKEN"]
PROJECT, ITEM = "22222222-2222-2222-2222-222222222222", "33333333-3333-3333-3333-333333333333"


async def main():
    async with Client(URL, auth=BearerAuth(TOKEN)) as client:
        result = await client.call_tool(
            "agent_run", {"action": "start", "project_id": PROJECT, "workitem_id": ITEM, "title": "e2e run"}
        )
        print("tool result:", result.content[0].text)

    recorded = json.load(urllib.request.urlopen("http://127.0.0.1:8000/__recorded"))
    print("stub recorded:", recorded)
    assert len(recorded) == 1, recorded
    assert recorded[0]["path"] == f"/api/v1/workspaces/acme/projects/{PROJECT}/work-items/{ITEM}/agent-runs/"
    assert recorded[0]["x-api-key"] == TOKEN
    assert recorded[0]["body"] == {"title": "e2e run"}

    bad = httpx.post(
        URL,
        headers={
            "Authorization": "Bearer not-the-token",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    print("unknown token status:", bad.status_code)
    assert bad.status_code == 401
    print("E2E OK")


asyncio.run(main())
