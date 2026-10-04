-- Goals RLS smoke test.
--
-- Verifies the Sprint 4 RLS gap closed by `security/goals-rls` is actually
-- enforced in Postgres. Runs as a plain psql script against a database
-- that has the current schema and `policies.sql` applied.
--
-- Usage:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
--        -f infra/supabase/tests/goals_rls_smoke.sql
--
-- The script works on either stock Postgres or a Supabase project. On
-- stock Postgres `auth.uid()` is not defined, so the preamble below
-- creates a stub `auth` schema and function that reads the current user
-- id from a session GUC (`request.jwt.claims.sub`). The real Supabase
-- `auth.uid()` reads the same claim from the Supabase-issued JWT, so the
-- policy expressions are identical in production.
--
-- The script asserts six invariants:
--   1. Owner A can SELECT their goals + goal_events.
--   2. Owner B cannot SELECT A's goals + goal_events.
--   3. INSERT by B into A's twin is blocked by RLS.
--   4. UPDATE by B of A's goal is blocked by RLS (rowcount = 0).
--   5. DELETE by B of A's goal is blocked by RLS (rowcount = 0).
--   6. Owner A keeps full access across SELECT/INSERT/UPDATE/DELETE on
--      their own rows.
--
-- The script tears down everything it created (BEGIN / ROLLBACK) and
-- restores the database to its pre-test state on success or failure.

\echo '--- goals_rls_smoke.sql: setup'

BEGIN;

-- Stub `auth.uid()` so this smoke test runs on stock Postgres too.
-- In production this is the Supabase-provided function and is NOT
-- redefined. `CREATE SCHEMA IF NOT EXISTS` + `CREATE OR REPLACE
-- FUNCTION` is safe to run against Supabase since the function body
-- just reads a session GUC that Supabase sets per JWT.
CREATE SCHEMA IF NOT EXISTS auth;

CREATE OR REPLACE FUNCTION auth.uid()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(
        current_setting('request.jwt.claims.sub', true),
        ''
    )::uuid;
$$;

-- Fixed owner ids so expected rowcounts are deterministic.
\set user_a '''11111111-1111-1111-1111-111111111111'''
\set user_b '''22222222-2222-2222-2222-222222222222'''

-- Seed two twins + one goal + one goal_event per twin, as a SUPERUSER
-- role so RLS does not apply during setup (RLS is bypassed for role
-- owners / BYPASSRLS by default; the smoke relies on that behavior
-- which matches how a service-role seed script works in Supabase).
SET LOCAL ROLE NONE;

INSERT INTO twins (id, user_id, display_name)
VALUES
    ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', :user_a, 'Aurora'),
    ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', :user_b, 'Boreal');

INSERT INTO twin_profiles (id, twin_id)
VALUES
    ('a0a0a0a0-a0a0-a0a0-a0a0-a0a0a0a0a0a0',
        'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'),
    ('b0b0b0b0-b0b0-b0b0-b0b0-b0b0b0b0b0b0',
        'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb');

