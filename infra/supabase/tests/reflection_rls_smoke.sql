-- Reflection RLS smoke test (Sprint 7).
--
-- Verifies the row-level security policies for `reflection_candidates`
-- are actually enforced in Postgres. Runs as a plain psql script
-- against a database that has the current schema and `policies.sql`
-- applied.
--
-- Usage:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
--        -f infra/supabase/tests/reflection_rls_smoke.sql
--
-- The script asserts seven invariants:
--   1. Owner A sees exactly A's reflection candidates.
--   2. Owner B cannot see A's reflection candidates (and vice versa).
--   3. INSERT by B into A's twin is blocked by RLS WITH CHECK.
--   4. UPDATE by B of A's candidate is a no-op (rowcount = 0).
--   5. DELETE by B of A's candidate is a no-op (rowcount = 0).
--   6. Owner A keeps full write access to their own rows.
--   7. `memories.superseded_by_memory_id` honors the existing
--      memories_owner policy — B cannot see A's memory even when
--      marked superseded, and B cannot UPDATE A's memory to point its
--      supersession pointer at any other memory.
--
-- The script tears down everything (BEGIN / ROLLBACK) and restores the
-- database to its pre-test state on success or failure.

\echo '--- reflection_rls_smoke.sql: setup'

BEGIN;

-- Stub `auth.uid()` so this smoke test runs on stock Postgres too.
-- Same shape as goals_rls_smoke.sql.
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

\set user_a '''11111111-1111-1111-1111-111111111111'''
\set user_b '''22222222-2222-2222-2222-222222222222'''

-- Seed as superuser so RLS does not get in the way during setup.
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

-- A has one confirmed memory + one reflection candidate.
INSERT INTO memories (id, user_id, twin_id, type, content, source, user_confirmed)
VALUES (
    'aa111111-1111-1111-1111-111111111111',
    :user_a,
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    'FACT',
    'A''s private memory',
    'user_edit',
    true
);

INSERT INTO reflection_candidates
    (id, user_id, twin_id, kind, status, proposed_payload,
     source_memory_ids, source_goal_ids, rationale,
     confidence, importance, fingerprint, apply_metadata)
VALUES (
    'aa222222-2222-2222-2222-222222222222',
    :user_a,
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    'insight',
    'pending',
    '{"kind":"insight","headline":"private","body":"private","rationale":"private"}'::json,
    '["aa111111-1111-1111-1111-111111111111"]'::json,
    '[]'::json,
    'private rationale',
    0.5,
    0.5,
    'fp-a-insight',
    '{}'::json
);

-- B has one memory + one reflection candidate too.
INSERT INTO memories (id, user_id, twin_id, type, content, source, user_confirmed)
VALUES (
    'bb111111-1111-1111-1111-111111111111',
    :user_b,
    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
    'FACT',
    'B''s private memory',
    'user_edit',
    true
);

INSERT INTO reflection_candidates
    (id, user_id, twin_id, kind, status, proposed_payload,
     source_memory_ids, source_goal_ids, rationale,
     confidence, importance, fingerprint, apply_metadata)
VALUES (
    'bb222222-2222-2222-2222-222222222222',
    :user_b,
    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
    'insight',
    'pending',
    '{"kind":"insight","headline":"private","body":"private","rationale":"private"}'::json,
    '["bb111111-1111-1111-1111-111111111111"]'::json,
    '[]'::json,
    'private rationale',
    0.5,
    0.5,
    'fp-b-insight',
    '{}'::json
);

\echo '--- reflection_rls_smoke.sql: switching to a non-bypass role to exercise RLS'

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rls_smoke_user') THEN
        CREATE ROLE rls_smoke_user NOLOGIN;
    END IF;
END$$;
GRANT USAGE ON SCHEMA public TO rls_smoke_user;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON twins, twin_profiles, memories, reflection_candidates
    TO rls_smoke_user;

SET LOCAL ROLE rls_smoke_user;

-- ----------------------------------------------------------------
-- (1) Owner A sees exactly A's reflection candidates.
-- ----------------------------------------------------------------
SET LOCAL "request.jwt.claims.sub" TO '11111111-1111-1111-1111-111111111111';

DO $$
DECLARE
    cand_count   integer;
BEGIN
    SELECT COUNT(*) INTO cand_count FROM reflection_candidates;
    IF cand_count <> 1 THEN
        RAISE EXCEPTION 'invariant 1 (reflection_candidates): expected 1, got %',
            cand_count;
    END IF;
END$$;

\echo '    (1) OK — owner A sees exactly their own reflection candidate'

-- ----------------------------------------------------------------
-- (2) Owner B cannot see A's reflection candidates.
-- ----------------------------------------------------------------
SET LOCAL "request.jwt.claims.sub" TO '22222222-2222-2222-2222-222222222222';

DO $$
DECLARE
    cand_count   integer;
    cross_see    integer;
BEGIN
    SELECT COUNT(*) INTO cand_count FROM reflection_candidates;
    IF cand_count <> 1 THEN
        RAISE EXCEPTION 'invariant 2 (own count): expected 1 own, got %',
            cand_count;
    END IF;

    SELECT COUNT(*)
      INTO cross_see
      FROM reflection_candidates
     WHERE id = 'aa222222-2222-2222-2222-222222222222';
    IF cross_see <> 0 THEN
        RAISE EXCEPTION
            'invariant 2 (cross-user visible): got %', cross_see;
    END IF;
END$$;

\echo '    (2) OK — owner B cannot see A''s reflection candidates'

