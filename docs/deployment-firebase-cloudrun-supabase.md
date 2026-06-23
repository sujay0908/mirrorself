# MirrorSelf deployment plan

Target stack:

- Frontend: Firebase App Hosting
- Backend API: Google Cloud Run
- Database: Supabase Postgres
- Auth: Supabase Auth
- Media storage: Supabase Storage
- Short-term memory/cache: Redis (recommended: Upstash Redis)

## 1. Executive summary

This app can deploy cleanly to your target stack, but not as-is.

Three parts of the current codebase need real changes before production:

1. Auth is custom today, but you want Supabase Auth.
2. Media files are stored on local disk today, but Cloud Run instances are ephemeral.
3. The app depends on Redis for short-term memory, and Supabase does not replace Redis.

My recommended production architecture is:

```text
Browser
  -> Firebase App Hosting (Next.js frontend + route handlers)
     -> Cloud Run API (FastAPI)
        -> Supabase Auth (JWT verification + user identity)
        -> Supabase Postgres (app data)
        -> Supabase Storage (face photos, voice samples, generated audio, avatars)
        -> Redis (short-term memory / cache)
        -> Anthropic API
```

For AI media generation, I recommend a split between:

- synchronous API traffic on Cloud Run
- asynchronous generation for heavy voice/avatar work

That split is strongly recommended if you want real XTTS/SadTalker in production.

## 2. Why this architecture

### Frontend: use Firebase App Hosting, not classic Firebase Hosting

This frontend is a Next.js App Router app with server-side route handlers under `frontend/src/app/api/[...path]/route.ts`.
That fits Firebase App Hosting better than classic static Hosting.

Why:

- it has built-in support for Next.js
- it supports SSR and route handlers
- it integrates with GitHub for continuous deployments
- under the hood it uses Google Cloud services including Cloud Run and Cloud CDN

### Backend: Cloud Run is a good fit for the API

FastAPI on Cloud Run is a good match for:

- stateless HTTP APIs
- autoscaling traffic
- secret management through Secret Manager
- container-based deployment

But Cloud Run is not a durable local filesystem. Anything in `./storage/...` must move to object storage.

### Database + Auth: Supabase fits well

Supabase can cover:

- Postgres for app tables
- Auth for sign-up/sign-in/session JWTs
- Storage for uploaded and generated media

That lets you simplify identity handling and centralize user/media data.

### Redis: still needed unless you refactor memory

The current backend uses Redis for:

- recent facts
- short-term conversation context

Supabase does not provide a drop-in Redis replacement. You have two choices:

1. keep Redis as a managed dependency
2. refactor short-term memory into Postgres only

I recommend keeping Redis for the first deployment and revisiting later.

## 3. Current gaps in this repo

### Auth gap

Current code:

- custom registration/login in [backend/app/api/auth.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/api/auth.py)
- custom JWT creation/verification in [backend/app/core/security.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/core/security.py)
- current user lookup from local JWT `sub` in [backend/app/api/deps.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/api/deps.py)
- frontend login/register pages call custom endpoints in [frontend/src/app/login/page.tsx](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/frontend/src/app/login/page.tsx) and [frontend/src/app/register/page.tsx](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/frontend/src/app/register/page.tsx)

Target state:

- Supabase issues the access token
- frontend signs users in with Supabase
- backend verifies Supabase JWTs
- backend maps Supabase user ID to the local `users` table

### Storage gap

Current code writes face/audio/video files to local paths such as:

- `./storage/face_photos`
- `./storage/voice_samples`
- `./storage/voice_output`
- `./storage/avatars`

Relevant files:

- [backend/app/api/onboarding.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/api/onboarding.py)
- [backend/app/services/voice_service.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/services/voice_service.py)
- [backend/app/services/avatar_service.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/services/avatar_service.py)

That will not be safe on Cloud Run because instances are ephemeral and horizontally scaled.

### URL gap

The frontend expects `face_photo_path`, `avatar_video_path`, `audio_url`, and `video_url` to be fetchable URLs, but the backend currently stores file paths and not stable public/signed URLs.

### Redis dependency gap

Short-term memory currently depends on:

- [backend/app/core/redis_client.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/core/redis_client.py)
- [backend/app/services/memory_service.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/services/memory_service.py)

## 4. Recommended deployment design

## 4.1 Frontend

Deploy the `frontend/` app to Firebase App Hosting.

Keep the existing Next.js proxy pattern:

- browser calls `/api/...`
- Next.js route handler forwards to Cloud Run

This gives you:

- same-origin browser traffic
- less frontend CORS pain
- one place to attach auth headers

