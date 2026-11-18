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
