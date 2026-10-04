# Supabase config

Sprint 1 uses Supabase for two things:

1. **Auth** — email OTP; JWTs are issued by Supabase and verified by the
   FastAPI service against the project's JWKS URL.
2. **Postgres** — the application database. Schema managed by Alembic
   (`apps/api/alembic/versions/`). `schema.sql` in this folder is a
   human-readable mirror, NOT the source of truth.

## Provisioning (staging)

1. Create a new Supabase project.
2. Copy `SUPABASE_JWT_JWKS_URL`, `SUPABASE_URL`, and the anon key into your
   secret store; set them in the API's environment and in
   `EXPO_PUBLIC_SUPABASE_URL` / `EXPO_PUBLIC_SUPABASE_ANON_KEY` for the
   mobile app.
3. Run migrations against the Supabase-managed Postgres:
   ```
   cd apps/api
   DATABASE_URL='postgresql+asyncpg://...' alembic upgrade head
   ```
4. Apply RLS policies:
   ```
   psql <SUPABASE_DB_URL> -f infra/supabase/policies.sql
   ```
5. Turn on email auth provider; disable magic-link redirect to any
   non-approved domain.

## Local dev

The `docker-compose.dev.yml` file spins up a plain Postgres 15 without
Supabase. Auth is stubbed by the `SUPABASE_JWT_HS_SECRET` env var so tests
and manual dev do not need a live Supabase instance.

## RLS smoke tests

`tests/goals_rls_smoke.sql` verifies that the Sprint 4 goal policies
actually block cross-user access. Run it after applying `policies.sql`
against a Postgres instance (either a Supabase project or a local
Postgres whose `auth.uid()` has been stubbed — the smoke file does the
stubbing automatically if the schema is missing):

```
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
     -f infra/supabase/tests/goals_rls_smoke.sql
```

The script runs inside a single transaction and rolls everything back on
success or failure, so it leaves no fixture rows behind.
