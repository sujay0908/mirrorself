# Firebase App Hosting Deployment Guide for MirrorSelf Frontend

This guide walks through deploying the MirrorSelf Next.js frontend to Firebase App Hosting.

## Prerequisites

### 1. Firebase Project
```bash
# Install Firebase CLI
npm install -g firebase-tools

# Login to Firebase
firebase login

# List your Firebase projects
firebase projects:list

# Create a new Firebase project if needed
# (via https://console.firebase.google.com)
```

### 2. Google Cloud Project with Blaze Plan
Firebase App Hosting requires:
- Firebase Blaze (paid) plan
- Linked Google Cloud project
- Cloud Run API enabled (done automatically)

### 3. Supabase Project
- Frontend Auth configured
- Publishable key available

### 4. Backend Cloud Run Service
- Deployed and running
- Service URL available (e.g., `https://mirrorself-api-xxx.run.app`)

## Step 1: Setup Firebase Project

### Create or select Firebase project

```bash
export FIREBASE_PROJECT_ID="your-firebase-project"

# If you need to create one:
firebase projects:create mirrorself --display-name "MirrorSelf"

# Set as default
firebase use $FIREBASE_PROJECT_ID
```

### Enable required APIs

```bash
gcloud services enable \
  firebasehosting.googleapis.com \
  cloudbuild.googleapis.com \
  cloudrun.googleapis.com \
  artifactregistry.googleapis.com
```

## Step 2: Configure GitHub Repository

Firebase App Hosting deploys directly from GitHub.

### Connect Repository

