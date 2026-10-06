-- Evolving Twin Loop RLS smoke test (Sprint 8).
--
-- Verifies that the row-level security policies for
-- `twin_evolution_events` and `intent_telemetry_events` are enforced
-- in Postgres. Runs as a plain psql script against a database that
-- has the current schema and `policies.sql` applied.
--
-- Usage:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
--        -f infra/supabase/tests/evolving_twin_loop_rls_smoke.sql
--
-- Invariants:
--   1. Owner A sees exactly A's evolution events.
--   2. Owner B cannot see A's evolution events.
--   3. B's INSERT into A's twin on twin_evolution_events is blocked.
--   4. B's UPDATE of A's evolution row is a no-op.
--   5. Owner A sees exactly A's telemetry rows.
--   6. B cannot see A's telemetry rows.
--   7. B's INSERT into A's twin on intent_telemetry_events is blocked.
--   8. Owner A keeps full access to their own rows under RLS.

\echo '--- evolving_twin_loop_rls_smoke.sql: setup'

BEGIN;

CREATE SCHEMA IF NOT EXISTS auth;

CREATE OR REPLACE FUNCTION auth.uid()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('request.jwt.claims.sub', true), '')::uuid;
$$;

\set user_a '''11111111-1111-1111-1111-111111111111'''
\set user_b '''22222222-2222-2222-2222-222222222222'''

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

INSERT INTO twin_evolution_events
    (id, user_id, twin_id, event_type, summary)
