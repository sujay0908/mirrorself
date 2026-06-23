# Cloud Run Deployment Guide for MirrorSelf Backend

This guide walks through deploying the MirrorSelf FastAPI backend to Google Cloud Run.

## Prerequisites

### 1. Google Cloud Project
```bash
export GCP_PROJECT_ID="your-gcp-project-id"
gcloud auth login
gcloud config set project $GCP_PROJECT_ID
gcloud services enable run.googleapis.com
gcloud services enable secretmanager.googleapis.com
gcloud services enable containerregistry.googleapis.com
```

### 2. Supabase Setup
Before deploying, ensure you have:
- Supabase project created (https://supabase.com)
- Database credentials saved
- Storage buckets created:
  - `face-photos` (private)
  - `voice-samples` (private)
  - `voice-output` (private)
  - `avatars` (public or signed)

### 3. Redis Setup
Create a managed Redis instance (recommended: Upstash Redis):
- https://upstash.com
- Copy the REDIS_URL

### 4. Anthropic API Key
- Get key from https://console.anthropic.com/
- Will be stored in Cloud Run Secret Manager

## Step 1: Create Supabase Storage Buckets

In the Supabase dashboard, go to Storage and create these buckets:

```sql
-- Bucket: face-photos
-- Privacy: Private
-- Files from user onboarding

-- Bucket: voice-samples  
-- Privacy: Private
-- Voice cloning samples

-- Bucket: voice-output
-- Privacy: Private
-- Generated voice responses

-- Bucket: avatars
-- Privacy: Can be public (for generated talking head videos)
```

## Step 2: Store Secrets in Cloud Run Secret Manager

Store sensitive values in Google Cloud Secret Manager:

```bash
# Database connection string (transaction pooler)
echo -n "postgresql://user:pass@project.pooler.supabase.com:6543/postgres" | \
  gcloud secrets create database-url --data-file=-

# Redis URL
echo -n "redis://default:password@host:port" | \
  gcloud secrets create redis-url --data-file=-

# Supabase URL
echo -n "https://project.supabase.co" | \
  gcloud secrets create supabase-url --data-file=-

# Supabase Service Role Key
echo -n "your-service-role-key" | \
  gcloud secrets create supabase-service-role-key --data-file=-

# Supabase Publishable Key
echo -n "your-publishable-key" | \
  gcloud secrets create supabase-publishable-key --data-file=-

# Anthropic API Key
echo -n "sk-ant-..." | \
  gcloud secrets create anthropic-api-key --data-file=-
```

Verify secrets were created:
```bash
gcloud secrets list
```

## Step 3: Grant Cloud Run Service Account Access to Secrets

```bash
# Get the default Cloud Run service account
PROJECT_NUMBER=$(gcloud projects describe $GCP_PROJECT_ID --format='value(projectNumber)')
CLOUD_RUN_SA="$PROJECT_NUMBER-compute@developer.gserviceaccount.com"

# Grant Secret Accessor role
for secret in database-url redis-url supabase-url supabase-service-role-key supabase-publishable-key anthropic-api-key; do
  gcloud secrets add-iam-policy-binding $secret \
    --member=serviceAccount:$CLOUD_RUN_SA \
    --role=roles/secretmanager.secretAccessor
done
```

## Step 4: Deploy Backend to Cloud Run

### Option A: Using Deployment Script (Recommended)

```bash
# From project root
export GCP_PROJECT_ID="your-project-id"
export SERVICE_REGION="us-central1"  # or another region
bash scripts/deploy-cloud-run.sh
```

### Option B: Manual gcloud CLI Command

```bash
gcloud run deploy mirrorself-api \
  --source . \
  --region us-central1 \
  --platform managed \
  --allow-unauthenticated \
  --port 8000 \
  --min-instances 1 \
  --max-instances 10 \
  --memory 2Gi \
  --cpu 1 \
  --timeout 600 \
  --set-env-vars APP_ENV=production,DEBUG=false,LOG_LEVEL=INFO \
  --set-secrets=ANTHROPIC_API_KEY=anthropic-api-key:latest \
  --set-secrets=DATABASE_URL=database-url:latest \
  --set-secrets=REDIS_URL=redis-url:latest \
  --set-secrets=SUPABASE_URL=supabase-url:latest \
  --set-secrets=SUPABASE_SERVICE_ROLE_KEY=supabase-service-role-key:latest \
  --set-secrets=SUPABASE_PUBLISHABLE_KEY=supabase-publishable-key:latest
```

## Step 5: Verify Deployment

Once deployment completes, you'll get a service URL. Test it:

```bash
SERVICE_URL=$(gcloud run services describe mirrorself-api \
  --platform managed \
  --region us-central1 \
  --format 'value(status.url)')

# Liveness check
curl $SERVICE_URL/health

# Readiness check (checks Postgres + Redis)
curl $SERVICE_URL/health/ready

# Check logs
gcloud run logs read mirrorself-api --region us-central1 --limit 50
```

Expected health/ready response:
```json
{
  "postgres": true,
  "redis": true
}
```

## Step 6: Run Database Migrations

The backend creates tables automatically on startup via SQLAlchemy. However, if you need to run Alembic migrations:

```bash
# Download the service URL
SERVICE_URL=$(gcloud run services describe mirrorself-api \
  --platform managed \
  --region us-central1 \
  --format 'value(status.url)')

# Migrations already run on startup, but you can verify:
curl $SERVICE_URL/health/ready
```

## Step 7: Configure Frontend to Connect

After backend deployment, update the frontend with the Cloud Run URL:

```bash
# Get the backend service URL
SERVICE_URL=$(gcloud run services describe mirrorself-api \
  --platform managed \
  --region us-central1 \
  --format 'value(status.url)')

# Update frontend environment
# API_INTERNAL_URL should be: $SERVICE_URL/api
# For example: https://mirrorself-api-abc123def-uc.a.run.app/api
```

Update `frontend/.env` or Firebase environment variables:
```env
API_INTERNAL_URL=https://mirrorself-api-abc123def-uc.a.run.app/api
```

## Scaling and Cost Optimization

### Current Configuration
- **Min instances**: 1 (always running)
- **Max instances**: 10 (scales automatically)
- **Memory**: 2 GB
- **CPU**: 1 vCPU
- **Timeout**: 10 minutes (for generation tasks)

### For Production (with high traffic)
```bash
gcloud run services update mirrorself-api \
  --region us-central1 \
  --min-instances 2 \
  --max-instances 50 \
  --memory 4Gi \
  --cpu 2
```

### Cost Optimization (for low traffic)
```bash
gcloud run services update mirrorself-api \
  --region us-central1 \
  --min-instances 0 \
  --max-instances 5 \
  --memory 2Gi \
  --cpu 1
```

Note: With `--min-instances=0`, the first request will have a cold start (~5-10 seconds).

## Troubleshooting

### Readiness probe failing
Check the logs:
```bash
gcloud run logs read mirrorself-api --region us-central1 --limit 100
```

Common issues:
- **Database connection**: Verify `DATABASE_URL` in secrets
- **Redis connection**: Verify `REDIS_URL` in secrets
- **Network**: Ensure Cloud Run can reach Supabase and Upstash

### Health endpoint returns 503
```bash
curl https://your-service-url/health/ready -v
```

Check what's failing (postgres or redis) in the response.

### Slow deployments
- Reduce max concurrent deployments in settings
- Build image locally first with `docker build -t ...`
- Use Cloud Build for CI/CD

## Environment Variables Reference

| Variable | Source | Purpose |
|----------|--------|---------|
| `APP_ENV` | Literal | Set to "production" |
| `DEBUG` | Literal | Set to false |
| `LOG_LEVEL` | Literal | Set to INFO |
| `DATABASE_URL` | Secret | Supabase transaction pooler connection string |
| `REDIS_URL` | Secret | Upstash or Memorystore Redis URL |
| `SUPABASE_URL` | Secret | https://project.supabase.co |
| `SUPABASE_SERVICE_ROLE_KEY` | Secret | From Supabase Settings > API |
| `SUPABASE_PUBLISHABLE_KEY` | Secret | From Supabase Settings > API |
| `ANTHROPIC_API_KEY` | Secret | From Anthropic console |

## Next Steps

1. ✅ Backend deployed to Cloud Run
2. ⏭️ Deploy frontend to Firebase App Hosting (see [firebase-deployment.md](./firebase-deployment.md))
3. ⏭️ Set up async media generation worker (optional, for scalability)

## Additional Resources

- [Cloud Run Documentation](https://cloud.google.com/run/docs)
- [Cloud Run Environment Variables](https://cloud.google.com/run/docs/configuring/environment-variables)
- [Cloud Run Secrets](https://cloud.google.com/run/docs/configuring/services/secrets)
- [Supabase Database Connection](https://supabase.com/docs/guides/database/connecting-to-postgres)
