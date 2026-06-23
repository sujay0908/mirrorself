# MirrorSelf Deployment Documentation

Complete guides for deploying MirrorSelf to production.

## Quick Start

1. **Read the main deployment plan**: [deployment-firebase-cloudrun-supabase.md](./deployment-firebase-cloudrun-supabase.md)
2. **Follow the checklist**: [deployment-checklist.md](./deployment-checklist.md)
3. **Deploy backend**: [cloud-run-deployment.md](./cloud-run-deployment.md)
4. **Deploy frontend**: [firebase-deployment.md](./firebase-deployment.md)

## Documentation

### [Deployment Plan](./deployment-firebase-cloudrun-supabase.md)
**Comprehensive architecture and strategy for production deployment**

- Target stack overview
- Why each service (Firebase, Cloud Run, Supabase, Redis)
- Current gaps in codebase (auth, storage, URLs)
- Detailed refactoring guide
- Migration steps and implementation order
- Risks and mitigations

**Read this first** to understand the overall approach.

### [Deployment Checklist](./deployment-checklist.md)
**Step-by-step checklist for deployment**

- Phase 0: Prerequisites
- Phase 1: Infrastructure setup
- Phase 2: Backend deployment
- Phase 3: Frontend deployment
- Phase 4: Supabase configuration
- Phase 5: Testing
- Phase 6: Monitoring
- Phase 7: Optional async worker

**Use this to track progress** through each phase.

### [Cloud Run Backend Deployment](./cloud-run-deployment.md)
**Detailed guide for deploying FastAPI backend to Google Cloud Run**

- Prerequisites and GCP setup
- Creating Supabase storage buckets
- Storing secrets in Secret Manager
- Deployment script usage
- Verification and testing
- Scaling configuration
- Troubleshooting

**Use this when deploying the backend.**

### [Firebase Frontend Deployment](./firebase-deployment.md)
**Detailed guide for deploying Next.js frontend to Firebase App Hosting**

- Firebase project setup
- GitHub repository configuration
- Environment variables
- Supabase auth redirects
- Custom domain setup
- Deployment process
- Verification and testing
- Troubleshooting

**Use this when deploying the frontend.**

## Architecture Overview

```
Browser
  ↓
Firebase App Hosting (Next.js)
  ├─ /api/... → Cloud Run
  ├─ Supabase Auth
  └─ Static assets

Cloud Run (FastAPI)
  ├─ Supabase Auth JWT verification
  ├─ Supabase Postgres
  ├─ Supabase Storage
  └─ Redis (Upstash)

Supabase
  ├─ Auth
  ├─ Postgres Database
  └─ Storage (face-photos, voice-samples, voice-output, avatars)

External Services
  ├─ Anthropic Claude API
  └─ Upstash Redis
```

## Phase-by-Phase Summary

### Phase 1: Auth Migration ✅
- Backend JWT verification with Supabase
- Frontend auth pages with Supabase
- Bootstrap endpoint for profile sync
- Status: **COMPLETE**

### Phase 2: Storage Migration ✅
- Storage service abstraction
- Upload to Supabase Storage
- Generate signed/public URLs
- Status: **COMPLETE**

### Phase 3: Backend Deployment
- Create Supabase storage buckets
- Create Cloud Run secrets
- Deploy to Cloud Run
- Verify health endpoints
- Status: **IN PROGRESS** → See [cloud-run-deployment.md](./cloud-run-deployment.md)

### Phase 4: Frontend Deployment
- Configure Firebase
- Deploy to App Hosting
- Setup custom domain
- Status: **NEXT** → See [firebase-deployment.md](./firebase-deployment.md)

### Phase 5: Optional Async Worker
- Create Cloud Run job for avatar generation
- Setup Cloud Tasks queue
- Frontend polling for status
- Status: **OPTIONAL** for Phase 1

## Key Configuration Values

Before deploying, gather these values:

