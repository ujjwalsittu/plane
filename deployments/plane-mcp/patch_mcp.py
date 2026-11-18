# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Build-time patch for the Plane MCP server image: expose fields this fork's API supports.

- project create/update: start_date, target_date, priority, status
- milestone create/update: description
- workitem create/update: completed_at (for imports)

The SDK's request models drop unknown fields (extra="ignore"); the patched ones allow them, and the
tools pass the new arguments through. Every replacement must find its anchor, so a new MCP version
that moves the code fails the image build instead of shipping a half-applied patch.
"""

import pathlib
import re
import sys

SITE = pathlib.Path("/usr/local/lib/python3.11/site-packages/plane/models")
TOOLS = pathlib.Path("/app/plane_mcp/tools")


def replace(path: pathlib.Path, old: str, new: str, count: int = 1) -> None:
    text = path.read_text()
    found = text.count(old)
    if found < count:
        sys.exit(f"patch_mcp: anchor not found {found}/{count} times in {path}:\n{old}")
    path.write_text(text.replace(old, new, count))


def allow_extra(path: pathlib.Path, *classes: str) -> None:
    text = path.read_text()
    for name in classes:
        pattern = re.compile(rf'(class {name}\(BaseModel\):\n(?:    .*\n|\n)*?    model_config = ConfigDict\(extra=)"ignore"')
        text, n = pattern.subn(r'\1"allow"', text, count=1)
        if n != 1:
            sys.exit(f"patch_mcp: model_config of {name} not found in {path}")
    path.write_text(text)


# --- SDK request models -------------------------------------------------------------------------
allow_extra(SITE / "projects.py", "CreateProject", "UpdateProject")
allow_extra(SITE / "milestones.py", "CreateMilestone", "UpdateMilestone")
allow_extra(SITE / "work_items.py", "CreateWorkItem", "UpdateWorkItem")

# --- project tool -------------------------------------------------------------------------------
project = TOOLS / "project.py"
replace(
    project,
    '            "external_source",\n            "external_id",\n        ),\n    ),\n    Action(\n        "update",',
    '            "external_source",\n            "external_id",\n            "start_date",\n            "target_date",\n'
    '            "priority",\n            "status",\n        ),\n    ),\n    Action(\n        "update",',
)
replace(
    project,
    '            "is_time_tracking_enabled",\n            "external_source",\n            "external_id",\n        ),\n'
    '        note="only the fields you pass are changed",',
    '            "is_time_tracking_enabled",\n            "external_source",\n            "external_id",\n'
    '            "start_date",\n            "target_date",\n            "priority",\n            "status",\n        ),\n'
    '        note="only the fields you pass are changed",',
)
replace(
    project,
    '    "Feature toggles are booleans; omitted ones are left as they are."\n)',
    '    "Feature toggles are booleans; omitted ones are left as they are. "\n'
    '    "start_date and target_date are YYYY-MM-DD. priority is one of: urgent, high, medium, low, none. "\n'
    '    "status is one of: backlog, planned, in_progress, paused, completed, cancelled."\n)',
)
replace(
    project,
    "        is_time_tracking_enabled: bool | None = None,\n",
    "        is_time_tracking_enabled: bool | None = None,\n"
    '        start_date: str = "",\n        target_date: str = "",\n        priority: str = "",\n        status: str = "",\n',
)
replace(
    project,
    "        zone: TimezoneEnum | None = timezone or None  # type: ignore[assignment]\n",
    "        zone: TimezoneEnum | None = timezone or None  # type: ignore[assignment]\n"
    '        if priority and priority not in ("urgent", "high", "medium", "low", "none"):\n'
    '            return "Error: priority must be one of urgent, high, medium, low, none."\n'
    '        if status and status not in ("backlog", "planned", "in_progress", "paused", "completed", "cancelled"):\n'
    '            return "Error: status must be one of backlog, planned, in_progress, paused, completed, cancelled."\n'
    "        planning = {\n"
    "            field: value\n"
    '            for field, value in {"start_date": start_date, "target_date": target_date, "priority": priority, '
    '"status": status}.items()\n'
    "            if value\n"
    "        }\n",
)
replace(
    project,
    "                    is_issue_type_enabled=workitem_types,\n                ),\n            )\n\n        if not project_id:",
    "                    is_issue_type_enabled=workitem_types,\n                    **planning,\n                ),\n"
    "            )\n\n        if not project_id:",
)
replace(
    project,
    "                    estimate=opt(estimate),\n                ),",
    "                    estimate=opt(estimate),\n                    **planning,\n                ),",
)

# --- milestone tool -----------------------------------------------------------------------------
milestone = TOOLS / "milestone.py"
replace(
    milestone,
    'Action("create", ("project_id", "title"), ("target_date", "external_source", "external_id")),',
    'Action("create", ("project_id", "title"), ("target_date", "description", "external_source", "external_id")),',
)
replace(
    milestone,
    '        ("title", "target_date", "external_source", "external_id"),',
    '        ("title", "target_date", "description", "external_source", "external_id"),',
)
replace(milestone, '        target_date: str = "",\n        add_ids', '        target_date: str = "",\n        description: str = "",\n        add_ids')
replace(
    milestone,
    "                    title=title,\n                    target_date=opt(target_date),\n",
    "                    title=title,\n                    target_date=opt(target_date),\n"
    "                    **({\"description\": description} if description else {}),\n",
)
replace(
    milestone,
    "                    title=opt(title),\n                    target_date=opt(target_date),\n",
    "                    title=opt(title),\n                    target_date=opt(target_date),\n"
    "                    **({\"description\": description} if description else {}),\n",
)

# --- workitem tool ------------------------------------------------------------------------------
workitem = TOOLS / "workitem.py"
replace(workitem, '    "target_date",\n    "sort_order",\n', '    "target_date",\n    "completed_at",\n    "sort_order",\n')
replace(
    workitem,
    '        target_date: str | None = "",\n        sort_order: float = 0,\n',
    '        target_date: str | None = "",\n        completed_at: str = "",\n        sort_order: float = 0,\n',
)
replace(
    workitem,
    '                "target_date": opt(target_date),\n                "sort_order": opt(sort_order),\n',
    '                "target_date": opt(target_date),\n                "completed_at": opt(completed_at),\n'
    '                "sort_order": opt(sort_order),\n',
)

print("patch_mcp: applied")
