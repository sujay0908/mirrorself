# Security audit

Audit date: 2026-11-16/17. Scope: the `sprint-2-monorepo` branch, the deployed
API (Render), the web app (Vercel), the database (Neon), the identity
provider (Supabase) and the public GitHub repository `sujay0908/mirrorself`.

Status key: **Fixed** (code changed and tested), **Open: needs owner**
(requires an account action only the owner can take), **Accepted** (known,
deliberately left, with the reason).

## Critical

### S1. Live credentials in the public repository's history — Open: needs owner

The repository is public. Commits on `main` (`ff3c836`, `5a92f2d`, `33068b1`)
and `new-code-branch` (`005eca5`) contain, in setup scripts and docs:

| Credential | What it grants |
|---|---|
| Supabase `service_role` JWT for project `ihygwqrqkvkwlpzjrhdg` (HS256, expires 2036) | Full Supabase admin: bypasses RLS on the Supabase database, and the Auth admin API can list users, create users and **generate sign-in links for any user**. Because the MirrorSelf API trusts Supabase-issued tokens, that is a path to signing in as any MirrorSelf user. |
| Supabase Postgres password (`db.ihygwqrqkvkwlpzjrhdg.supabase.co`) | Direct superuser-level access to the Supabase database. |
| Upstash Redis URL with password (`immortal-hagfish-107731.upstash.io`) | Read/write to that Redis instance. |

The `sk-ant-…` values found are placeholders (`sk-ant-test…`), not real keys.

The values were classified without being used or printed. Removing them from
history requires a force-push rewrite, which is out of bounds for this work;
**rotation is the fix**, after which the leaked values are worthless:

1. Supabase → Project Settings → **API Keys** → disable the **legacy** `anon`
   and `service_role` keys (the web app already uses the new publishable key,
   `sb_publishable_…`, so this does not affect it). If the project still has
   the legacy JWT secret active under **JWT Keys**, revoke it.
2. Supabase → Project Settings → **Database** → reset the database password.
3. Upstash console → the `immortal-hagfish-107731` database → reset the
   password, or delete the database if nothing uses it.
4. Afterwards, confirm sign-in on https://mirrorself-web.vercel.app still works.

## High

### S2. Legacy Supabase tables writable with the public key — Open: needs owner

`public.users`, `public.conversations`, `public.messages`, `public.facts` in
the Supabase project have RLS disabled. They are empty and unused (MirrorSelf
data lives in Neon), but anyone holding the publishable key, which is
public by design, can read and write them through the Supabase REST API.
Remediation, either:

```sql
-- Block all client access, keep the tables:
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.facts ENABLE ROW LEVEL SECURITY;
```

or drop them if nothing depends on them. Not applied automatically: it changes
the owner's Supabase database.

### S3. `python-jose` token verification library — Fixed

`python-jose` 3.5.0 has an unfixed advisory (CVE-2026-85394: public keys
accepted as HMAC secrets) and pulls in `python-ecdsa`, which has an unfixed
timing side channel. Token verification moved to PyJWT. The specific attack
was not reachable before (algorithms were pinned), but there is no upstream
fix, so the dependency was removed. `pip-audit` over the pinned set now
reports no known vulnerabilities.

### S4. No rate limiting — Fixed

There was no limit on any endpoint, including the one that calls a paid model.
Now: per-IP limit before authentication (300/min), per-user limit on every
authenticated route (120/min), chat sends (20/min), manual reflection runs
(6/min). Responses are `429 rate_limited` with `Retry-After`. Limits are
per process; see the runbook before running more than one instance.

## Medium

| ID | Finding | Status |
|---|---|---|
| S5 | Tokens without `exp` were accepted; JWKS keys were cached forever (a rotated key needed a restart); the JWKS fetch blocked the event loop; an unreachable identity provider returned 500. | **Fixed**: `exp` and `sub` required, 10 s leeway, keys cached 1 h with refresh on unknown `kid` (rate-limited), fetched off the event loop, stale keys used during an outage, 503 `auth_unavailable` when none are held. |
| S6 | JWKS entries could select any algorithm. | **Fixed**: only ES256/RS256 are honoured from the JWKS. |
| S7 | 401 responses said *why* a token failed (expired, bad signature, audience). | **Fixed**: one generic message; the reason is logged. |
| S8 | Validation errors echoed the rejected input (a whole chat message) back in the response. | **Fixed**: location and reason only. |
| S9 | Provider errors forwarded the vendor's error text to the client. | **Fixed**: logged by type and request id; the client gets a stable code. |
| S10 | SQL errors could include bound parameters (chat text) in exception text and logs. | **Fixed**: `hide_parameters=True` on the engine. |
| S11 | No request body limit. | **Fixed**: 64 KiB, rejected before parsing (413). |
| S12 | CORS allowed credentials and every method and header. | **Fixed**: no credentials (auth is a bearer header), explicit methods and headers. |
| S13 | No security headers on API responses. | **Fixed**: `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, a deny-all CSP on JSON responses, HSTS in production. |
| S14 | Unbounded `basic_profile` (rendered into every prompt). | **Fixed**: ≤ 50 entries, ≤ 8 KiB. |
| S15 | Supabase "leaked password protection" is off. | **Accepted**: the app signs in by magic link only; no passwords are set. Turn it on if password sign-in is ever added. |

## Low / informational

- **API docs are public** (`/v1/docs`, `/v1/openapi.json`). They contain no
  secrets and describe a surface that requires a valid token. Set
  `API_DOCS_ENABLED=false` to hide them.
- **Supabase project region is Seoul (ap-northeast-2)**; the API is in Oregon
  and the database in Ohio. Not a security issue; noted in the performance
  report.
- **Branch protection is off** on `main` and `sprint-2-monorepo`. Recommended:
  require the `api` and `mobile` checks on `main` and block force-pushes.

## Ownership isolation (verified)

Every protected resource is addressed through the caller's own Twin, and a
foreign id is a 404 (not a 403, so existence is not revealed). Verified end to
end against PostgreSQL with two independent users (`scripts/e2e_smoke.py`,
full mode), and by the unit suite:

- User B cannot read, list, or post into A's conversations, read A's
  transcript, read or edit A's goals or their history, or see A's Twin.
- An idempotency key from another user cannot replay A's exchange.
- A pagination cursor from another conversation matches nothing.
- All 13 protected routes refuse missing, malformed, unsigned (`alg=none`),
  expired and wrongly-signed tokens.

## Not tested here

- CSRF: not applicable; no cookie-based authentication.
- File upload: there is no upload endpoint.
- SSRF: the only outbound requests go to fixed, configured hosts (Supabase
  JWKS, the model provider).
- A penetration test by a third party has not been done.
