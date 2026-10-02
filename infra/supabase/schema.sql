-- Personal AI Twin — Sprint 1 schema.
-- This file is the human-readable mirror of alembic/versions/0001_initial.py.
-- Apply migrations via alembic; do NOT `psql -f schema.sql` in prod.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS twins (
    id            UUID PRIMARY KEY,
    user_id       UUID NOT NULL UNIQUE,
    display_name  VARCHAR(120) NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
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
