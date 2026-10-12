-- Sprint 10 migration preflight (OPTIONAL, READ-ONLY).
--
-- Run this against the TARGET database immediately before applying
-- migration 0007_chat_time_learning_ack, e.g.:
--
--     psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f sprint10_migration_preflight.sql
--
-- It is advisory: it REPORTS whether any other client backend holds an
-- open transaction, or whether a prepared transaction exists on this
-- database. Either can contend with the migration's brief
-- ACCESS EXCLUSIVE lock on twin_evolution_events. This script does NOT
-- fence connections — fencing requires cluster-role privileges this
-- project does not hold on the managed (Supabase) target. See
-- docs/architecture/chat-time-learning-ack.md ("Deployment / rollout").
--
-- Interpreting the output:
--   * Both result sets EMPTY  → the migration should acquire its locks
--     immediately; its inner lock_timeout (15s) is the backstop either way.
--   * Rows present            → investigate the listed backends before
--     migrating (an app worker mid-request, a stuck "idle in transaction"
--     session, or a prepared transaction holding locks).
--
-- Uses `state`, not `backend_xmin`: a backend can sit "idle in
-- transaction" holding row/table locks with a NULL backend_xmin, so
-- state is the reliable signal. Scoped to client backends so autovacuum
-- and internal workers are ignored. PostgreSQL 12+ compatible.

\echo '== client backends with an open transaction (want: 0 rows) =='
SELECT pid,
       usename,
       application_name,
       state,
       xact_start,
       now() - xact_start AS open_for,
       pg_blocking_pids(pid) AS blocked_by
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
  AND datname = current_database()
  AND backend_type = 'client backend'
  AND state IN ('active',
                'idle in transaction',
                'idle in transaction (aborted)',
                'fastpath function call')
ORDER BY xact_start NULLS LAST;

\echo '== prepared transactions on this database (want: 0 rows) =='
SELECT gid, prepared, owner, transaction
FROM pg_prepared_xacts
WHERE database = current_database();
