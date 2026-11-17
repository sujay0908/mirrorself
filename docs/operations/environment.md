# Production environment variables

Secrets are set in each platform's dashboard and never committed. `render.yaml`
marks them `sync: false`. Values shown here are non-secret defaults or
examples.

## API — Render service `mirrorself-api`

### Required

| Variable | Value | Notes |
|---|---|---|
| `APP_ENV` | `prod` | Turns on the production configuration checks, HSTS, and rate limiting. |
| `DATABASE_URL` | Neon connection string (secret) | Direct host, not `-pooler`. Pasted verbatim; `postgres://…?sslmode=require` is normalised. Start-up refuses to run without a PostgreSQL URL. |
| `SUPABASE_JWT_JWKS_URL` | `https://ihygwqrqkvkwlpzjrhdg.supabase.co/auth/v1/.well-known/jwks.json` | Token verification keys. |
| `SUPABASE_JWT_AUDIENCE` | `authenticated` | |
| `CORS_ALLOW_ORIGINS` | `https://mirrorself-web.vercel.app,https://app.timeismetime.com,https://www.timeismetime.com,https://timeismetime.com` | Every origin the web app is served from. |
| `LLM_PROVIDER` | `anthropic` | `mock`/`local` are refused in production. |
| `LLM_MODEL` | `claude-sonnet-5-5` | Current Sonnet. `claude-haiku-5-5` costs less; `claude-opus-5-5` is the most capable. |

### AI (optional until chat is switched on)

| Variable | Value | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | secret | Without it the API runs; chat sends return `503 llm_provider_not_configured` and everything else works. |
| `LLM_EFFORT` | `low` | Reasoning depth. `low` keeps conversational replies fast and inexpensive. Unset = model default. |
| `LLM_TIMEOUT_SECONDS` | `45` | Per attempt. |
| `LLM_MAX_RETRIES` | `1` | The SDK retries timeouts, 429 and 5xx with backoff. Worst case ≈ timeout × (retries + 1). |
| `LLM_MAX_TOKENS` | `16000` | Output ceiling including thinking. |
| `LLM_REFUSAL_FALLBACK` | `auto` | On models that support it, a safety-classifier decline is retried server-side on a fallback model. `off` disables. |
| `EMBEDDING_PROVIDER` | `mock` | `openai` (with `OPENAI_API_KEY`) enables semantic memory retrieval. With `mock`, memories are stored and listed but retrieval is not semantic. |
| `OPENAI_API_KEY` | secret | Only for `EMBEDDING_PROVIDER=openai`. |

### Tuning (defaults are the tested values)

| Variable | Default | Notes |
|---|---|---|
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `20` / `30` | Per process. See the load-test report. |
| `DB_POOL_TIMEOUT_SECONDS` | `10` | Wait for a free connection before `503 server_busy`. |
| `DB_POOL_RECYCLE_SECONDS` | `240` | Below Neon's idle suspend. |
| `DB_CONNECT_TIMEOUT_SECONDS` / `DB_COMMAND_TIMEOUT_SECONDS` | `15` / `30` | |
| `RATE_LIMIT_ENABLED` | unset (= on outside tests) | |
| `RATE_LIMIT_IP_PER_MINUTE` | `300` | Before authentication. |
| `RATE_LIMIT_DEFAULT_PER_MINUTE` | `120` | Per user, all authenticated routes. |
| `RATE_LIMIT_CHAT_PER_MINUTE` | `20` | Per user, chat sends. |
| `RATE_LIMIT_AI_PER_MINUTE` | `6` | Per user, manual reflection runs. |
| `MAX_REQUEST_BODY_BYTES` | `65536` | |
| `API_DOCS_ENABLED` | `true` | `false` hides `/v1/docs` and the OpenAPI schema. |
| `SUPABASE_JWT_ISSUER` | unset | Set to `https://ihygwqrqkvkwlpzjrhdg.supabase.co/auth/v1` to also require the issuer claim. |
| `LOG_LEVEL` | `INFO` | |

Set automatically by Render: `PORT`, `RENDER_GIT_COMMIT` (reported by
`/v1/system/version`).

Never set in production: `SUPABASE_JWT_HS_SECRET` (dev-only; ignored outside
`APP_ENV=dev`), `MOCK_LLM_LATENCY_MS`.

## Web app — Vercel project `mirrorself-web`

Inlined into the JavaScript bundle at build time, so **all are public**. Never
put a secret here.

| Variable | Value |
|---|---|
| `EXPO_PUBLIC_API_URL` | `https://mirrorself-api.onrender.com` (later `https://api.timeismetime.com`) |
| `EXPO_PUBLIC_SUPABASE_URL` | `https://ihygwqrqkvkwlpzjrhdg.supabase.co` |
| `EXPO_PUBLIC_SUPABASE_ANON_KEY` | the project's **publishable** key (`sb_publishable_…`) |
| `EXPO_PUBLIC_API_TIMEOUT_MS` | optional, default `15000` for reads (chat sends use 90 s) |

The build fails if any required value is missing or points at localhost
(`scripts/check-web-env.js`, `scripts/verify-web-bundle.js`).

## Supabase — Authentication → URL configuration

- Site URL: `https://app.timeismetime.com` once that domain is live
  (until then `https://mirrorself-web.vercel.app`).
- Redirect URLs: every origin the app is served from, with `/**`.
