# Backend Phase 2: production media/storage path

This phase moves backend media handling to Firebase Storage (backed by Google Cloud Storage) while keeping:

- Supabase Auth
- Supabase Postgres
- Upstash Redis
- Cloud Run for the FastAPI backend

## What changed in code

- The backend now uses Google Cloud Storage client APIs instead of Supabase Storage.
- Media is stored as object keys in the database and mapped to browser-usable download URLs in API responses.
- Upload/download processing uses the Firebase project bucket with structured prefixes:
  - `face-photos/`
  - `voice-samples/`
  - `voice-output/`
  - `avatars/`

Key files:

- [backend/app/services/storage_service.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/services/storage_service.py)
- [backend/app/services/response_mapper.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/services/response_mapper.py)
- [backend/app/services/chat_service.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/services/chat_service.py)
- [backend/app/api/onboarding.py](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/backend/app/api/onboarding.py)

## Runtime architecture

```text
FastAPI on Cloud Run
  -> Supabase Postgres
  -> Upstash Redis
  -> Firebase Storage bucket (GCS)
  -> Anthropic API
```

## Required environment variables

Backend:

```env
APP_ENV=production
DEBUG=false
LOG_LEVEL=INFO
SECRET_KEY=...
DATABASE_URL=...
DATABASE_URL_SYNC=...
REDIS_URL=...
SUPABASE_URL=https://PROJECT.supabase.co
SUPABASE_PUBLISHABLE_KEY=...
SUPABASE_JWKS_URL=https://PROJECT.supabase.co/auth/v1/.well-known/jwks.json
GCP_PROJECT_ID=your-gcp-project-id
FIREBASE_STORAGE_BUCKET=your-project-id.firebasestorage.app
FIREBASE_STORAGE_URL_MODE=firebase_token
STORAGE_URL_TTL_SECONDS=3600
PUBLIC_BASE_URL=https://api.yourdomain.com
CORS_ORIGINS=["https://app.yourdomain.com","http://localhost:3000"]
```

Secrets in Secret Manager:

- `anthropic-api-key`
- `secret-key`

## Cloud Run IAM

Create a dedicated Cloud Run service account and grant:

- `roles/secretmanager.secretAccessor` on the project
- `roles/storage.objectAdmin` on the Firebase/GCS bucket
- `roles/iam.serviceAccountTokenCreator` on itself if you switch to signed URL mode

The helper script is:

- [scripts/setup-cloud-run-iam.ps1](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/scripts/setup-cloud-run-iam.ps1)

## Why Firebase token URLs

Default mode is `firebase_token`, which gives browser-friendly media URLs without requiring auth headers on `<img>`, `<audio>`, or `<video>` tags.

Modes:

- `firebase_token` (default, easiest for frontend media tags)
- `signed_url` (requires signing-capable credentials)
- `public_url` (only for fully public buckets/objects)

## Artifact Registry + Cloud Run deploy

Use Artifact Registry, not Container Registry.

Scripts:

- [scripts/deploy-cloud-run.sh](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/scripts/deploy-cloud-run.sh)
- [scripts/deploy-cloud-run.ps1](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/scripts/deploy-cloud-run.ps1)
- [scripts/create-secrets.ps1](/abs/path/C:/Users/sujay/Downloads/mirror-self-ai/mirrorself/scripts/create-secrets.ps1)

## Local validation path

For local/backend validation you can still use Docker Compose for the PostgreSQL container and Redis container:

```bash
docker compose up -d postgres redis
```

Then point:

- `DATABASE_URL` to local Postgres
- `REDIS_URL` to local Redis or Upstash
- `FIREBASE_STORAGE_BUCKET` to the real Firebase bucket

## Deployment steps

1. Create Firebase project and default Storage bucket.
2. Enable Cloud Run, Artifact Registry, Secret Manager, IAM Credentials APIs.
3. Create/update secrets:

```powershell
$env:GCP_PROJECT_ID="your-project"
$env:ANTHROPIC_API_KEY="..."
$env:SECRET_KEY="..."
.\scripts\create-secrets.ps1
```

4. Configure IAM:

```powershell
$env:GCP_PROJECT_ID="your-project"
$env:FIREBASE_STORAGE_BUCKET="your-project-id.firebasestorage.app"
.\scripts\setup-cloud-run-iam.ps1
```

5. Set deployment env vars in your shell.
6. Deploy backend:

```powershell
.\scripts\deploy-cloud-run.ps1
```

## Validation checklist

- `/health` returns 200
- `/health/ready` returns 200 once Postgres and Redis are reachable
- onboarding face upload succeeds
- onboarding voice upload succeeds
- generated avatar path resolves to a Firebase media URL
- chat response contains `audio_url`
- public twin page can render `avatar_video_path`

## IAM / platform references

- Cloud Run service identity: https://docs.cloud.google.com/run/docs/configuring/services/service-identity
- Cloud Run secrets: https://docs.cloud.google.com/run/docs/configuring/services/secrets
- Cloud Run deploy from container image: https://docs.cloud.google.com/run/docs/deploying
- Artifact Registry image naming: https://docs.cloud.google.com/artifact-registry/docs/docker/names
- Cloud Storage signed URLs overview: https://docs.cloud.google.com/storage/docs/access-control/signed-urls
- Cloud Storage / Firebase integration: https://firebase.google.com/docs/storage/gcp-integration