-- ----------------------------------------------------------------
-- (3) INSERT by B into A's twin is blocked by RLS WITH CHECK.
-- ----------------------------------------------------------------
DO $$
DECLARE
    err_code    text := NULL;
BEGIN
    BEGIN
        INSERT INTO reflection_candidates
            (id, user_id, twin_id, kind, status, proposed_payload,
             source_memory_ids, source_goal_ids, rationale,
             confidence, importance, fingerprint, apply_metadata)
        VALUES (
            'cc222222-2222-2222-2222-222222222222',
            '11111111-1111-1111-1111-111111111111',
            'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            'insight',
            'pending',
            '{"kind":"insight","headline":"x","body":"x","rationale":"x"}'::json,
            '[]'::json,
            '[]'::json,
            'B planted a candidate on A',
            0.5,
            0.5,
            'fp-c-insight',
            '{}'::json
        );
    EXCEPTION WHEN insufficient_privilege THEN
        err_code := 'insufficient_privilege';
    WHEN check_violation THEN
        err_code := 'check_violation';
    END;
    IF err_code IS NULL THEN
        RAISE EXCEPTION
            'invariant 3 (INSERT cross-twin): insert succeeded';
    END IF;
END$$;

\echo '    (3) OK — INSERT by B into A''s twin was rejected'

-- ----------------------------------------------------------------
-- (4) UPDATE by B of A's reflection is a no-op (rowcount = 0).
-- ----------------------------------------------------------------
DO $$
DECLARE
    affected  integer;
BEGIN
    UPDATE reflection_candidates
       SET status = 'confirmed'
     WHERE id = 'aa222222-2222-2222-2222-222222222222';
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 0 THEN
        RAISE EXCEPTION
            'invariant 4 (UPDATE cross-user): rowcount %', affected;
    END IF;
END$$;

\echo '    (4) OK — UPDATE by B of A''s reflection affected 0 rows'

-- ----------------------------------------------------------------
-- (5) DELETE by B of A's reflection is a no-op (rowcount = 0).
-- ----------------------------------------------------------------
DO $$
DECLARE
    affected  integer;
BEGIN
    DELETE FROM reflection_candidates
     WHERE id = 'aa222222-2222-2222-2222-222222222222';
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 0 THEN
        RAISE EXCEPTION
            'invariant 5 (DELETE cross-user): rowcount %', affected;
    END IF;
END$$;

\echo '    (5) OK — DELETE by B of A''s reflection affected 0 rows'

-- ----------------------------------------------------------------
-- (6) Owner A keeps full write access to their own rows.
-- ----------------------------------------------------------------
SET LOCAL "request.jwt.claims.sub" TO '11111111-1111-1111-1111-111111111111';

DO $$
DECLARE
    affected   integer;
BEGIN
    INSERT INTO reflection_candidates
        (id, user_id, twin_id, kind, status, proposed_payload,
         source_memory_ids, source_goal_ids, rationale,
         confidence, importance, fingerprint, apply_metadata)
    VALUES (
        'aa333333-3333-3333-3333-333333333333',
        '11111111-1111-1111-1111-111111111111',
        'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        'insight',
        'pending',
        '{"kind":"insight","headline":"y","body":"y","rationale":"y"}'::json,
        '[]'::json,
        '[]'::json,
        'A''s second reflection, inserted under RLS',
        0.5,
        0.5,
        'fp-a-insight-2',
        '{}'::json
    );

    UPDATE reflection_candidates
       SET status = 'rejected', resolved_at = now()
     WHERE id = 'aa333333-3333-3333-3333-333333333333';
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 1 THEN
        RAISE EXCEPTION 'invariant 6 (self UPDATE): rowcount %', affected;
    END IF;

    DELETE FROM reflection_candidates
     WHERE id = 'aa333333-3333-3333-3333-333333333333';
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 1 THEN
        RAISE EXCEPTION 'invariant 6 (self DELETE): rowcount %', affected;
    END IF;
END$$;

\echo '    (6) OK — owner A can INSERT/UPDATE/DELETE their own reflection rows under RLS'

-- ----------------------------------------------------------------
-- (7) The memories.superseded_by_memory_id column is governed by the
--     existing memories_owner policy. Verify cross-user visibility and
--     cross-user supersession are both blocked.
-- ----------------------------------------------------------------
SET LOCAL "request.jwt.claims.sub" TO '22222222-2222-2222-2222-222222222222';

DO $$
DECLARE
    seen      integer;
    affected  integer;
BEGIN
    -- (7a) B cannot see A's memory even by id.
    SELECT COUNT(*)
      INTO seen
      FROM memories
     WHERE id = 'aa111111-1111-1111-1111-111111111111';
    IF seen <> 0 THEN
        RAISE EXCEPTION
            'invariant 7a (cross-user memory visible): got %', seen;
    END IF;

    -- (7b) B cannot set the supersession pointer on A's memory.
    UPDATE memories
       SET superseded_by_memory_id = 'bb111111-1111-1111-1111-111111111111'
     WHERE id = 'aa111111-1111-1111-1111-111111111111';
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 0 THEN
        RAISE EXCEPTION
            'invariant 7b (cross-user supersede): rowcount %', affected;
    END IF;
END$$;

\echo '    (7) OK — memories.superseded_by_memory_id respects memories_owner RLS'

RESET ROLE;
RESET "request.jwt.claims.sub";

ROLLBACK;

\echo '--- reflection_rls_smoke.sql: PASS'
