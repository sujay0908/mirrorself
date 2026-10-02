# API Conventions

> **The avatar is the interface; the evolving personal intelligence is the product.**

This document defines the HTTP contract for the FastAPI service. It is
enforced by lint rules, generated clients, and code review. Endpoints not
covered here are still governed by these rules.

---

## Base URL and versioning

- Base: `https://api.personal-ai-twin.<env>.<domain>`
- Version prefix: `/v1`
- Breaking changes cut a new version prefix; deprecated versions receive
  security fixes only for 90 days after the successor ships.
- The current version is exposed at `GET /v1/system/version` returning
  `{ "api": "v1", "commit": "<sha>", "build_time": "<iso>" }`.

---

## Authentication

- All endpoints except `/v1/system/*` require a `Authorization: Bearer <jwt>`
  header where the JWT is issued by Supabase Auth.
- FastAPI verifies signatures against the Supabase project's JWKS.
- The `sub` claim maps to `users.supabase_id`; the FastAPI service resolves
  `user_id` internally and never trusts a client-provided user id.
- Service-role tokens are for server-to-server internal endpoints only and
  must never be shipped to the mobile client.

---

## URL shape

- Kebab-case only in URL segments (`goal-events`, not `goalEvents` or
  `goal_events`).
- Plural nouns for collections: `/v1/memories`, not `/v1/memory`.
- Nested routes reflect ownership: `/v1/conversations/{id}/messages`.
- Actions that are not CRUD use a verb after the noun:
  `POST /v1/twins/{id}/forget-me`.

---

## Request and response bodies

- JSON only. `Content-Type: application/json`.
- Body keys are `snake_case`. The generated TypeScript client remaps them
  to `camelCase` for consumers; the wire format is `snake_case`.
- Enums are lowercase snake_case strings.
- Timestamps are RFC 3339 with a trailing `Z`. Client-supplied timestamps
  are ignored except where explicitly documented.
- IDs are UUIDv7 (time-ordered); the client never generates one for a
  new resource unless the endpoint documents idempotency (see below).

Every mutating endpoint returns the created or updated resource in full.

---

## Error envelope

All error responses share one shape:

```json
{
  "error": {
    "code": "memory_not_found",
    "message": "The memory with id 0193... does not exist or is not yours.",
    "details": { "memory_id": "0193..." },
    "request_id": "req_01JB..."
  }
}
```

- `code` is a stable, snake_case, machine-readable string.
- `message` is safe to show to the user.
- `details` is optional and structured. It never contains raw memory content.
- `request_id` is the OpenTelemetry trace id, useful for support tickets.
- HTTP status codes follow standard semantics: 400 client, 401 unauth,
  403 forbidden (has a user, wrong resource), 404 missing (resource
  doesn't exist or isn't theirs — the two are indistinguishable to the
  client, deliberately), 409 conflict, 422 validation, 429 rate limited,
  5xx server.

---

## Pagination

Cursor-based, always:

```
GET /v1/memories?limit=50&cursor=eyJ...
```

Response:

```json
{
  "items": [ ... ],
  "next_cursor": "eyJ...",
  "has_more": true
}
```

- `limit` default 50, max 200.
- `cursor` is opaque base64 JSON `{ "id": "<uuid>", "created_at": "<iso>" }`.
- `next_cursor` is `null` when `has_more` is false.
- Ordering is documented per endpoint and is stable within a cursor
  sequence.

No offset pagination anywhere. Ever.

---

## Rate limits

- Per user: 60 requests / minute default; 10 / minute for LLM-touching
  endpoints (`/conversations/{id}/messages`) unless a paying plan is active.
- Per IP: 300 / minute, floor.
- Exceeded: HTTP 429 with `Retry-After` in seconds.
- Rate limit state lives in Redis.

---

## Idempotency

Any endpoint that produces side effects can be called with an
`Idempotency-Key: <ulid>` header. The server stores the response for 24
hours and returns the same body/status on retry. This is required for:

- `POST /v1/conversations/{id}/messages`
- `POST /v1/goals`
- `POST /v1/memories`
- `POST /v1/twins/{id}/forget-me` (single-shot; the second call is a
  no-op returning the same 204)

Clients must retry with the same key. A different key is a different
operation.

---

## Streaming

`POST /v1/conversations/{id}/messages` supports both:

- `Accept: application/json` — buffered response.
- `Accept: text/event-stream` — Server-Sent Events; each event is one
  JSON object with `type ∈ { "delta", "citation", "done", "error" }`.

Never use raw newline-delimited JSON. Always SSE for streaming.

---

## Data hygiene

- No PII in log lines. Structured fields are used, and sensitive ones are
  redacted at emit time.
- Memory content is never logged. Memory IDs, similarity scores, and types
  are.
- Prompt bodies are hashed (SHA-256, truncated 8 chars) and logged, not
  stored verbatim outside a dedicated debug facility that requires
  elevated access.

---

## Endpoint catalogue (Sprint 1 target)

Not exhaustive; the canonical list is the generated OpenAPI schema.

```
GET    /v1/system/version
GET    /v1/system/health
GET    /v1/system/ready

GET    /v1/me                                   # current user + twin summary
PATCH  /v1/me                                   # display name, locale

GET    /v1/twins/{id}
PATCH  /v1/twins/{id}                           # twin display, persona knobs
POST   /v1/twins/{id}/forget-me
GET    /v1/twins/{id}/export

GET    /v1/twins/{id}/profile
PATCH  /v1/twins/{id}/profile                   # user-editable profile fields

GET    /v1/twins/{id}/personality-traits
POST   /v1/twins/{id}/personality-traits
DELETE /v1/twins/{id}/personality-traits/{tid}

GET    /v1/twins/{id}/preferences
POST   /v1/twins/{id}/preferences
PATCH  /v1/twins/{id}/preferences/{pid}
DELETE /v1/twins/{id}/preferences/{pid}

GET    /v1/conversations
POST   /v1/conversations
GET    /v1/conversations/{id}
GET    /v1/conversations/{id}/messages
POST   /v1/conversations/{id}/messages          # the chat turn

GET    /v1/memories
GET    /v1/memories/{id}
PATCH  /v1/memories/{id}
DELETE /v1/memories/{id}

GET    /v1/memory-candidates                    # pending confirmations
POST   /v1/memory-candidates/{id}/confirm
POST   /v1/memory-candidates/{id}/reject

GET    /v1/goals
POST   /v1/goals
PATCH  /v1/goals/{id}
DELETE /v1/goals/{id}
POST   /v1/goals/{id}/events
GET    /v1/goals/{id}/events

GET    /v1/reflections                           # stub in Sprint 2
```

---

## OpenAPI

FastAPI generates the OpenAPI 3.1 document at `/v1/openapi.json`.
`packages/shared-types/` is regenerated from it in CI. A schema drift
between the generated client and the app is a build failure, not a
warning.
