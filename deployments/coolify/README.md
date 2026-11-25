# Coolify runbook (plane.azeonics.com)

Service: Coolify project "Project Management", service `plane` (`uppph92wubnjsj2sp5ghyc6x`).
Images: `ghcr.io/ujjwalsittu/plane-*`, selected by the service env `APP_RELEASE` (`sha-<7>` or a `custom-v*` tag).

## Deploy

Push to `custom`; the "Custom images" workflow runs the unit tests, then builds and pushes `:sha-<7>`.
When it is green:

```bash
COOLIFY_TOKEN=... deployments/coolify/deploy-plane.sh <commit>
```

The script checks the images exist, sets `APP_RELEASE`, deploys, and waits until
`https://plane.azeonics.com/version.json` reports the commit and `/api/instances/` answers 200.
If the stack stalls it asks Coolify to start the service. Don't use a plain Coolify "restart" to
change releases: it keeps the old `APP_RELEASE`.

### Plane MCP server

The `plane-mcp` service (`pllozvf5ra9qd0wlwzb9tynu`) is separate from `plane`. Its compose names a
fixed image, `ghcr.io/ujjwalsittu/plane-mcp:sha-<7>`, and `APP_RELEASE` does not change it.
Redeploying the service without changing that tag restarts the old image. When a release changes
`deployments/plane-mcp`:

1. Set the image tag in the service's compose to the new `sha-<7>`. In the Coolify UI, use the
   service's compose editor. Through the API, PATCH `docker_compose_raw`, base64-encoded, and keep
   the environment entries as `${VAR:-default}` references.
2. Deploy the service.
3. Check the `mcp` container log for `Plane MCP: advertising N tools`. N should match the release:
   34 at `sha-65d0213`.

## Roll back

Run the deploy script with the previous release (it prints it on failure). Migrations are only
added, never reverted automatically; if a release added a migration, restore the database from the
pre-deploy dump as well (below).

## Backups

Scheduled task `pre-upgrade-pgdump` (container `plane-db`, run on demand) writes
`plane-YYYYMMDD-HHMMSS.dump` to `/var/lib/postgresql/data/backups` inside the database volume.
Take one before every deploy that adds migrations. Note: these dumps live in the same volume as the
database and nothing runs on a schedule yet.

## Restore drill

Scheduled task `restore-drill` (disabled, run on demand) runs `restore-drill.sh` from the backups
folder: it restores the newest dump into a scratch database `plane_restore_drill`, compares row
counts of the main tables with the live database, prints `RESTORE DRILL OK`, and drops the scratch
database. Last run: 2026-11-18, OK (dump `plane-20261118-065735.dump`, 8 s).

To restore for real, stop the `api`, `worker`, `beat-worker` and `live` containers, then in
`plane-db`: `pg_restore -h 127.0.0.1 -U "$POSTGRES_USER" -d plane --clean --if-exists --no-owner <dump>`,
and start the service again.

Coolify note: scheduled-task commands are limited to about 255 characters (longer ones fail with a
bare HTTP 500), which is why the drill lives in a script file.

## Agent settings

Cloud agents need `PLANE_MCP_URL` (the public URL of the Plane MCP server, `deployments/plane-mcp`) on
both the `api` and the `worker` containers; without it "Set up cloud agents" refuses with
"PLANE_MCP_URL is not configured on this instance".