Important fix:

The route handler should treat `API_INTERNAL_URL` as the backend base ending in `/api`, not `/api/v1`.

Recommended production value:

```env
API_INTERNAL_URL=https://YOUR-CLOUD-RUN-URL/api
NEXT_PUBLIC_API_BASE=/api
```

## 4.2 Backend API

Deploy one FastAPI Cloud Run service for:

- auth-aware API endpoints
- onboarding
- chat
- public profile endpoints
- storage coordination

Recommended first deployment shape:

- public HTTPS endpoint
- min instances: 1 if cold starts hurt
- reasonable CPU/memory sizing
- Secret Manager for sensitive env vars
- Supabase transaction pooler connection string for runtime app traffic

## 4.3 Async AI worker

Recommended, especially if you want real XTTS/SadTalker:

- create a second Cloud Run service or Cloud Run job for media generation
- trigger it asynchronously from the API via Cloud Tasks or Pub/Sub

Why:

- avatar generation is slow
- voice cloning/model loading is heavy
- synchronous request time is a poor fit for expensive media generation

Recommended split:

- API service:
  - validates upload
  - creates DB records
  - enqueues generation
  - returns status

- Worker service:
  - downloads source files from Supabase Storage
  - runs XTTS/SadTalker
  - uploads outputs to Supabase Storage
  - updates DB status

## 4.4 Database

Use Supabase Postgres for:

- users
- conversations
- messages
- facts

For Cloud Run runtime traffic, use Supabase’s transaction pooler connection string.
For migrations, use the direct connection string.

## 4.5 Auth

Use Supabase Auth for:

- email/password
- magic link if you want later
- social providers later if needed

Recommended identity model:

- Supabase Auth is the source of truth for authentication
- your `users` table remains the source of truth for app profile and twin data
- link them through a `supabase_user_id` column

## 4.6 Storage

Use Supabase Storage buckets:

- `face-photos`
- `voice-samples`
- `voice-output`
- `avatars`

Store object paths in Postgres, not local file paths.

Examples:

- `face-photos/user_123/portrait.jpg`
- `voice-samples/user_123/source.wav`
- `voice-output/user_123/msg_987.wav`
- `avatars/user_123/talk_123.mp4`

For delivery:

- private buckets for raw inputs
- signed URLs for sensitive assets
- public or signed URLs for generated assets depending on your privacy model

## 4.7 Redis

Recommended first choice: Upstash Redis.

Why:

- easiest external Redis for Cloud Run
- no VPC setup needed
- simplest migration from current `REDIS_URL`

Alternative:

- Google Memorystore, if you want a more GCP-native setup and are okay with VPC networking

## 5. Changes you need to make in the codebase

This is the practical part.

## 5.1 Backend auth changes

### Files to change

- [backend/app/models/user.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/models/user.py)
- [backend/app/api/auth.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/api/auth.py)
- [backend/app/api/deps.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/api/deps.py)
- [backend/app/core/security.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/core/security.py)
- [backend/app/schemas/user.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/schemas/user.py)

### Required changes

1. Add a `supabase_user_id` column to `users`
   - type: UUID or string
   - unique
   - indexed

2. Make `hashed_password` nullable if you are fully moving to Supabase Auth

3. Replace local JWT decoding with Supabase JWT verification

4. Change `get_current_user()` so it:
   - reads the bearer token
   - verifies the Supabase JWT
   - extracts `sub`
   - finds `users.supabase_user_id == sub`

5. Replace `/auth/register` and `/auth/login`

Recommended new auth endpoints:

- `POST /api/v1/auth/bootstrap`
  - accepts authenticated Supabase token
  - creates local user row if missing
  - returns app profile

- `GET /api/v1/auth/me`
  - unchanged purpose
  - now based on Supabase JWT instead of local JWT

### Recommended shape for the `users` table

Keep:

- `id`
- `email`
- `username`
- `display_name`
- `bio`
- twin-related fields

Add:

- `supabase_user_id`

Optional:

- remove `hashed_password` later after migration

## 5.2 Frontend auth changes

### Files to change

- [frontend/src/app/login/page.tsx](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/frontend/src/app/login/page.tsx)
- [frontend/src/app/register/page.tsx](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/frontend/src/app/register/page.tsx)
- [frontend/src/lib/auth-store.ts](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/frontend/src/lib/auth-store.ts)
- [frontend/src/lib/api.ts](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/frontend/src/lib/api.ts)

### New files to add

- `frontend/src/lib/supabase/client.ts`
- `frontend/src/lib/supabase/server.ts`
- optional middleware if you want SSR session refresh behavior