1. Go to [Firebase Console](https://console.firebase.google.com)
2. Select your project
3. Click **Build** → **App Hosting**
4. Click **Get started**
5. Click **Authorize with GitHub**
6. Select repository: `sujay0908/mirrorself`
7. Click **Connect**

### Configure Deployment Settings

1. **Branch**: Select `main` (or your deployment branch)
2. **Root directory**: `frontend/`
3. **Build command**: `npm run build`
4. **Output directory**: `.next`

## Step 3: Set Environment Variables in Firebase

### Add Backend URL

In the App Hosting settings, add environment variables:

```env
# Available to browser AND server-side (Next.js route handlers)
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=your-publishable-key
NEXT_PUBLIC_API_BASE=/api

# Server-side only (route handlers)
API_INTERNAL_URL=https://mirrorself-api-xxx.run.app/api
```

### Store Secrets

1. Go to **App Hosting** → **Environment** tab
2. Add environment variables:
   - `NEXT_PUBLIC_SUPABASE_URL`: Your Supabase project URL
   - `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`: From Supabase Settings
   - `API_INTERNAL_URL`: Your Cloud Run backend URL
   - `NEXT_PUBLIC_API_BASE`: `/api` (proxy path)

Example:
```
NEXT_PUBLIC_SUPABASE_URL = https://ihygwqrqkvkwlpzjrhdg.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY = sb_publishable_JbcTkFomYiFfUsHosr5r1w_rZMrgEQq
API_INTERNAL_URL = https://mirrorself-api-abc123.run.app/api
NEXT_PUBLIC_API_BASE = /api
```

## Step 4: Configure Supabase Auth Redirects

After you have your Firebase URL, configure Supabase redirects:

1. Go to Supabase Dashboard → **Authentication** → **URL Configuration**
2. Add redirect URLs:
   - Site URL: `https://your-firebase-domain.com` (e.g., `https://app.example.com`)
   - Redirect URLs:
     - `https://your-firebase-domain.com/**`
     - `https://your-firebase-domain.com/auth/callback` (optional)
     - `http://localhost:3000` (for local dev)

3. Update CORS in backend API settings:
   ```
   https://your-firebase-domain.com
   ```

## Step 5: Configure Custom Domain (Optional)

### Attach Your Domain

1. Go to Firebase Console → **App Hosting**
2. Click **Custom domains**
3. Click **Add custom domain**
4. Enter your domain (e.g., `app.example.com`)
5. Follow DNS setup instructions for your registrar

### DNS Records

Firebase will provide specific NS records or A records to add to your domain registrar.

Example (using Google Domains or Cloudflare):
- **Type**: CNAME
- **Name**: `app`
- **Value**: `firebaseapp-<project-id>.web.app`

## Step 6: Deploy Frontend

### Automatic Deployment

GitHub commits to `main` automatically trigger deployments via Firebase App Hosting.

### Manual Deployment

```bash
cd frontend

# Build locally
npm run build

# Deploy
firebase deploy --only hosting
```

### Check Deployment Status

```bash
# View recent deployments
firebase hosting:channel:list

# View build logs
firebase functions:log
```

## Step 7: Verify Deployment

### Test Auth Flow

1. Visit your frontend URL
2. Click **Create account** or **Log in**
3. Enter credentials
4. Should redirect to Supabase Auth
5. After auth, should call `/api/v1/auth/bootstrap`

### Test Chat Flow

1. Complete onboarding (upload face, voice)
2. Go to Chat page
3. Send message
4. Backend should generate response with audio/video

### Check Logs

```bash
# Firebase build logs
firebase hosting:log

# Cloud Function logs (for route handlers)
gcloud functions logs read --region us-central1 --limit 50
```

## Environment Variables Reference

| Variable | Type | Purpose | Example |
|----------|------|---------|---------|
| `NEXT_PUBLIC_SUPABASE_URL` | Public | Supabase project URL | `https://project.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Public | Supabase auth key | `sb_publishable_...` |
| `NEXT_PUBLIC_API_BASE` | Public | Frontend API proxy path | `/api` |
| `API_INTERNAL_URL` | Secret | Backend URL for route handlers | `https://api.run.app/api` |

## Troubleshooting

### Build Fails on Deploy

Check Firebase build logs:
```bash
firebase hosting:channel:list
```

Common issues:
- **TypeScript errors**: Run `npm run typecheck` locally
- **Missing dependencies**: Ensure `package.json` has all imports
- **Build script fails**: Test locally with `npm run build`

### Route handler can't reach backend

Test from your browser console:
```javascript
fetch('/api/v1/auth/me', {
  headers: { 'Authorization': 'Bearer your-token' }
})
```

If 404, check:
- `API_INTERNAL_URL` environment variable is set correctly
- Backend service is running and accessible
- CORS configured on backend

### Supabase Auth Redirect Fails

Check Supabase → **Authentication** → **URL Configuration**:
- Site URL matches your Firebase domain
- Redirect URLs include `**` wildcard
- No typos in domain

### Slow Deployments

App Hosting build times are usually 2-5 minutes. Check:
- No large node_modules dependencies
- Next.js cache strategy: `.next/` should be reused
- Parallel builds in Cloud Build settings

## Scaling and Cost

### Firebase App Hosting Pricing
- **First 180 build minutes/month**: Free
- **Build minutes**: $0.005 per minute
- **Hosting storage**: Pay-per-GB
- **Cloud Functions** (route handlers): See Cloud Run pricing

### Optimize Costs
- Reduce deployment frequency
- Use efficient builds (incremental)
- Cache dependencies
- Minimize bundle size with Next.js optimizations

## Next Steps

1. ✅ Backend deployed to Cloud Run
2. ✅ Frontend deployed to Firebase App Hosting
3. ⏭️ Optional: Setup async media generation worker
4. ⏭️ Optional: Setup monitoring and alerts

## Monitoring

### Set Up Alerts

1. Go to **App Hosting** → **Metrics**
2. Monitor:
   - Build success/failure rate
   - Deployment duration
   - Frontend performance metrics

### View Logs

```bash
# Recent deployments
firebase history:list

# Specific deployment logs
firebase hosting:log
```

## Additional Resources

- [Firebase App Hosting Docs](https://firebase.google.com/docs/app-hosting)
- [Firebase CLI Reference](https://firebase.google.com/docs/cli)
- [Next.js on Firebase](https://nextjs.org/docs/deployment)
- [Cloud Run Pricing](https://cloud.google.com/run/pricing)
- [Supabase Auth Documentation](https://supabase.com/docs/guides/auth)
