-- Personal AI Twin — Sprint 1 schema.
-- This file is the human-readable mirror of alembic/versions/0001_initial.py.
-- Apply migrations via alembic; do NOT `psql -f schema.sql` in prod.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS twins (
    id                      UUID PRIMARY KEY,
    user_id                 UUID NOT NULL UNIQUE,
    display_name            VARCHAR(120) NOT NULL,
    -- Sprint 8: timestamp of the last SUCCESSFUL reflection run for
    -- this twin. Written by `ReflectionScheduler.maybe_run` inside the
    -- same transaction as `ReflectionService.create_candidates`. The
    -- opportunity policy's "new memories since last run" and cooldown
    -- clauses both read this column. NULL until the first successful
    -- run.
    last_reflection_run_at  TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_twins_user_id ON twins(user_id);

CREATE TABLE IF NOT EXISTS twin_profiles (
    id                            UUID PRIMARY KEY,
    twin_id                       UUID NOT NULL UNIQUE
                                    REFERENCES twins(id) ON DELETE CASCADE,
    communication_style_preset    VARCHAR(32) NOT NULL DEFAULT 'neutral',
    communication_style_notes     TEXT,
    basic_profile                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS conversations (
    id          UUID PRIMARY KEY,
    twin_id     UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    title       VARCHAR(200),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_conversations_twin_id ON conversations(twin_id);

CREATE TABLE IF NOT EXISTS messages (
    id                UUID PRIMARY KEY,
    conversation_id   UUID NOT NULL
                        REFERENCES conversations(id) ON DELETE CASCADE,
    role              VARCHAR(16) NOT NULL
                        CHECK (role IN ('user', 'twin', 'system')),
    content           TEXT NOT NULL,
    llm_provider      VARCHAR(64),
    llm_model         VARCHAR(128),
    input_tokens      INTEGER,
    output_tokens     INTEGER,
    metadata_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_messages_conversation_created
    ON messages(conversation_id, created_at);

-- ================================================================
-- Sprint 2: memory system
-- Source of truth: apps/api/alembic/versions/0002_memory_system.py
-- ================================================================

CREATE TABLE IF NOT EXISTS memories (
    id                  UUID PRIMARY KEY,
    user_id             UUID NOT NULL,
    twin_id             UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    type                VARCHAR(32) NOT NULL
                            CHECK (type IN ('FACT','PREFERENCE','EXPERIENCE','GOAL')),
    content             TEXT NOT NULL,
    source              VARCHAR(32) NOT NULL,
    confidence          DOUBLE PRECISION NOT NULL DEFAULT 1.0
                            CHECK (confidence >= 0 AND confidence <= 1),
    importance          DOUBLE PRECISION NOT NULL DEFAULT 0.5
                            CHECK (importance >= 0 AND importance <= 1),
    user_confirmed      BOOLEAN NOT NULL DEFAULT false,
    last_confirmed_at   TIMESTAMPTZ,
    metadata_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_memories_user_id ON memories(user_id);
CREATE INDEX IF NOT EXISTS ix_memories_twin_id ON memories(twin_id);
CREATE INDEX IF NOT EXISTS ix_memories_twin_created
    ON memories(twin_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_memories_twin_type ON memories(twin_id, type);

CREATE TABLE IF NOT EXISTS memory_sources (
    id                      UUID PRIMARY KEY,
    memory_id               UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    source_type             VARCHAR(32) NOT NULL
                                CHECK (source_type IN ('message','user_edit','import')),
    source_message_id       UUID REFERENCES messages(id) ON DELETE SET NULL,
    source_conversation_id  UUID REFERENCES conversations(id) ON DELETE SET NULL,
    source_metadata         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_memory_sources_memory_id ON memory_sources(memory_id);

CREATE TABLE IF NOT EXISTS memory_embeddings (
    id                    UUID PRIMARY KEY,
    memory_id             UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    embedding_model       VARCHAR(128) NOT NULL,
    embedding_dimensions  INTEGER NOT NULL CHECK (embedding_dimensions > 0),
    vector                JSON NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_memory_embedding_model UNIQUE (memory_id, embedding_model)
);
CREATE INDEX IF NOT EXISTS ix_memory_embeddings_memory_id
    ON memory_embeddings(memory_id);

CREATE TABLE IF NOT EXISTS memory_candidates (
    id                       UUID PRIMARY KEY,
    user_id                  UUID NOT NULL,
    twin_id                  UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    type                     VARCHAR(32) NOT NULL
                                 CHECK (type IN ('FACT','PREFERENCE','EXPERIENCE','GOAL')),
    content                  TEXT NOT NULL,
    confidence               DOUBLE PRECISION NOT NULL DEFAULT 0.5
                                 CHECK (confidence >= 0 AND confidence <= 1),
    importance               DOUBLE PRECISION NOT NULL DEFAULT 0.5
                                 CHECK (importance >= 0 AND importance <= 1),
    source_message_id        UUID REFERENCES messages(id) ON DELETE CASCADE,
    source_conversation_id   UUID REFERENCES conversations(id) ON DELETE CASCADE,
    rationale                TEXT,
    status                   VARCHAR(16) NOT NULL DEFAULT 'pending'
                                 CHECK (status IN ('pending','confirmed','rejected','expired')),
    resulting_memory_id      UUID REFERENCES memories(id) ON DELETE SET NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_memory_candidates_user_id
    ON memory_candidates(user_id);
CREATE INDEX IF NOT EXISTS ix_memory_candidates_twin_id
    ON memory_candidates(twin_id);
CREATE INDEX IF NOT EXISTS ix_memory_candidates_twin_status_created
    ON memory_candidates(twin_id, status, created_at DESC);

-- Sprint 4: goals + goal_events
-- Mirror of alembic/versions/0004_goals.py so this file stays a
-- human-readable view of every table policies.sql references. Apply
-- migrations via alembic in prod; schema.sql is not the source of truth.

CREATE TABLE IF NOT EXISTS goals (
    id                 UUID PRIMARY KEY,
    user_id            UUID NOT NULL,
    twin_id            UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    title              VARCHAR(200) NOT NULL,
    description        TEXT,
    target_date        TIMESTAMPTZ,
    priority           INTEGER NOT NULL DEFAULT 3
                           CHECK (priority >= 1 AND priority <= 5),
    status             VARCHAR(16) NOT NULL DEFAULT 'active'
                           CHECK (status IN ('active','achieved','abandoned','paused')),
    status_changed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata_json      JSON NOT NULL DEFAULT '{}'::json,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_goals_user_id ON goals(user_id);
CREATE INDEX IF NOT EXISTS ix_goals_twin_id ON goals(twin_id);
CREATE INDEX IF NOT EXISTS ix_goals_twin_status
    ON goals(twin_id, status);

CREATE TABLE IF NOT EXISTS goal_events (
    id           UUID PRIMARY KEY,
    goal_id      UUID NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    event_type   VARCHAR(32) NOT NULL
                     CHECK (event_type IN ('created','updated','status_changed')),
    from_status  VARCHAR(16),
    to_status    VARCHAR(16),
    note         TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_goal_events_goal_id ON goal_events(goal_id);

-- ================================================================
-- Sprint 7: reflection subsystem
-- Source of truth: apps/api/alembic/versions/0005_reflection.py
-- ================================================================
--
-- Reflection candidates are user-confirmable proposals produced by the
-- reflection extractor. The LLM proposes; the user confirms; only
-- confirmation can create durable changes. Four approved kinds —
-- `profile_update`, `memory_dedup`, `goal_update`, `insight`.
--
-- `memories.superseded_by_memory_id` is a nullable self-FK added by the
-- same migration. Confirmed `memory_dedup` reflections mark a row as
-- superseded (never deleted); retrieval filters by IS NULL while the
-- normal memory list still exposes superseded rows for the un-supersede
-- UX.

ALTER TABLE memories
    ADD COLUMN IF NOT EXISTS superseded_by_memory_id UUID
        REFERENCES memories(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_memories_superseded_by_memory_id
    ON memories(superseded_by_memory_id);

-- Sprint 8: immutable confirmation timestamp. Set once at
-- candidate_confirm; the reflection opportunity policy counts
-- "new confirmed memories since last run" against this column.
ALTER TABLE memories
    ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS ix_memories_confirmed_at
    ON memories(confirmed_at);

CREATE TABLE IF NOT EXISTS reflection_candidates (
    id                 UUID PRIMARY KEY,
    user_id            UUID NOT NULL,
    twin_id            UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    kind               VARCHAR(32) NOT NULL
                            CHECK (kind IN ('profile_update','memory_dedup',
                                            'goal_update','insight')),
    status             VARCHAR(16) NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','confirmed','rejected')),
    proposed_payload   JSON NOT NULL DEFAULT '{}'::json,
    source_memory_ids  JSON NOT NULL DEFAULT '[]'::json,
    source_goal_ids    JSON NOT NULL DEFAULT '[]'::json,
    rationale          TEXT,
    confidence         DOUBLE PRECISION NOT NULL DEFAULT 0.5
                            CHECK (confidence >= 0 AND confidence <= 1),
    importance         DOUBLE PRECISION NOT NULL DEFAULT 0.5
                            CHECK (importance >= 0 AND importance <= 1),
    fingerprint        VARCHAR(64),
    resolved_at        TIMESTAMPTZ,
    apply_error        VARCHAR(255),
    apply_metadata     JSON NOT NULL DEFAULT '{}'::json,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_reflection_candidates_user_id
    ON reflection_candidates(user_id);
CREATE INDEX IF NOT EXISTS ix_reflection_candidates_twin_id
    ON reflection_candidates(twin_id);
CREATE INDEX IF NOT EXISTS ix_reflection_candidates_twin_status_created
    ON reflection_candidates(twin_id, status, created_at);
CREATE INDEX IF NOT EXISTS ix_reflection_candidates_twin_fingerprint
    ON reflection_candidates(twin_id, status, fingerprint);

-- ================================================================
-- Sprint 8: Evolving Twin Loop — evolution events + intent telemetry
-- Source of truth: apps/api/alembic/versions/0006_evolving_twin_loop.py
-- ================================================================
--
-- `twin_evolution_events` records durable, user-authorized changes
-- that actually took effect. Only written AFTER the matching apply
-- succeeds. Rejected reflections do NOT create a row. The `summary`
-- column is a short, derived string composed from IDs + the kind of
-- change — it does NOT contain raw memory/goal/profile/message text.
-- See docs/architecture/evolving-twin-loop.md.

CREATE TABLE IF NOT EXISTS twin_evolution_events (
    id              UUID PRIMARY KEY,
    user_id         UUID NOT NULL,
    twin_id         UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    event_type      VARCHAR(32) NOT NULL
                        CHECK (event_type IN (
                            'memory_learned','memory_consolidated',
                            'goal_updated','profile_confirmed',
                            'insight_acknowledged'
                        )),
    reflection_id   UUID REFERENCES reflection_candidates(id)
                        ON DELETE SET NULL,
    memory_id       UUID REFERENCES memories(id) ON DELETE SET NULL,
    goal_id         UUID REFERENCES goals(id) ON DELETE SET NULL,
    profile_field   VARCHAR(64),
    summary         VARCHAR(255) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_twin_evolution_events_user_id
    ON twin_evolution_events(user_id);
CREATE INDEX IF NOT EXISTS ix_twin_evolution_events_twin_id
    ON twin_evolution_events(twin_id);
CREATE INDEX IF NOT EXISTS ix_twin_evolution_events_twin_created
    ON twin_evolution_events(twin_id, created_at);

-- `intent_telemetry_events` — SAFE-METADATA-ONLY row. There is no
-- content column, no message_id, no FK to any row that would let a
-- reader recover the user's words. The intent telemetry sentinel test
-- (`test_privacy_sentinel_never_appears_in_evolution_rows_or_logs`)
-- asserts this. See docs/architecture/evolving-twin-loop.md.

CREATE TABLE IF NOT EXISTS intent_telemetry_events (
    id                      UUID PRIMARY KEY,
    user_id                 UUID NOT NULL,
    twin_id                 UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    intent                  VARCHAR(32) NOT NULL,
    confidence              DOUBLE PRECISION NOT NULL
                                CHECK (confidence >= 0 AND confidence <= 1),
    reason                  VARCHAR(64) NOT NULL,
    detector_name           VARCHAR(64) NOT NULL,
    latency_ms              INTEGER NOT NULL DEFAULT 0,
    message_length_bucket   VARCHAR(16) NOT NULL
                                CHECK (message_length_bucket IN
                                       ('short','medium','long')),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_intent_telemetry_user_id
    ON intent_telemetry_events(user_id);
CREATE INDEX IF NOT EXISTS ix_intent_telemetry_twin_id
    ON intent_telemetry_events(twin_id);
CREATE INDEX IF NOT EXISTS ix_intent_telemetry_twin_created
    ON intent_telemetry_events(twin_id, created_at);
