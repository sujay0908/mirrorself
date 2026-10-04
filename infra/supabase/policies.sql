-- Row-level security policies.
-- Applied AFTER the tables exist. Every user-scoped table has RLS on.
--
-- The FastAPI service currently talks to Supabase Postgres with a
-- service-role connection (it enforces ownership in application code).
-- These policies are the second line of defence: if Supabase's
-- REST/Realtime layers are ever pointed at these tables directly, only the
-- owning user gets a row.

-- Twins.
ALTER TABLE twins ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS twins_owner_select ON twins;
CREATE POLICY twins_owner_select ON twins
    FOR SELECT USING (user_id = auth.uid());
DROP POLICY IF EXISTS twins_owner_write ON twins;
CREATE POLICY twins_owner_write ON twins
    FOR ALL USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- Twin profiles.
ALTER TABLE twin_profiles ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS twin_profiles_owner ON twin_profiles;
CREATE POLICY twin_profiles_owner ON twin_profiles
    FOR ALL
    USING (
        twin_id IN (SELECT id FROM twins WHERE user_id = auth.uid())
    )
    WITH CHECK (
        twin_id IN (SELECT id FROM twins WHERE user_id = auth.uid())
    );

-- Conversations.
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS conversations_owner ON conversations;
CREATE POLICY conversations_owner ON conversations
    FOR ALL
    USING (
        twin_id IN (SELECT id FROM twins WHERE user_id = auth.uid())
    )
    WITH CHECK (
        twin_id IN (SELECT id FROM twins WHERE user_id = auth.uid())
    );

-- Messages.
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS messages_owner ON messages;
CREATE POLICY messages_owner ON messages
    FOR ALL
    USING (
        conversation_id IN (
            SELECT c.id FROM conversations c
            JOIN twins t ON t.id = c.twin_id
            WHERE t.user_id = auth.uid()
        )
    )
    WITH CHECK (
        conversation_id IN (
            SELECT c.id FROM conversations c
            JOIN twins t ON t.id = c.twin_id
            WHERE t.user_id = auth.uid()
        )
    );

-- ================================================================
-- Sprint 2: memory system RLS
-- ================================================================

-- Memories — owned directly via twin_id.
ALTER TABLE memories ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS memories_owner ON memories;
CREATE POLICY memories_owner ON memories
    FOR ALL
    USING (twin_id IN (SELECT id FROM twins WHERE user_id = auth.uid()))
    WITH CHECK (twin_id IN (SELECT id FROM twins WHERE user_id = auth.uid()));

-- Memory sources — owned transitively via memory → twin.
ALTER TABLE memory_sources ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS memory_sources_owner ON memory_sources;
CREATE POLICY memory_sources_owner ON memory_sources
    FOR ALL
    USING (
        memory_id IN (
            SELECT m.id FROM memories m
            JOIN twins t ON t.id = m.twin_id
            WHERE t.user_id = auth.uid()
        )
    )
    WITH CHECK (
        memory_id IN (
            SELECT m.id FROM memories m
            JOIN twins t ON t.id = m.twin_id
            WHERE t.user_id = auth.uid()
        )
    );

-- Memory embeddings — owned transitively via memory → twin.
ALTER TABLE memory_embeddings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS memory_embeddings_owner ON memory_embeddings;
CREATE POLICY memory_embeddings_owner ON memory_embeddings
    FOR ALL
    USING (
        memory_id IN (
            SELECT m.id FROM memories m
            JOIN twins t ON t.id = m.twin_id
            WHERE t.user_id = auth.uid()
        )
    )
    WITH CHECK (
        memory_id IN (
            SELECT m.id FROM memories m
            JOIN twins t ON t.id = m.twin_id
            WHERE t.user_id = auth.uid()
        )
    );

-- Memory candidates — owned directly via twin_id.
ALTER TABLE memory_candidates ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS memory_candidates_owner ON memory_candidates;
CREATE POLICY memory_candidates_owner ON memory_candidates
    FOR ALL
    USING (twin_id IN (SELECT id FROM twins WHERE user_id = auth.uid()))
    WITH CHECK (twin_id IN (SELECT id FROM twins WHERE user_id = auth.uid()));

-- ================================================================
-- Sprint 4: goals RLS
-- ================================================================
--
-- The 0004_goals migration created these tables but the audit of the
-- Sprint 4 merge (PR #17 / 6f4ea2b) found no matching RLS policies here,
-- leaving the documented second line of defence open for goal data.
-- Policies below follow the existing convention: direct-twin_id tables
-- match the memories pattern, transitive tables match the memory_sources
-- pattern (join through the parent to the owning twin).

-- Goals — owned directly via twin_id (same pattern as memories).
ALTER TABLE goals ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS goals_owner ON goals;
CREATE POLICY goals_owner ON goals
    FOR ALL
    USING (twin_id IN (SELECT id FROM twins WHERE user_id = auth.uid()))
    WITH CHECK (twin_id IN (SELECT id FROM twins WHERE user_id = auth.uid()));

-- Goal events — owned transitively via goal → twin (same pattern as
-- memory_sources / memory_embeddings). The service layer guarantees goal
-- events are append-only; the policy here only enforces ownership, not
-- the append-only invariant.
ALTER TABLE goal_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS goal_events_owner ON goal_events;
CREATE POLICY goal_events_owner ON goal_events
    FOR ALL
    USING (
        goal_id IN (
            SELECT g.id FROM goals g
            JOIN twins t ON t.id = g.twin_id
            WHERE t.user_id = auth.uid()
        )
    )
    WITH CHECK (
        goal_id IN (
            SELECT g.id FROM goals g
            JOIN twins t ON t.id = g.twin_id
            WHERE t.user_id = auth.uid()
        )
    );