INSERT INTO goals (id, user_id, twin_id, title)
VALUES
    ('a1111111-1111-1111-1111-111111111111',
        :user_a,
        'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        'A''s private goal'),
    ('b1111111-1111-1111-1111-111111111111',
        :user_b,
        'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
        'B''s private goal');

INSERT INTO goal_events (id, goal_id, event_type, to_status)
VALUES
    ('a2222222-2222-2222-2222-222222222222',
        'a1111111-1111-1111-1111-111111111111',
        'created',
        'active'),
    ('b2222222-2222-2222-2222-222222222222',
        'b1111111-1111-1111-1111-111111111111',
        'created',
        'active');

\echo '--- goals_rls_smoke.sql: switching to a non-bypass role to exercise RLS'

-- RLS is bypassed for the table owner / BYPASSRLS roles. Create (or
-- reuse) a role that does NOT bypass, then SET LOCAL ROLE to it. Any
-- further query in this transaction runs under that role.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rls_smoke_user') THEN
        CREATE ROLE rls_smoke_user NOLOGIN;
    END IF;
END$$;
GRANT USAGE ON SCHEMA public TO rls_smoke_user;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON twins, twin_profiles, goals, goal_events
    TO rls_smoke_user;

SET LOCAL ROLE rls_smoke_user;

-- ----------------------------------------------------------------
-- (1) Owner A can see their own goals + goal_events.
-- ----------------------------------------------------------------
SET LOCAL "request.jwt.claims.sub" TO '11111111-1111-1111-1111-111111111111';

DO $$
DECLARE
    goal_count    integer;
    event_count   integer;
BEGIN
    SELECT COUNT(*) INTO goal_count FROM goals;
    IF goal_count <> 1 THEN
        RAISE EXCEPTION 'invariant 1 (goals): expected 1, got %', goal_count;
    END IF;

    SELECT COUNT(*) INTO event_count FROM goal_events;
    IF event_count <> 1 THEN
        RAISE EXCEPTION 'invariant 1 (goal_events): expected 1, got %', event_count;
    END IF;
END$$;

\echo '    (1) OK — owner A sees exactly their own goal + event'

-- ----------------------------------------------------------------
-- (2) Owner B cannot see owner A's rows, and vice-versa.
-- ----------------------------------------------------------------
SET LOCAL "request.jwt.claims.sub" TO '22222222-2222-2222-2222-222222222222';

DO $$
DECLARE
    goal_count   integer;
    event_count  integer;
    cross_see    integer;
BEGIN
    SELECT COUNT(*) INTO goal_count FROM goals;
    IF goal_count <> 1 THEN
        RAISE EXCEPTION 'invariant 2 (goals): expected 1 own goal visible, got %',
            goal_count;
    END IF;

    SELECT COUNT(*) INTO event_count FROM goal_events;
    IF event_count <> 1 THEN
        RAISE EXCEPTION 'invariant 2 (goal_events): expected 1 own event visible, got %',
            event_count;
    END IF;

    SELECT COUNT(*)
      INTO cross_see
      FROM goals
     WHERE id = 'a1111111-1111-1111-1111-111111111111';
    IF cross_see <> 0 THEN
        RAISE EXCEPTION 'invariant 2 (cross-user goal visible): got %', cross_see;
    END IF;

    SELECT COUNT(*)
      INTO cross_see
      FROM goal_events
     WHERE id = 'a2222222-2222-2222-2222-222222222222';
    IF cross_see <> 0 THEN
        RAISE EXCEPTION 'invariant 2 (cross-user event visible): got %', cross_see;
    END IF;
END$$;

\echo '    (2) OK — owner B cannot see A''s rows'

-- ----------------------------------------------------------------
-- (3) INSERT by B into A's twin is blocked by RLS WITH CHECK.
--     The insert should raise insufficient_privilege, which the DO
--     block catches and converts into an assertion.
-- ----------------------------------------------------------------
DO $$
DECLARE
    err_code    text := NULL;
BEGIN
    BEGIN
        INSERT INTO goals (id, user_id, twin_id, title)
        VALUES (
            'c1111111-1111-1111-1111-111111111111',
            '11111111-1111-1111-1111-111111111111',
            'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            'B is trying to plant a row on A''s twin'
        );
    EXCEPTION WHEN insufficient_privilege THEN
        err_code := 'insufficient_privilege';
    WHEN check_violation THEN
        err_code := 'check_violation';
    END;
    IF err_code IS NULL THEN
        RAISE EXCEPTION 'invariant 3 (INSERT cross-twin): insert succeeded';
    END IF;
END$$;

\echo '    (3) OK — INSERT by B into A''s twin was rejected'

-- ----------------------------------------------------------------
-- (4) UPDATE by B of A's goal is a no-op (rowcount = 0).
-- ----------------------------------------------------------------
DO $$
DECLARE
    affected  integer;
BEGIN
    UPDATE goals
       SET title = 'B tried to rewrite this'
     WHERE id = 'a1111111-1111-1111-1111-111111111111';
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 0 THEN
        RAISE EXCEPTION 'invariant 4 (UPDATE cross-user): rowcount %', affected;
    END IF;
END$$;

\echo '    (4) OK — UPDATE by B of A''s goal affected 0 rows'

-- ----------------------------------------------------------------
-- (5) DELETE by B of A's goal is a no-op (rowcount = 0).
-- ----------------------------------------------------------------
DO $$
DECLARE
    affected  integer;
BEGIN
    DELETE FROM goals
     WHERE id = 'a1111111-1111-1111-1111-111111111111';
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 0 THEN
        RAISE EXCEPTION 'invariant 5 (DELETE cross-user): rowcount %', affected;
    END IF;
END$$;

\echo '    (5) OK — DELETE by B of A''s goal affected 0 rows'

-- ----------------------------------------------------------------
-- (6) Owner A keeps full write access to their own rows.
-- ----------------------------------------------------------------
SET LOCAL "request.jwt.claims.sub" TO '11111111-1111-1111-1111-111111111111';

DO $$
DECLARE
    affected   integer;
BEGIN
    INSERT INTO goals (id, user_id, twin_id, title)
    VALUES (
        'a3333333-3333-3333-3333-333333333333',
        '11111111-1111-1111-1111-111111111111',
        'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        'A''s second goal, inserted under RLS'
    );

    UPDATE goals
       SET title = 'A''s renamed goal'
     WHERE id = 'a3333333-3333-3333-3333-333333333333';
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 1 THEN
        RAISE EXCEPTION 'invariant 6 (self UPDATE): rowcount %', affected;
    END IF;

    DELETE FROM goals
     WHERE id = 'a3333333-3333-3333-3333-333333333333';
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 1 THEN
        RAISE EXCEPTION 'invariant 6 (self DELETE): rowcount %', affected;
    END IF;
END$$;

\echo '    (6) OK — owner A can INSERT/UPDATE/DELETE their own rows under RLS'

-- Reset session and roll back the entire fixture so the smoke test
-- leaves no trace.
RESET ROLE;
RESET "request.jwt.claims.sub";

ROLLBACK;

\echo '--- goals_rls_smoke.sql: PASS'
