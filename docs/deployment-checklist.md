# MirrorSelf Deployment Checklist

Complete this checklist to deploy MirrorSelf to production (Firebase + Cloud Run + Supabase).

## Phase 0: Prerequisites ✅

- [ ] Google Cloud Project created and Blaze plan enabled
- [ ] Firebase project created
- [ ] Supabase project created
- [ ] Upstash Redis instance created
- [ ] Anthropic API key obtained
- [ ] GitHub repository configured
- [ ] Local environment setup complete

## Phase 1: Infrastructure Setup

### Supabase Configuration

- [ ] **Supabase Auth**
  - [ ] Email/password authentication enabled
  - [ ] Confirm email enabled (recommended)
  - [ ] Site URL configured (e.g., `https://app.yourdomain.com`)
  - [ ] Redirect URLs added:
    - `https://app.yourdomain.com/**`
    - `http://localhost:3000` (dev)
    - `http://localhost:3001` (dev)

- [ ] **Supabase Storage Buckets** (create these):
  - [ ] `face-photos` (private)
  - [ ] `voice-samples` (private)
  - [ ] `voice-output` (private)
  - [ ] `avatars` (public or signed)

- [ ] **Supabase Database**
  - [ ] Note connection strings:
    - Transaction pooler: `postgresql://...@pooler.supabase.com:6543/...`
    - Direct: `postgresql://...@db.supabase.com:5432/...`
  - [ ] Save credentials securely

### Google Cloud Setup

- [ ] **Enable APIs**:
  - [ ] Cloud Run
  - [ ] Secret Manager
  - [ ] Container Registry
  - [ ] Cloud Build

- [ ] **Create Cloud Run Secrets**:
  - [ ] `database-url` (Supabase transaction pooler)
  - [ ] `redis-url` (Upstash)
  - [ ] `supabase-url`
  - [ ] `supabase-service-role-key`
  - [ ] `supabase-publishable-key`
  - [ ] `anthropic-api-key`

- [ ] **Grant Service Account Access**:
  - [ ] Cloud Run service account has `secretmanager.secretAccessor` role

### Firebase Setup

- [ ] **Firebase Project**:
  - [ ] Project created
  - [ ] Blaze plan enabled
  - [ ] GitHub repository connected
  - [ ] App Hosting configured

## Phase 2: Backend Deployment

- [ ] **Local Testing**:
  - [ ] Backend runs locally with all env vars
  - [ ] `GET /health` returns `{"status": "ok"}`
  - [ ] `GET /health/ready` returns `{"postgres": true, "redis": true}`

- [ ] **Backend Code Ready**:
  - [ ] Supabase migrations applied
  - [ ] Database schemas created (auto-runs on startup)
  - [ ] Storage service integrated

- [ ] **Deploy to Cloud Run**:
  - [ ] Run `bash scripts/deploy-cloud-run.sh`
  - [ ] Or use manual `gcloud run deploy` command
  - [ ] Deployment completes successfully
  - [ ] Get service URL

- [ ] **Verify Cloud Run**:
  - [ ] `curl $SERVICE_URL/health` returns ok
  - [ ] `curl $SERVICE_URL/health/ready` returns postgres+redis true
  - [ ] Check logs for errors: `gcloud run logs read mirrorself-api`

- [ ] **Database Migrations**:
  - [ ] Tables created automatically on first startup
  - [ ] Alembic migrations applied (auto-runs on startup)

## Phase 3: Frontend Deployment

- [ ] **Local Testing**:
  - [ ] Frontend builds: `npm run build`
  - [ ] No TypeScript errors: `npm run typecheck`
  - [ ] Auth flow works with local backend

- [ ] **Configure Firebase**:
  - [ ] Environment variables set in Firebase:
    - `NEXT_PUBLIC_SUPABASE_URL`
    - `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`
    - `NEXT_PUBLIC_API_BASE=/api`
    - `API_INTERNAL_URL=$BACKEND_URL/api`

- [ ] **Deploy Frontend**:
  - [ ] Connect GitHub repository to App Hosting
  - [ ] Select `main` branch
  - [ ] Set root directory: `frontend/`
  - [ ] Push to `main` (or manual deploy via `firebase deploy`)
  - [ ] Deployment completes

- [ ] **Configure Custom Domain**:
  - [ ] Purchase or transfer domain
  - [ ] Add DNS records for Firebase
  - [ ] Domain attached to App Hosting
  - [ ] HTTPS certificate provisioned

## Phase 4: Supabase Configuration

- [ ] **Update Auth Redirects**:
  - [ ] Add Firebase domain to Supabase URL Configuration
  - [ ] Test sign-up and login flows

- [ ] **Configure Storage Buckets**:
  - [ ] Bucket policies set correctly
  - [ ] CORS configured if needed
  - [ ] Signed URL expiration set (default: 1 hour)

