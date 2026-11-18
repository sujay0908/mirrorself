# Production readiness report

Date: 2026-11-17. Branch `sprint-2-monorepo`. Deployed commit
`0e616c3692745b4b98a42f26c35660ac7b150bc7` (API on Render, web on Vercel).
`main` was not touched; no history was rewritten.

Companion documents in this folder: `security-audit.md`, `load-testing.md`,
`domains-dns.md`, `backup-recovery.md`, `environment.md`, `runbook.md`.

## Summary

The application is deployed, hardened and tested, and works today on
https://mirrorself-web.vercel.app and https://www.timeismetime.com. It is
**not yet ready for real users** because of three owner actions:

1. **Rotate the credentials leaked in the public repository's history**
   (security audit S1). Until then, anyone who finds them can sign in as any
   user. This is the one item that should happen before inviting anyone.
2. **Add an Anthropic API key** in Render. Without it the Twin cannot reply;
   everything else works.
3. **Add four DNS records at Hostinger** for the apex, `app` and `api`
   (domains-dns.md).

## Acceptance criteria

| Criterion | Status | Evidence | Outstanding |
|---|---|---|---|
| Production frontend works | **PASS** (public screens) | New bundle live on both hosts; config check passed at build; sign-in validation verified in the browser (previously a silent no-op); no console errors; no horizontal overflow at 375 px. | Signed-in screens not re-checked in a browser after this deploy (needs a sign-in). |
| Backend works | **PASS** | Production smoke: health, readiness, build info, hardening headers, 13/13 protected routes refuse bad tokens, 413 on oversized bodies, CORS for all four origins. | — |
| Database works | **PASS** | Migration 0008 applied in production; existing Twin unchanged (content digest identical before and after). | Daily snapshots not scheduled (owner). |
| Authentication works | **PASS with one gap** | Production fetches the live Supabase key and rejects forged, expired, unsigned and malformed tokens. ES256 acceptance tested with real key pairs in the suite. | Acceptance of a genuine Supabase token through the new PyJWT path needs one real sign-in. |
| Twin creation and retrieval | **PASS** (staging) | End-to-end against PostgreSQL: create, conflict on second, five simultaneous creates → exactly one, retrieve, edit, persistence. | — |
| Conversations | **PASS** (staging) | Create, list, retrieve, paging, ordering, automatic titles. | — |
| Messages persisted | **PASS** (staging) | One exchange stored per send, in order; retries replay; failed model calls store nothing; concurrent duplicates refused with 409. | — |
| AI generation with a configured provider | **BLOCKED: key** | Provider verified against the installed SDK's real signature and error classes (26 tests); previously it would have failed every call (`temperature` rejected by SDK 2.x). | Add `ANTHROPIC_API_KEY`, then send one message. |
| Memory system | **PASS** reads / **BLOCKED** extraction | List, detail, provenance, 404s; vectors no longer loaded for lists. Extraction needs a model key. | As above. |
| Goals | **PASS** (staging) | Create, list, transition, illegal transition refused, audit trail. | — |
| Reflections | **PASS** reads / **BLOCKED** run | Manual run needs a model key. | As above. |
| Evolution | **PASS** | Read path; ordering now total (sequence), fixed a long-standing flaky test. | — |
| Ownership isolation | **PASS** | Second user cannot read, list, post into or edit the first user's conversations or goals; foreign idempotency keys and cursors match nothing. | — |
| Custom domains | **PARTIAL** | `www.timeismetime.com` serves the app with a valid certificate. | Apex (parked, HTTPS broken), `app` and `api` need DNS records and two dashboard steps. |
| SSL | **PASS** except apex | `www`, `*.vercel.app`, `*.onrender.com` valid; HSTS on the API. | Apex fixed by DNS record 1. |
| CORS | **PASS** | Preflight allowed for the four web origins; unknown origins refused. `www` was rejected before this release. | — |
| Security tests | **PASS / 1 critical open** | See security-audit.md; `pip-audit` clean; S2 (Supabase RLS) fixed 2026-11-18. | S1 credential rotation (owner). |
| Regression tests | **PASS** | API 423 passed + 6 PostgreSQL tests against Neon; web 106 passed; CI green on the deployed commit (tests, production image build, migration round trip, audit). | — |
| Browser tests | **PARTIAL** | Chromium engine (Chrome/Edge): desktop and 375 px. | Firefox and Safari not tested. |
| Performance tests | **PASS** | Staged load test 10→250 users on the staging stack; production read-only measurements. | — |
| Load-test capacity documented | **PASS** | load-testing.md: limits, failure mode, estimates labelled as estimates. | — |
| Monitoring | **PARTIAL** | Structured JSON logs with request ids on every line and response, `/v1/ready`, commit in `/v1/system/version`. | No alerting configured (needs an uptime service or paid plan). |
| Backups and recovery | **PASS** documented, drill done | Snapshot before deploy; restore drill matched production exactly. | Only 6 h point-in-time history on the current plan; enable daily snapshots. |
| CI/CD | **PASS** | Render now deploys only after GitHub checks pass and only on API changes; CI builds the production image and round-trips migrations. | Branch protection off (recommended on `main`). |
| Rollback procedure | **PASS** | runbook.md; migrations additive with tested downgrades. | — |

## Defects fixed in this release

**Would have broken production**
- The Anthropic provider sent `temperature`, which the installed SDK (2.x)
  rejects: every chat would have failed the moment a key was added.
- `LLM_MODEL` named a model that retires on 2026-11-30.
- CORS rejected `www.timeismetime.com`, which already serves the app.
- On the web build every alert, validation message and confirmation was a
  silent no-op (`Alert.alert` is a stub in React Native Web).

**Data loss or duplication**
- The chat screen cleared the draft before the send succeeded; any failure
  lost the message. No retry path; retries could double a turn.
- Unbounded transcript loading on every chat turn; memory lists loaded both
  stored copies of every embedding vector.

**Reliability**
- No pool health check: the first request after the database suspended got
  a dead connection.
- Chat requests held a database connection idle-in-transaction during the
  background model call.
- Ordering ties (two rows in one clock tick) — the cause of two tests that
  failed intermittently for weeks.
- No rate limiting, request size limit, request ids, readiness check, or
  security headers.

## What needs the owner

| Action | Where | Why |
|---|---|---|
| Rotate leaked Supabase keys and DB password, Upstash password | Supabase, Upstash dashboards | Critical; security-audit.md S1 |
| Add `ANTHROPIC_API_KEY` | Render → Environment | Turns on chat, memory extraction, reflections |
| Add 4 DNS records; add `api.timeismetime.com` in Render; set Supabase URLs | Hostinger, Render, Supabase | domains-dns.md |
| Daily Neon snapshots | Neon console | 6 h history is the only automatic backup today |
| An uptime check on `/v1/health` | UptimeRobot or similar | No alerting exists |
| Decide: paid Render instance, and Ohio region | Render | Removes 43 s cold starts and ~350 ms per read |
| Delete the `restore-drill-2026-11-17` Neon branch | Neon console | Left from the restore test |

## Not done, and why

- **Authenticated browser walk-through after this deploy**: requires a
  magic-link sign-in by the owner.
- **Real model call**: no API key exists yet.
- **Releasing the database connection during model calls**: the next
  scalability step (load-testing.md), deliberately not mixed into this
  release because it changes the duplicate-send handling.
- **Separate public website on `www`**: no site exists yet; `www` serves the
  app until one does.
