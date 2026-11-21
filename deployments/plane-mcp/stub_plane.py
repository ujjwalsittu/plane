# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""A stand-in for the Plane API for e2e_bearer.sh: one known token, records the agent-run POSTs."""

import json
import os
import re
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = os.environ["STUB_TOKEN"]
RECORDED: list[dict] = []
RUNS = re.compile(r"^/api/v1/workspaces/([^/]+)/projects/([^/]+)/work-items/([^/]+)/agent-runs/$")


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/__recorded":
            return self.reply(200, RECORDED)
        if self.path == "/api/v1/users/me/":
            if self.headers.get("x-api-key") == TOKEN:
                return self.reply(200, {"id": "user-1", "token_workspace_slug": "acme"})
            return self.reply(401, {"detail": "Invalid API key"})
        self.reply(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        match = RUNS.match(self.path)
        if not match:
            return self.reply(404, {})
        RECORDED.append({"path": self.path, "x-api-key": self.headers.get("x-api-key"), "body": body})
        self.reply(201, {"id": "run-1", "status": "running", "title": body.get("title", "")})

    def log_message(self, *args):
        pass


HTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