| Value | Where to Get | Purpose |
|-------|-------------|---------|
| GCP Project ID | Google Cloud Console | Cloud Run deployment target |
| Firebase Project ID | Firebase Console | Frontend deployment target |
| Supabase URL | Supabase Settings | Backend + Frontend config |
| Supabase Service Role Key | Supabase Settings > API | Backend server auth |
| Supabase Publishable Key | Supabase Settings > API | Frontend auth |
| Database URL (Pooler) | Supabase Database > Connection | Backend runtime connection |
| Redis URL | Upstash Dashboard | Backend memory service |
| Anthropic API Key | Anthropic Console | LLM generation |
| Custom Domain | Your registrar | Frontend + auth configuration |

## Deployment Scripts

### Linux/Mac

```bash
# Deploy backend to Cloud Run
export GCP_PROJECT_ID="your-project"
export SERVICE_REGION="us-central1"
bash scripts/deploy-cloud-run.sh

# Deploy frontend to Firebase
firebase deploy --only hosting
```

### Windows PowerShell

```powershell
# Deploy backend to Cloud Run
$env:GCP_PROJECT_ID = "your-project"
$env:SERVICE_REGION = "us-central1"
.\scripts\deploy-cloud-run.ps1

# Deploy frontend to Firebase
firebase deploy --only hosting
```

## Troubleshooting

### Backend Issues

- **Cloud Run deployment fails**: Check Docker build succeeds locally
- **Health endpoint returns 503**: Verify database and Redis connectivity
- **Supabase auth fails**: Check JWT secret is configured
- **Storage uploads fail**: Verify service account has Storage access

See [cloud-run-deployment.md#troubleshooting](./cloud-run-deployment.md#troubleshooting)

### Frontend Issues

- **Build fails on Firebase**: Check TypeScript compiles locally
- **Route handler can't reach backend**: Verify `API_INTERNAL_URL` environment variable
- **Auth redirect fails**: Check Supabase URL Configuration includes Firebase domain
- **Slow deployments**: Check build command and dependencies

See [firebase-deployment.md#troubleshooting](./firebase-deployment.md#troubleshooting)

## Cost Estimates

### Monthly Costs (Approximate)

| Service | Usage | Cost |
|---------|-------|------|
| Cloud Run | 100K requests/month, 1 min instances | $30-50 |
| Firebase | 50 deployments/month, 1GB storage | $10-20 |
| Supabase | 100GB storage, transaction pooler | $50-100 |
| Upstash Redis | 100GB throughput/month | $20-30 |
| Anthropic | 100K tokens/day | $30-50 |
| **Total** | | **$140-250** |

Costs scale linearly with traffic. Optimize by:
- Using Cloud Run minimum instances = 0 for low traffic
- Reducing media generation frequency
- Caching responses
- Using Supabase free tier if < 5GB data

## Support

For issues or questions:
1. Check relevant deployment guide troubleshooting section
2. Review deployment checklist to verify all steps
3. Check application logs in Cloud Run / Firebase
4. Consult official documentation links in guides

## Production Readiness

Before going live:
- [ ] HTTPS enabled (automatic)
- [ ] CORS configured correctly
- [ ] Secrets in Secret Manager (not .env)
- [ ] Error monitoring active
- [ ] Database backups configured
- [ ] Rate limiting enabled (optional)
- [ ] User data retention policy defined
- [ ] Privacy policy published

## Next Steps

1. **Start**: Read [deployment-firebase-cloudrun-supabase.md](./deployment-firebase-cloudrun-supabase.md)
2. **Plan**: Use [deployment-checklist.md](./deployment-checklist.md)
3. **Deploy Backend**: Follow [cloud-run-deployment.md](./cloud-run-deployment.md)
4. **Deploy Frontend**: Follow [firebase-deployment.md](./firebase-deployment.md)
5. **Test**: Verify all flows work end-to-end
6. **Monitor**: Setup alerts and dashboards

---

**Last Updated**: 2026-06-23
**Status**: Phase 3 in progress