VALUES
    ('aa444444-4444-4444-4444-444444444444', :user_a,
        'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        'memory_learned', 'FACT memory learned via confirmed candidate'),
    ('bb444444-4444-4444-4444-444444444444', :user_b,
        'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
        'insight_acknowledged', 'insight acknowledged');

INSERT INTO intent_telemetry_events
    (id, user_id, twin_id, intent, confidence, reason,
     detector_name, latency_ms, message_length_bucket)
VALUES
    ('aa555555-5555-5555-5555-555555555555', :user_a,
        'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        'PLAN', 0.9, 'phrase:plan', 'rule-based-v1', 2, 'short'),
    ('bb555555-5555-5555-5555-555555555555', :user_b,
        'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
        'TALK', 0.7, 'phrase:talk', 'rule-based-v1', 1, 'short');

\echo '--- evolving_twin_loop_rls_smoke.sql: switching to non-bypass role'

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rls_smoke_user') THEN
        CREATE ROLE rls_smoke_user NOLOGIN;
    END IF;
END$$;
GRANT USAGE ON SCHEMA public TO rls_smoke_user;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON twins, twin_profiles, twin_evolution_events, intent_telemetry_events
    TO rls_smoke_user;

SET LOCAL ROLE rls_smoke_user;

-- (1)+(2) evolution visibility
SET LOCAL "request.jwt.claims.sub" TO '11111111-1111-1111-1111-111111111111';
DO $$
DECLARE n integer;
BEGIN
    SELECT COUNT(*) INTO n FROM twin_evolution_events;
    IF n <> 1 THEN RAISE EXCEPTION 'invariant 1: expected 1, got %', n; END IF;
END$$;
\echo '    (1) OK — owner A sees exactly A''s evolution events'

SET LOCAL "request.jwt.claims.sub" TO '22222222-2222-2222-2222-222222222222';
DO $$
DECLARE cross_see integer;
BEGIN
    SELECT COUNT(*) INTO cross_see FROM twin_evolution_events
     WHERE id = 'aa444444-4444-4444-4444-444444444444';
    IF cross_see <> 0 THEN
        RAISE EXCEPTION 'invariant 2 (cross-user visible): got %', cross_see;
    END IF;
END$$;
\echo '    (2) OK — owner B cannot see A''s evolution events'

-- (3) evolution insert cross-twin blocked
DO $$
DECLARE err text := NULL;
BEGIN
    BEGIN
        INSERT INTO twin_evolution_events (id, user_id, twin_id, event_type, summary)
        VALUES ('cc444444-4444-4444-4444-444444444444',
                '11111111-1111-1111-1111-111111111111',
                'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                'memory_learned', 'planted on A');
    EXCEPTION
        WHEN insufficient_privilege THEN err := 'insufficient_privilege';
        WHEN check_violation       THEN err := 'check_violation';
    END;
    IF err IS NULL THEN
        RAISE EXCEPTION 'invariant 3: cross-twin INSERT succeeded';
    END IF;
END$$;
\echo '    (3) OK — INSERT by B into A''s twin evolution was rejected'

-- (4) evolution update cross-user is 0-row no-op
DO $$
DECLARE affected integer;
BEGIN
    UPDATE twin_evolution_events SET summary = 'B tried'
     WHERE id = 'aa444444-4444-4444-4444-444444444444';
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 0 THEN
        RAISE EXCEPTION 'invariant 4: cross-user UPDATE rowcount %', affected;
    END IF;
END$$;
\echo '    (4) OK — UPDATE by B of A''s evolution row affected 0 rows'

-- (5)+(6) telemetry visibility
SET LOCAL "request.jwt.claims.sub" TO '11111111-1111-1111-1111-111111111111';
DO $$
DECLARE n integer;
BEGIN
    SELECT COUNT(*) INTO n FROM intent_telemetry_events;
    IF n <> 1 THEN RAISE EXCEPTION 'invariant 5: expected 1, got %', n; END IF;
END$$;
\echo '    (5) OK — owner A sees exactly A''s telemetry rows'

SET LOCAL "request.jwt.claims.sub" TO '22222222-2222-2222-2222-222222222222';
DO $$
DECLARE cross_see integer;
BEGIN
    SELECT COUNT(*) INTO cross_see FROM intent_telemetry_events
     WHERE id = 'aa555555-5555-5555-5555-555555555555';
    IF cross_see <> 0 THEN
        RAISE EXCEPTION 'invariant 6 (cross-user visible): got %', cross_see;
    END IF;
END$$;
\echo '    (6) OK — owner B cannot see A''s telemetry rows'

-- (7) telemetry insert cross-twin blocked
DO $$
DECLARE err text := NULL;
BEGIN
    BEGIN
        INSERT INTO intent_telemetry_events
            (id, user_id, twin_id, intent, confidence, reason,
             detector_name, latency_ms, message_length_bucket)
        VALUES ('cc555555-5555-5555-5555-555555555555',
                '11111111-1111-1111-1111-111111111111',
                'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                'PLAN', 0.5, 'phrase:plan', 'rule-based-v1', 1, 'short');
    EXCEPTION
        WHEN insufficient_privilege THEN err := 'insufficient_privilege';
        WHEN check_violation       THEN err := 'check_violation';
    END;
    IF err IS NULL THEN
        RAISE EXCEPTION 'invariant 7: cross-twin INSERT succeeded';
    END IF;
END$$;
\echo '    (7) OK — INSERT by B into A''s twin telemetry was rejected'

-- (8) owner A full access
SET LOCAL "request.jwt.claims.sub" TO '11111111-1111-1111-1111-111111111111';
DO $$
DECLARE affected integer;
BEGIN
    INSERT INTO twin_evolution_events (id, user_id, twin_id, event_type, summary)
    VALUES ('aa666666-6666-6666-6666-666666666666',
            '11111111-1111-1111-1111-111111111111',
            'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            'profile_confirmed',
            'profile.communication_style_notes updated via confirmed reflection');
    UPDATE twin_evolution_events SET summary = summary
     WHERE id = 'aa666666-6666-6666-6666-666666666666';
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 1 THEN
        RAISE EXCEPTION 'invariant 8 (self UPDATE): rowcount %', affected;
    END IF;
    DELETE FROM twin_evolution_events
     WHERE id = 'aa666666-6666-6666-6666-666666666666';
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 1 THEN
        RAISE EXCEPTION 'invariant 8 (self DELETE): rowcount %', affected;
    END IF;
END$$;
\echo '    (8) OK — owner A can INSERT/UPDATE/DELETE their own evolution rows'

RESET ROLE;
RESET "request.jwt.claims.sub";
ROLLBACK;

\echo '--- evolving_twin_loop_rls_smoke.sql: PASS'
