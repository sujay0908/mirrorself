# Deployment Execution Plan

## Prerequisites Checklist

### ✅ Done
- Firebase Project: `mirrorself-d6f1b` (Project #413477527072)
- Google Cloud Project: `project-14346235-d9f7-4d14-b72`
- firebase.json configured for App Hosting
- .firebaserc linked to Firebase project

### 📋 Need to Collect

Before proceeding, gather these credentials:

#### Supabase (from supabase.com dashboard)
- [ ] `SUPABASE_URL` (e.g., https://xxxxxxxxxxxx.supabase.co)
- [ ] `SUPABASE_PUBLISHABLE_KEY` (starts with `eyJ...`)
- [ ] `SUPABASE_SERVICE_ROLE_KEY` (starts with `eyJ...`)
- [ ] `SUPABASE_JWKS_URL` (https://xxxxxxxxxxxx.supabase.co/auth/v1/.well-known/jwks.json)
- [ ] Database connection string (Pooler)
- [ ] Database direct connection (for migrations)

#### Google Cloud
- [ ] GCP Project ID: `project-14346235-d9f7-4d14-b72` ✅
- [ ] `ANTHROPIC_API_KEY` (from Anthropic console)
- [ ] Docker authentication (gcloud auth)

#### Redis (Upstash)
- [ ] `REDIS_URL` (from upstash.com)

#### Your Domain (optional but recommended)
- [ ] Domain for backend API (e.g., api.yourdomain.com)
- [ ] Domain for frontend (e.g., app.yourdomain.com)

---

## Phase 1: Create Supabase Infrastructure

### Step 1: Storage Buckets
In Supabase Storage dashboard, create these buckets:
- [ ] `face-photos` (Private)
- [ ] `voice-samples` (Private)
- [ ] `voice-output` (Private)
- [ ] `avatars` (Public)

### Step 2: Auth Configuration
In Supabase Auth settings:
- [ ] Enable Email/Password auth
- [ ] Set "Site URL" to: `https://mirrorself-d6f1b.web.app`
- [ ] Add redirect URLs:
  - `https://mirrorself-d6f1b.web.app`
  - `https://mirrorself-d6f1b.firebaseapp.com`
  - `http://localhost:3000` (for local testing)

### Step 3: Database Migration
After all Supabase credentials collected:
```bash
# Set environment variables
$env:SUPABASE_DATABASE_URL = "your-direct-connection-string"

# Run migration
cd backend
python migrate.py
```

---

## Phase 2: Create Google Cloud Secrets

Run these commands with GCP project: `project-14346235-d9f7-4d14-b72`

```powershell
# Set project
gcloud config set project project-14346235-d9f7-4d14-b72

# Create secrets
echo $env:SUPABASE_URL | gcloud secrets create supabase-url --data-file=-
echo $env:SUPABASE_PUBLISHABLE_KEY | gcloud secrets create supabase-publishable-key --data-file=-
echo $env:SUPABASE_SERVICE_ROLE_KEY | gcloud secrets create supabase-service-role-key --data-file=-
echo $env:SUPABASE_JWKS_URL | gcloud secrets create supabase-jwks-url --data-file=-
echo $env:SUPABASE_DATABASE_URL | gcloud secrets create database-url --data-file=-
echo $env:REDIS_URL | gcloud secrets create redis-url --data-file=-
echo $env:ANTHROPIC_API_KEY | gcloud secrets create anthropic-api-key --data-file=-
```

---

## Phase 3: Deploy Backend to Cloud Run

```powershell
# Authenticate Docker
gcloud auth configure-docker

# Set variables
$GCP_PROJECT = "project-14346235-d9f7-4d14-b72"
$REGION = "us-central1"
$SERVICE_NAME = "mirrorself-api"

# Build and push
docker build -t gcr.io/$GCP_PROJECT/$SERVICE_NAME:latest ./backend
docker push gcr.io/$GCP_PROJECT/$SERVICE_NAME:latest

# Deploy to Cloud Run
gcloud run deploy $SERVICE_NAME `
  --image gcr.io/$GCP_PROJECT/$SERVICE_NAME:latest `
  --region $REGION `
  --platform managed `
  --memory 2Gi `
  --cpu 2 `
  --timeout 300 `
  --set-env-vars SUPABASE_URL=secret:supabase-url,SUPABASE_PUBLISHABLE_KEY=secret:supabase-publishable-key,DATABASE_URL=secret:database-url,REDIS_URL=secret:redis-url,SUPABASE_JWKS_URL=secret:supabase-jwks-url `
  --set-secrets SUPABASE_SERVICE_ROLE_KEY=supabase-service-role-key:latest,ANTHROPIC_API_KEY=anthropic-api-key:latest
```

Save the returned service URL: `https://mirrorself-api-xxxxx.run.app`

---

## Phase 4: Deploy Frontend to Firebase

### Step 1: Build frontend
```powershell
cd frontend
npm run build
```

### Step 2: Set environment variables
Update or create `frontend/.env.production`:
```
NEXT_PUBLIC_SUPABASE_URL=https://xxxxxxxxxxxx.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=eyJ...
NEXT_PUBLIC_API_BASE=/api
API_INTERNAL_URL=https://mirrorself-api-xxxxx.run.app/api
```

### Step 3: Deploy
```powershell
firebase deploy
```

---

## Phase 5: Verify Deployment

### Backend health checks
```powershell
$BACKEND_URL = "https://mirrorself-api-xxxxx.run.app"

# Health check
curl "$BACKEND_URL/health"

# Readiness check
curl "$BACKEND_URL/health/ready"
```

### Frontend verification
```powershell
# Open in browser
start "https://mirrorself-d6f1b.web.app"
```

### Test auth flow
1. Go to login page
2. Create account with Supabase
3. Complete onboarding
4. Test chat

---

## Next Steps
1. Collect all credentials listed above
2. Create Supabase storage buckets and configure Auth
3. Run `python backend/migrate.py`
4. Create GCP secrets
5. Deploy backend to Cloud Run
6. Deploy frontend to Firebase
7. Verify health endpoints
8. Test full user flow

---

## Troubleshooting

If deployment fails, check:
- Supabase credentials are correct
- GCP project ID is correct
- Storage buckets exist
- Database migration ran successfully
- All required env vars are set
- Docker authentication is configured

See [docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md) for detailed guides.