## Phase 5: Testing

### Auth Flow

- [ ] Sign up with new account
  - [ ] Form validates input
  - [ ] Backend bootstrap endpoint called
  - [ ] Local user profile created
  - [ ] Redirected to onboarding

- [ ] Login with existing account
  - [ ] Form validates credentials
  - [ ] Supabase auth succeeds
  - [ ] Backend bootstrap endpoint called
  - [ ] Redirected to chat or onboarding

- [ ] Logout
  - [ ] Session cleared
  - [ ] Redirected to login page

### Onboarding Flow

- [ ] Upload face photo
  - [ ] File uploaded to Supabase Storage
  - [ ] Image validated
  - [ ] Path stored in database

- [ ] Upload voice sample
  - [ ] Audio file uploaded to Supabase Storage
  - [ ] Duration validated (6-120 seconds)
  - [ ] Voice cloned and stored locally
  - [ ] Path stored in database

- [ ] Complete personality quiz
  - [ ] Form validates input
  - [ ] Profile updated with personality
  - [ ] Status set to "processing"

- [ ] Generate avatar
  - [ ] Face photo downloaded from Storage
  - [ ] SadTalker generates video
  - [ ] Video uploaded to Supabase Storage
  - [ ] Status set to "ready"

### Chat Flow

- [ ] Send message
  - [ ] Message sent to backend
  - [ ] Sentiment analyzed
  - [ ] LLM generates response
  - [ ] Audio synthesized
  - [ ] Audio uploaded to Supabase Storage
  - [ ] Avatar video generated
  - [ ] Video uploaded to Supabase Storage
  - [ ] Response displayed with media

- [ ] View conversation history
  - [ ] Previous messages loaded
  - [ ] Media (audio/video) displays correctly

### Error Handling

- [ ] Network error handling
- [ ] Invalid input validation
- [ ] Auth token expiration
- [ ] Storage upload failures
- [ ] Backend service downtime

## Phase 6: Monitoring & Optimization

- [ ] **Monitoring**:
  - [ ] Cloud Run metrics dashboard set up
  - [ ] Alert on high error rate
  - [ ] Alert on slow response times
  - [ ] Log aggregation configured

- [ ] **Scaling**:
  - [ ] Cloud Run min/max instances configured
  - [ ] Cold start time acceptable (< 30 seconds)
  - [ ] Concurrent requests handled

- [ ] **Costs**:
  - [ ] Review Cloud Run costs
  - [ ] Review Firebase costs
  - [ ] Review Supabase costs
  - [ ] Optimize if needed

## Phase 7: Async Media Generation (Optional)

For production with heavy usage:

- [ ] Create separate Cloud Run job for avatar generation
- [ ] Implement Cloud Tasks or Pub/Sub queue
- [ ] Update chat endpoint to return status polling URL
- [ ] Frontend polls for completion

## Production Checklist

- [ ] HTTPS enabled on all services
- [ ] CORS properly configured
- [ ] Secrets stored in Secret Manager (not .env)
- [ ] Database backups configured
- [ ] Error logging and monitoring active
- [ ] Rate limiting configured
- [ ] User data retention policy defined
- [ ] Privacy policy and ToS published
- [ ] GDPR compliance reviewed

## Rollback Procedure

If deployment fails:

### Backend Rollback
```bash
# Revert to previous Cloud Run revision
gcloud run services update-traffic mirrorself-api \
  --to-revision=$PREVIOUS_REVISION_ID \
  --region=us-central1
```

### Frontend Rollback
```bash
# Revert to previous Firebase deployment
firebase hosting:versions:list
firebase deploy --only hosting:mirrorself --version=$PREVIOUS_VERSION_ID
```

## Deployment Completed ✅

Once all items are checked:

1. ✅ Backend running on Cloud Run
2. ✅ Frontend running on Firebase App Hosting
3. ✅ Supabase configured with storage
4. ✅ Auth flow tested end-to-end
5. ✅ Onboarding tested
6. ✅ Chat tested with media generation
7. ✅ Monitoring and logging active
8. ✅ Domain configured with HTTPS

## Support Resources

- **Deployment Guides**:
  - [Cloud Run Deployment](./cloud-run-deployment.md)
  - [Firebase Deployment](./firebase-deployment.md)
  - [Main Deployment Plan](./deployment-firebase-cloudrun-supabase.md)

- **Official Docs**:
  - [Cloud Run Documentation](https://cloud.google.com/run/docs)
  - [Firebase App Hosting](https://firebase.google.com/docs/app-hosting)
  - [Supabase Guides](https://supabase.com/docs)

- **Monitoring**:
  - Cloud Run Metrics: https://console.cloud.google.com/run
  - Firebase Console: https://console.firebase.google.com
  - Supabase Dashboard: https://app.supabase.com
