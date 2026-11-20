# Upstream sync: merging a new Plane release into `custom`

This fork's `custom` branch is upstream Plane plus our own features. It's deployed to
plane.azeonics.com as `ghcr.io/ujjwalsittu/plane-*:sha-<7>`, built by the "Custom images" workflow.

## How you find out

A Coolify scheduled task ("upstream-release-check", 06:00 UTC, in the api container) runs `python manage.py check_upstream_release` every
day. When makeplane/plane publishes a release newer than `apps/api/package.json`'s version, it opens
one high-priority work item in the project set by `UPSTREAM_SYNC_TARGET` (`azeonics/PLAT`). Release
candidates are ignored, and a release never gets a second work item, even if you delete the first.

To check by hand: `python manage.py check_upstream_release --dry-run` in the api container.

Merge **releases** only (tags like `v1.6.0`), never `upstream/preview`.

## Checklist

1. **Branch.**
   ```bash
   git fetch upstream --tags
   git checkout custom && git pull
   git checkout -b sync/v1.6.0
   git merge v1.6.0
   ```
2. **Resolve conflicts.** The usual ones:
   - `apps/api/migrations_lockfile.txt` and migration numbers. If both sides added migrations to
     `db`, keep upstream's files, renumber ours to follow theirs, fix each renumbered migration's
     `dependencies`, then run `uv run python manage.py makemigrations --check` and let
     `makemigrations` rewrite the lockfile. Never edit the lockfile by hand.
   - `packages/i18n/src/locales/*`. Our strings live in `milestone.json`; keep both sides' keys.
   - `apps/web/app/routes/core.ts`, the sidebar constants in `packages/constants/src/workspace.ts`
     and `apps/web/components/workspace/sidebar/*`: keep upstream's changes plus our entries.
   - `apps/api/plane/api/urls/__init__.py`, `apps/api/plane/db/models/__init__.py` and
     `apps/api/plane/celery.py`: keep both.
   - The editor (`packages/editor`): re-check our Markdown mode and code-block fixes.
3. **Check upstream's own changes** to the areas we extended: external API views
   (`apps/api/plane/api/views/issue.py`, `project.py`, `page.py`), `pql_lite.py`, and the workspace
   features endpoint in `apps/api/plane/api/views/milestone.py`. If upstream now ships something we
   built (e.g. teams, releases), compare before keeping ours.
4. **Test.**
   ```bash
   docker compose -f docker-compose-test.yml run --rm api-tests sh -c "pytest -p no:cacheprovider --create-db -q"
   pnpm turbo run check:types --filter=web
   pnpm --filter=@plane/i18n sync:check
   pnpm check:lint
   ```
5. **Merge and push.** Merge the sync branch into `custom` and push; wait for "Custom images":
   `gh run watch <id> --repo ujjwalsittu/plane`.
6. **Back up.** Run the Coolify scheduled task "pre-upgrade-pgdump" on the Plane service, and confirm a new
   `plane-<date>.dump` in its output.
7. **Deploy.** In Coolify set `APP_RELEASE=sha-<7>` on the Plane service (re-set it even if it
   looks right; saving the env page can reset it), then deploy.
8. **Verify.**
   - `https://plane.azeonics.com/version.json` shows the new sha; `/api/instances/` returns 200.
   - The admin instance page shows the new upstream version.
   - Spot-check our features: GitHub panel on a work item, initiatives, releases, templates, teams,
     work logs, workspace pages, and the MCP tools (`workitem count`, `release list`).
9. **Close out.** Mark the upstream-release work item Done with the deployed sha, and translate any
   new upstream strings that landed in English only.

## Rolling back

Set `APP_RELEASE` back to the previous sha and deploy. If the release ran migrations that broke
data, restore the dump from step 6 (see `restore-drill.sh` in the backups folder of the database
volume) before deploying the old image.
