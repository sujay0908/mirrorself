# 🚀 MirrorSelf Deployment - Complete Action Plan

## ✅ Completed Setup
- Firebase Project: `mirrorself-d6f1b` (initialized)
- Google Cloud Project: `project-14346235-d9f7-4d14-b72` (ready)
- Supabase Credentials: Collected
- All credentials gathered

---

## 📋 Next Immediate Steps (In Order)

### ⏳ Step 1: Install Google Cloud CLI (NOW)

**Why:** You need gcloud CLI to create secrets and deploy to Cloud Run

**Install:**
```powershell
# Option A: Download installer
(New-Object Net.WebClient).DownloadFile('https://dl.google.com/dl/cloudsdk/channels/rapid/GoogleCloudSDKInstaller.exe', "$env:TEMP\GoogleCloudSDKInstaller.exe")
& "$env:TEMP\GoogleCloudSDKInstaller.exe"

# Option B: Using Chocolatey (if installed)
choco install google-cloud-sdk
```

**After install, restart PowerShell and verify:**
```powershell
gcloud --version
gcloud auth login
gcloud config set project project-14346235-d9f7-4d14-b72
gcloud auth configure-docker
```

**Expected output:** `Google Cloud SDK [version]` and authentication success

---

### 📦 Step 2: Create Supabase Storage Buckets (Parallel)

**Where:** https://app.supabase.com → Your Project → Storage

**Create These 4 Buckets:**
1. ✅ `face-photos` (Private)
2. ✅ `voice-samples` (Private)
3. ✅ `voice-output` (Private)
4. ✅ `avatars` (Public)

**Instructions:**
- Click "New bucket"
- Enter name
- Choose privacy level
- Click "Create bucket"

---

### 🗄️ Step 3: Run Database Migration

**File:** [RUN_MIGRATION.md](RUN_MIGRATION.md)

**Quick version:**
```powershell
# Get your direct connection string from Supabase Settings
$env:DATABASE_URL = "postgresql://postgres:PASSWORD@aws-region.supabase.co:5432/postgres"

cd backend
python -m alembic upgrade head
```

**What it does:**
- Adds `supabase_user_id` column to users table
- Makes `hashed_password` nullable
- Creates index on `supabase_user_id`

---

### 🔐 Step 4: Create Google Cloud Secrets

**After gcloud is installed and authenticated:**

```powershell
$GCP_PROJECT = "project-14346235-d9f7-4d14-b72"
gcloud config set project $GCP_PROJECT

# Create each secret (you have these values)
echo "https://ihygwqrqkvkwlpzjrhdg.supabase.co" | gcloud secrets create supabase-url --data-file=-
echo "sb_publishable_JbcTkFomYiFfUsHosr5r1w_rZMrgEQq" | gcloud secrets create supabase-publishable-key --data-file=-
# [Continue for all secrets - see DEPLOYMENT_EXECUTION.md Phase 2]
```

**Secrets needed:**
1. `supabase-url`
2. `supabase-publishable-key`
3. `supabase-service-role-key`
4. `supabase-jwks-url`
5. `database-url`
6. `redis-url`
7. `anthropic-api-key`

---

### 🐳 Step 5: Build & Deploy Backend to Cloud Run

```powershell
$GCP_PROJECT = "project-14346235-d9f7-4d14-b72"
$REGION = "us-central1"
$SERVICE_NAME = "mirrorself-api"

# Build Docker image
docker build -t gcr.io/$GCP_PROJECT/$SERVICE_NAME:latest ./backend

# Push to Google Container Registry
docker push gcr.io/$GCP_PROJECT/$SERVICE_NAME:latest

# Deploy to Cloud Run
gcloud run deploy $SERVICE_NAME `
  --image gcr.io/$GCP_PROJECT/$SERVICE_NAME:latest `
  --region $REGION `
  --platform managed `
  --memory 2Gi `
  --cpu 2 `
  --timeout 300 `
  --allow-unauthenticated `
  --set-env-vars SUPABASE_URL=secret:supabase-url `
  --set-secrets SUPABASE_SERVICE_ROLE_KEY=supabase-service-role-key:latest

# Save the returned URL!
```

**Expected output:**
```
Service URL: https://mirrorself-api-xxxxx.run.app
```

---

### 🌐 Step 6: Deploy Frontend to Firebase

```powershell
cd frontend

# Build production version
npm run build

# Deploy
firebase deploy --token [YOUR_FIREBASE_TOKEN]
```

**Expected output:**
```
✔ Deploy complete!
Project Console: https://console.firebase.google.com/project/mirrorself-d6f1b
Hosting URL: https://mirrorself-d6f1b.web.app
```

---

### ✅ Step 7: Verify Everything Works

**Check backend health:**
```powershell
$BACKEND_URL = "https://mirrorself-api-xxxxx.run.app"
curl "$BACKEND_URL/health"
curl "$BACKEND_URL/health/ready"
```

**Check frontend:**
```powershell
start "https://mirrorself-d6f1b.web.app"
```

**Test full flow:**
1. Go to login page
2. Sign up with Supabase
3. Complete onboarding
4. Test chat

---

## 📚 Detailed Guides

- **[SETUP_GOOGLE_CLOUD.md](SETUP_GOOGLE_CLOUD.md)** — GCP CLI installation & setup
- **[RUN_MIGRATION.md](RUN_MIGRATION.md)** — Database migration guide
- **[DEPLOYMENT_EXECUTION.md](DEPLOYMENT_EXECUTION.md)** — Complete deployment checklist
- **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** — Architecture overview

---

## 🎯 Timeline Estimate

- Install GCloud: 10 min
- Create Supabase buckets: 5 min
- Run migration: 5 min
- Create secrets: 10 min
- Build & deploy backend: 15 min (includes build time)
- Deploy frontend: 5 min
- Verify: 5 min

**Total: ~55 minutes** (mostly waiting for builds)

---

## ⚠️ Common Issues & Fixes

### "gcloud: command not found"
- Install Google Cloud SDK (see SETUP_GOOGLE_CLOUD.md)
- Restart PowerShell after install

### "Connection refused" (database migration)
- Check Supabase project is running
- Use direct connection string (not pooler) for migration
- Verify password is correct

### "Docker push failed"
- Run `gcloud auth configure-docker`
- Ensure you're authenticated: `gcloud auth list`

### "403 Permission denied" (Cloud Run)
- Service account needs Secret Manager access
- Run: `gcloud projects add-iam-policy-binding $GCP_PROJECT --member=serviceAccount:$SERVICE_ACCOUNT --role=roles/secretmanager.secretAccessor`

---

## 🚦 Go/No-Go Checklist

Before starting deployment, confirm:

- [ ] Supabase project created
- [ ] Supabase storage buckets created
- [ ] Database migration completed
- [ ] Google Cloud CLI installed and authenticated
- [ ] GCP secrets created
- [ ] Firebase CLI authenticated
- [ ] Docker installed and working
- [ ] All 7 credentials available

---

## 🎉 Next Phase: Production Setup

After deployment verification:
1. Configure custom domain (optional)
2. Set up monitoring & logging
3. Configure backups
4. Optional: Deploy async worker for media generation

---

## 🆘 Need Help?

If you get stuck:
1. Check the detailed guide for your step
2. Review error messages in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) troubleshooting
3. Verify all credentials are correct
4. Check that prerequisites are met for each phase

**Let's get started! 🚀**

---

**Current Status:** Ready to proceed with Step 1 (Install Google Cloud CLI)