### Required changes

1. Install:

```bash
npm install @supabase/supabase-js @supabase/ssr
```

2. Replace custom register/login calls with Supabase Auth calls

3. After sign-up/sign-in, call backend bootstrap endpoint so the app creates or fetches the local profile row

4. Stop persisting the custom backend token in Zustand

5. Instead:
   - use Supabase session as auth source
   - store only app profile in Zustand if you want

6. Update API client so every authenticated request sends the current Supabase access token in `Authorization: Bearer ...`

## 5.3 Backend storage changes

### Files to change

- [backend/app/api/onboarding.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/api/onboarding.py)
- [backend/app/services/voice_service.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/services/voice_service.py)
- [backend/app/services/avatar_service.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/services/avatar_service.py)
- [backend/app/services/chat_service.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/services/chat_service.py)
- [backend/app/models/user.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/models/user.py)
- [backend/app/models/conversation.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/models/conversation.py)
- [backend/app/schemas/chat.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/schemas/chat.py)

### New backend abstraction to add

Add a storage service, for example:

- `backend/app/services/storage_service.py`

Responsibilities:

- upload file to Supabase Storage
- download file from Supabase Storage to `/tmp`
- build signed/public URLs
- delete obsolete assets if needed

### Required changes

1. Use `/tmp` only for transient processing
2. Upload final files to Supabase Storage
3. Store storage object keys or canonical URLs in DB
4. Return signed/public URLs in API responses

### Important modeling change

Today these fields are really filesystem paths:

- `face_photo_path`
- `voice_sample_path`
- `avatar_video_path`
- `audio_path`
- `video_path`

After refactor they should become one of:

- object key
- storage URL

I recommend storing object keys internally and generating URLs in the API layer.

## 5.4 API URL/proxy changes

### File to change

- [frontend/src/app/api/[...path]/route.ts](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/frontend/src/app/api/[...path]/route.ts)

### Required changes

Make sure:

- `API_INTERNAL_URL` points to `https://backend-service/api`
- not `https://backend-service/api/v1`

Because the route handler already strips `/api` and keeps `/v1/...`.

## 5.5 Environment/config changes

### Files to change

- [backend/app/core/config.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/core/config.py)
- [.env.example](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/.env.example)
- [frontend/.env.example](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/frontend/.env.example)

### Add backend env vars

```env
SUPABASE_URL=
SUPABASE_PUBLISHABLE_KEY=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_JWKS_URL=
SUPABASE_STORAGE_FACE_BUCKET=face-photos
SUPABASE_STORAGE_VOICE_SAMPLES_BUCKET=voice-samples
SUPABASE_STORAGE_VOICE_OUTPUT_BUCKET=voice-output
SUPABASE_STORAGE_AVATARS_BUCKET=avatars
REDIS_URL=
APP_BASE_URL=
FRONTEND_BASE_URL=
```

### Add frontend env vars

```env
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=
NEXT_PUBLIC_API_BASE=/api
API_INTERNAL_URL=https://YOUR-CLOUD-RUN-URL/api
```

## 6. Supabase setup steps

## 6.1 Create the Supabase project

In Supabase:

1. Create a project
2. Save:
   - project URL
   - publishable key
   - service role key
   - DB passwords and connection strings

## 6.2 Configure Auth

1. Enable email/password auth
2. Set site URL to your Firebase frontend domain
3. Add redirect URLs for:
   - Firebase production domain
   - Firebase preview domain(s), if you will use them
   - localhost for development

## 6.3 Create Storage buckets

Create:

- `face-photos`
- `voice-samples`
- `voice-output`
- `avatars`

Recommended privacy:

- `face-photos`: private
- `voice-samples`: private
- `voice-output`: private or signed only
- `avatars`: public only if the user has made the twin public; otherwise private

## 6.4 Run database migrations

Use the direct Supabase Postgres connection string for Alembic migrations.

You will need at least one schema migration for:

- `users.supabase_user_id`
- `users.hashed_password` nullable if migrating away from local auth
- any storage path/URL column adjustments you decide to make

## 7. Firebase frontend deployment steps

## 7.1 Choose Firebase App Hosting

Do not use plain static Hosting for this app unless you remove server-side behavior.

Why:

- this app uses Next.js App Router
- it has server route handlers
- it benefits from SSR support

## 7.2 Prepare the frontend

1. Finish Supabase frontend auth integration
2. Update `API_INTERNAL_URL` expectation
3. Verify local production build

Suggested local test:

```bash
cd frontend
npm run build
npm run start
```

## 7.3 Create the App Hosting backend

In Firebase:

1. Create/select project
2. Enable Blaze plan
3. Set up App Hosting
4. Connect your GitHub repo
5. Select the live branch
6. Set frontend runtime env vars/secrets

Key frontend env vars:

- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`
- `NEXT_PUBLIC_API_BASE=/api`
- `API_INTERNAL_URL=https://YOUR-CLOUD-RUN-URL/api`

## 7.4 Configure domain

Attach your custom frontend domain in Firebase App Hosting.

Examples:

- `app.yourdomain.com`
- `www.yourdomain.com`

Use that same URL in:

- Supabase Auth site URL
- Supabase redirect URLs
- backend `CORS_ORIGINS`

## 8. Cloud Run backend deployment steps

## 8.1 Prepare the container

Your backend already has a Dockerfile:

- [backend/Dockerfile](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/Dockerfile)

Before deploying:

1. finish auth refactor
2. finish storage refactor
3. verify the service runs with production env vars

## 8.2 Required runtime secrets/config

Use Cloud Run + Secret Manager for:

- `ANTHROPIC_API_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- any private signing or integration secrets

Use normal env vars for:

- `SUPABASE_URL`
- `SUPABASE_JWKS_URL`
- `DATABASE_URL`
- `REDIS_URL`
- `PUBLIC_BASE_URL`
- `CORS_ORIGINS`

## 8.3 Database connection choice

Recommended:

- runtime app traffic -> Supabase transaction pooler
- migrations -> direct connection

That matches Cloud Run’s autoscaling model better.

## 8.4 Cloud Run service settings

Recommended starting point:

- ingress: all
- authentication: allow unauthenticated if frontend proxy will call it publicly
- min instances: 1
- max instances: start conservative
- CPU always allocated: optional if long inference work is inside request path
- memory: increase above default if keeping ML dependencies in the same container
- timeout: increase if you keep generation synchronous

## 8.5 CORS

If the frontend always proxies through Next.js route handlers, CORS matters less.

Still, configure backend CORS for:

- local dev
- your Firebase frontend domain
- preview domains if needed

## 8.6 Health checks

Use existing endpoints:

- `/health`
- `/health/ready`

Make sure readiness does not hard-fail because of optional model components.

## 9. Redis deployment steps

## Option A: Upstash Redis (recommended)

1. Create Redis database
2. Copy `REDIS_URL`
3. Store it in Cloud Run env vars/secrets
4. Test:
   - app startup ping
   - chat memory flow

## Option B: Google Memorystore

Use this only if you want tighter GCP integration and accept extra networking setup.

## 10. Recommended implementation order

This is the safest sequence.

### Phase 1: auth migration

1. Add Supabase frontend auth
2. Add backend Supabase JWT verification
3. Add `supabase_user_id`
4. Add backend bootstrap/profile sync endpoint
5. Confirm login, signup, `/me`

### Phase 2: storage migration

1. Add storage service abstraction
2. Move uploads to Supabase Storage
3. Generate signed/public URLs
4. Update frontend media rendering
5. Confirm onboarding works

### Phase 3: deploy the API

1. Point DB to Supabase
2. Point Redis to managed Redis
3. Deploy Cloud Run
4. Verify health/readiness
5. Test auth + onboarding + chat with stub media if needed

### Phase 4: deploy the frontend

1. Deploy to Firebase App Hosting
2. Configure frontend env vars
3. Set Supabase redirect URLs
4. Test full browser flows

### Phase 5: async media generation

1. Split generation off the request path
2. Introduce queue/worker
3. Add status polling or websocket updates

## 11. Strong recommendation about XTTS and SadTalker

If you only want the app deployed and functioning soon:

- ship the API first
- keep media generation in stub or reduced mode
- then add async worker infrastructure

If you try to deploy full real-time XTTS + SadTalker in the same synchronous Cloud Run API path on day one, you are likely to hit:

- cold start pain
- long request latency
- higher memory/CPU costs
- operational instability

## 12. Concrete step-by-step checklist

## Step 1: add Supabase project resources

- create Supabase project
- enable Auth
- create Storage buckets
- save DB connection strings

## Step 2: update backend user model

Change [backend/app/models/user.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/models/user.py):

- add `supabase_user_id`
- make password field optional if fully migrating

Then create Alembic migration.

## Step 3: replace backend JWT auth

Change:

- [backend/app/api/deps.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/api/deps.py)
- [backend/app/core/security.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/core/security.py)

New behavior:

- verify Supabase JWT
- resolve local user by `supabase_user_id`

## Step 4: replace frontend login/register

Change:

- [frontend/src/app/login/page.tsx](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/frontend/src/app/login/page.tsx)
- [frontend/src/app/register/page.tsx](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/frontend/src/app/register/page.tsx)

New behavior:

- sign in/up with Supabase
- call backend bootstrap

## Step 5: update auth state handling

Change:

- [frontend/src/lib/auth-store.ts](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/frontend/src/lib/auth-store.ts)
- [frontend/src/lib/api.ts](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/frontend/src/lib/api.ts)

New behavior:

- use Supabase session token
- attach bearer token on API calls

## Step 6: add storage abstraction

Add:

- `backend/app/services/storage_service.py`

Then update:

- [backend/app/api/onboarding.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/api/onboarding.py)
- [backend/app/services/voice_service.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/services/voice_service.py)
- [backend/app/services/avatar_service.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/services/avatar_service.py)

## Step 7: fix media URLs

Change:

- [backend/app/services/chat_service.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/services/chat_service.py)
- [backend/app/schemas/chat.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/schemas/chat.py)

Make sure API responses return URLs, not filesystem paths.

## Step 8: update env files

Change:

- [.env.example](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/.env.example)
- [frontend/.env.example](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/frontend/.env.example)

## Step 9: deploy backend

- create Secret Manager secrets
- deploy Cloud Run service
- set DB/Redis/Supabase env vars
- verify `/health/ready`

## Step 10: deploy frontend

- create Firebase App Hosting backend
- connect GitHub repo
- set frontend env vars
- deploy

## Step 11: wire domains

- frontend custom domain in Firebase
- backend optional custom domain in Cloud Run
- Supabase redirect URLs updated
- CORS updated

## 13. Recommended production environment values

### Backend

```env
APP_ENV=production
DEBUG=false
LOG_LEVEL=INFO
DATABASE_URL=postgres://...@aws-REGION.pooler.supabase.com:6543/postgres
DATABASE_URL_SYNC=postgresql://...direct-or-session-string-for-migrations-only
REDIS_URL=redis://default:...@...upstash.io:6379
SUPABASE_URL=https://PROJECT.supabase.co
SUPABASE_PUBLISHABLE_KEY=...
SUPABASE_SERVICE_ROLE_KEY=...
SUPABASE_JWKS_URL=https://PROJECT.supabase.co/auth/v1/.well-known/jwks.json
PUBLIC_BASE_URL=https://app.yourdomain.com
CORS_ORIGINS=["https://app.yourdomain.com","http://localhost:3000"]
```

### Frontend

```env
NEXT_PUBLIC_SUPABASE_URL=https://PROJECT.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=...
NEXT_PUBLIC_API_BASE=/api
API_INTERNAL_URL=https://api.yourdomain.com/api
```

## 14. Risks and mitigations

| Risk | Why it matters | Mitigation |
|---|---|---|
| Local file storage on Cloud Run | files disappear or split across instances | move all durable media to Supabase Storage |
| Custom JWT mixed with Supabase Auth | duplicated auth systems become brittle | migrate fully to Supabase JWTs |
| Too many DB connections | Cloud Run scales horizontally | use Supabase transaction pooler for runtime |
| Redis missing in production | memory service breaks | add Upstash Redis from day one |
| Slow media generation | long API response times | move generation to async worker |
| Preview domain auth issues | magic links / callbacks fail | add Firebase preview domains to Supabase redirects |

## 15. What I would do first

If we were implementing this together, I’d do it in this order:

1. Supabase Auth migration
2. `supabase_user_id` migration
3. frontend token plumbing
4. storage abstraction
5. Cloud Run backend deployment
6. Firebase App Hosting deployment
7. async media worker

That order minimizes rework.

## 16. Official docs I used

- Firebase App Hosting overview: https://firebase.google.com/docs/app-hosting
- Cloud Run deployment docs: https://cloud.google.com/run/docs/deploying
- Cloud Run secrets docs: https://cloud.google.com/run/docs/configuring/services/secrets
- Supabase Postgres connection docs: https://supabase.com/docs/guides/database/connecting-to-postgres
- Supabase JWT docs: https://supabase.com/docs/guides/auth/jwts
- Supabase SSR client docs for Next.js: https://supabase.com/docs/guides/auth/server-side/nextjs
- Supabase Storage docs: https://supabase.com/docs/guides/storage

## 17. Final recommendation

Yes, this stack is a solid choice.

But the clean deployment version of this app is:

- Firebase App Hosting for the Next.js frontend
- Cloud Run for the FastAPI API
- Supabase for Auth + Postgres + Storage
- Redis as one extra managed dependency
- asynchronous worker for heavy media generation

That is the version I’d trust in production.
