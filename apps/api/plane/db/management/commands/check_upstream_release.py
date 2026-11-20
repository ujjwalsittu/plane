# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.core.management.base import BaseCommand, CommandError

# Module imports
from plane.utils.upstream_sync import UpstreamSyncError, check


class Command(BaseCommand):
    help = (
        "Open a work item when makeplane/plane has a release newer than this build. "
        "The project comes from UPSTREAM_SYNC_TARGET (<workspace slug>/<PROJECT>) or --target."
    )

    def add_arguments(self, parser):
        parser.add_argument("--target", default=None, help="<workspace slug>/<PROJECT>, overrides the env var")
        parser.add_argument("--dry-run", action="store_true", help="Report without creating anything")

    def handle(self, *args, **options):
        try:
            result = check(target=options["target"], dry_run=options["dry_run"])
        except UpstreamSyncError as exc:
            raise CommandError(str(exc)) from exc
        line = f"upstream {result['latest']} vs current v{result['current']}: {result['status']}"
        if result.get("work_item"):
            line += f" ({result['work_item']})"
        self.stdout.write(line)
