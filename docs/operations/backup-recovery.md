# Database backup and recovery

Production data lives in one Neon project, `mirrorself.` (`rapid-surf-20697501`,
AWS us-east-2, PostgreSQL 18), branch `production` (`br-aged-wind-bdn9tb22`),
database `neondb`. Supabase holds only sign-in identities; it holds no Twin
data.

## What protects the data today

| Mechanism | Coverage | Notes |
|---|---|---|
| Neon point-in-time restore (history) | The last **6 hours** (`history_retention_seconds = 21600`) | Restore to any second inside the window. The window is the plan's; a paid plan extends it to days. |
| Manual snapshots | Whenever one is taken | `pre-0008-2026-11-17` (`snap-damp-resonance-bdz9pu6r`) was taken before the migration 0008 deploy. |
| Scheduled snapshots | **None configured** | Recommended below. |
| Logical dumps (`pg_dump`) | **None** | Recommended below; independent of Neon. |

With only a 6-hour window and no schedule, a mistake noticed the next day is
not recoverable from Neon alone. Closing that gap is the first recommendation.

## Recommendations (need the owner)

1. **Daily snapshots.** Neon console → project → Backup & restore → snapshot
   schedule: daily, keep 7 days. (Not enabled automatically: snapshot storage
   can be billable depending on the plan.)
2. **Weekly off-platform dump**, kept outside Neon (for example a private
   storage bucket):
   ```bash
   pg_dump --format=custom --no-owner --no-privileges \
     "postgresql://neondb_owner:<password>@<direct-host>/neondb?sslmode=require" \
     -f mirrorself-$(date +%F).dump
   ```
   Use the **direct** host (not `-pooler`); `pg_dump` needs a session.
3. Before every deploy that includes a migration: take a manual snapshot
   (the runbook's deploy checklist does this).

## Restore procedures

### A. Recover from a bad change in the last 6 hours (most likely case)

1. Neon console → `production` branch → **Restore** → choose a timestamp
   just before the incident. Neon first creates a backup branch of the
   current state, so the restore itself is reversible.
2. Or, without touching production: create a branch from `production` at the
   timestamp, inspect it, and copy back only the rows that were lost.

### B. Restore a snapshot

1. Restore the snapshot **into a new branch** (do not finalize):
   Neon console → Backup & restore → snapshot → Restore → new branch.
2. Verify the new branch (row counts, the affected data).
3. Only then finalize, which swaps the restored branch in as `production`.
   The API's connection string targets the endpoint, which stays attached, so
   no configuration change is needed.

### C. Restore from a dump into a fresh database

```bash
createdb ... # or create a database in the Neon console
pg_restore --no-owner --no-privileges --dbname "<target url>" mirrorself-YYYY-MM-DD.dump
```

Then run `python -m alembic current` against it to confirm the schema
version, point `DATABASE_URL` at it, and redeploy.

## Tested

**Restore drill, 2026-11-17:** snapshot `pre-0008-2026-11-17` restored into
branch `restore-drill-2026-11-17` (`br-cool-dream-bd9mdk4y`) without
finalizing. Production and the restored branch compared equal on schema
version (`0007_chat_time_learning_ack`), row counts for every user-data table,
and MD5 digests over the `twins` and `conversations` rows. Production was not
touched. The drill branch can be deleted.

**Migration rollback, 2026-11-16:** migration 0008 was applied, rolled back and
re-applied on the `staging` branch, and CI now repeats that round trip on
every push.

## Migration policy

- Migrations are forward-only and additive where possible. An applied
  migration is never edited; a fix is a new migration.
- Each migration sets `lock_timeout` so a deploy fails fast instead of queueing
  behind a long transaction.
- Every migration must have a working `downgrade()`; CI checks
  `upgrade head → downgrade -1 → upgrade head` against PostgreSQL with
  pgvector.
- A migration that drops or rewrites data needs a snapshot first and an
  explicit owner sign-off.
