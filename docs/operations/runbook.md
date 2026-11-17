# Operations runbook

## Services

| Piece | Where | Link |
|---|---|---|
| API | Render `mirrorself-api` (free plan, Oregon, 1 instance) | https://mirrorself-api.onrender.com |
| Web app | Vercel `mirrorself-web` | https://mirrorself-web.vercel.app, https://www.timeismetime.com |
| Database | Neon `mirrorself.` (us-east-2), branch `production` | Neon console |
| Sign-in | Supabase `MirrorSelf` (`ihygwqrqkvkwlpzjrhdg`) | Supabase dashboard |
| Code / CI | GitHub `sujay0908/mirrorself`, branch `sprint-2-monorepo` | Actions tab |

## Health checks

```bash
curl -sS https://mirrorself-api.onrender.com/v1/health          # liveness: {"status":"ok"}
curl -sS https://mirrorself-api.onrender.com/v1/ready           # database + model configuration
curl -sS https://mirrorself-api.onrender.com/v1/system/version  # deployed commit, model
python apps/api/scripts/e2e_smoke.py --base-url https://mirrorself-api.onrender.com \
    --origin https://mirrorself-web.vercel.app --origin https://www.timeismetime.com
```

`/v1/health` is what Render probes. It never touches the database, so a
database blip does not restart a healthy process. `/v1/ready` returns 503
with `checks.database = "unavailable"` when the database cannot answer
within 5 s; right after a Neon compute wakes from idle that can happen once.

The first request after ~15 idle minutes takes up to ~45 s (free instance
waking). That is expected on the free plan.

## Logs

Render → `mirrorself-api` → Logs. One JSON line per request:

```json
{"event":"http.request","method":"POST","path":"/v1/conversations/…/messages",
 "status":201,"duration_ms":2310,"request_id":"6f3c…"}
```

Every error response carries the same `request_id` in its body and in the
`X-Request-ID` header. When someone reports a problem, ask for that id and
search the logs for it.

Logs never contain message text, memory content, tokens or keys. Useful
events: `api.unhandled` (a bug), `db.error` / `db.pool_exhausted` (database
trouble or saturation), `llm.request_failed` (model provider errors, with the
provider's request id), `llm.refused`, `auth.jwks_unavailable`,
`api.config.llm_degraded` (started without a model key).

## Alerts to set up (owner)

Render's free plan has no alerting of its own. Minimum viable monitoring:

1. **Uptime check** on `/v1/health` every 5 minutes (UptimeRobot, Better Stack
   or similar, free tiers). Note that pinging also keeps the free instance
   awake; decide whether that is wanted.
2. **Render notifications:** Account → Notifications → email on deploy
   failure (`notifyOnFail` is `default`).
3. **Error rate:** once on a paid plan, a log drain to a log service with an
   alert on `api.unhandled` or on 5xx share > 2% over 5 minutes.

## Deploy

Pushing to `sprint-2-monorepo` runs CI (`api`, `mobile`). Render deploys the
API after the commit's checks pass (`autoDeployTrigger: checksPass`).

Checklist for a release:

1. CI green on the commit.
2. If the release contains a migration: take a Neon snapshot of `production`.
3. Watch the Render deploy: build → `alembic upgrade head` → `Application
   startup complete` → live.
4. `GET /v1/system/version` shows the new `commit`.
5. Run the public smoke test (above).
6. Then deploy the web app: Vercel builds every push as a preview; promote
   to production with a redeploy of the latest production deployment using
   the latest commit (dashboard: Deployments → … → Redeploy to Production).
7. Open the site, sign in, open a conversation.

Order: API first, web second. The web app tolerates the previous API; the
reverse is not guaranteed.

## Rollback

- **API code:** Render → Deploys → pick the previous live deploy → Rollback.
  Migrations are additive, so the previous code runs against the newer
  schema. (0008 adds a nullable column and two indexes that older code
  ignores.)
- **Undo a migration** (rare; only if it is itself the problem): run
  `python -m alembic downgrade -1` from a shell with the production
  `DATABASE_URL`, then roll back the code. Snapshot first.
- **Data:** see `backup-recovery.md` (6-hour point-in-time restore, snapshots).
- **Web app:** Vercel → Deployments → previous production deployment →
  Promote (instant).

## Common incidents

| Symptom | Likely cause | Action |
|---|---|---|
| Every chat send returns `503 llm_provider_not_configured` | `ANTHROPIC_API_KEY` unset | Set it in Render → Environment. Saving redeploys. |
| Chat returns `503 llm_provider_misconfigured` | Key revoked, or `LLM_MODEL` not available to the account | Check `llm.request_failed` logs (status 401/403/404). |
| Chat returns `429 llm_rate_limited` | Provider rate limit | Wait; if persistent, raise the organization's rate-limit tier. |
| Many `503 server_busy` | Connection pool saturated | Check traffic; raise `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` or add capacity. See the load-test report. |
| `503 database_unavailable` | Neon down, suspended and failing to wake, or credentials changed | Neon console status; verify `DATABASE_URL`. |
| All requests 401 after a Supabase change | Signing key rotated / JWKS URL changed | The API refreshes keys automatically within 30 s of seeing a new key id; if not, check `SUPABASE_JWT_JWKS_URL`. |
| Browser says it cannot reach the API, server logs show nothing | CORS: the page's origin is not in `CORS_ALLOW_ORIGINS` | Add the origin, redeploy. |
| One user hits `429 rate_limited` | Per-user limit | Expected protection; adjust `RATE_LIMIT_*` only with a reason. |

## Secrets rotation

| Secret | Where to rotate | Then |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude Console → API keys | Update in Render; old key revoked after deploy is live. |
| Neon password | Neon console → Roles → reset | Update `DATABASE_URL` in Render. |
| Supabase keys | Supabase → API Keys | Publishable key: update Vercel and redeploy the web app. |

See `security-audit.md` S1 for the rotation that is outstanding now.
