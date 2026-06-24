# IMMEDIATE ACTION ITEMS - Follow in Order

## 📌 Current Status
✅ Firebase Project: mirrorself-d6f1b (configured)
✅ Google Cloud Project: project-14346235-d9f7-4d14-b72 (ready)
✅ Supabase Credentials: Collected
✅ All preparation complete

**Time to deployment: ~1 hour**

---

## 🎯 DO THIS RIGHT NOW

### Action 1: Install Google Cloud CLI (10 minutes)

**STOP here and install gcloud CLI first.**

Option A (Recommended - Automatic):
```powershell
# Copy and paste this entire block into PowerShell (as administrator):
$ProgressPreference = 'SilentlyContinue'
(New-Object Net.WebClient).DownloadFile('https://dl.google.com/dl/cloudsdk/channels/rapid/GoogleCloudSDKInstaller.exe', "$env:TEMP\GoogleCloudSDKInstaller.exe")
& "$env:TEMP\GoogleCloudSDKInstaller.exe"
```

Option B (Manual):
1. Go to https://cloud.google.com/sdk/docs/install
2. Download `GoogleCloudSDKInstaller.exe`
3. Run the installer
4. Accept defaults, click "Next" through the wizard

**After install, restart PowerShell and verify:**
```powershell
gcloud --version
gcloud auth login
```

---

### Action 2: Authenticate with Google (5 minutes)

```powershell
# This opens a browser to authenticate
gcloud auth login

# Set your project
gcloud config set project project-14346235-d9f7-4d14-b72

# Verify configuration
gcloud config list
```

Expected output:
```
[core]
project = project-14346235-d9f7-4d14-b72
```

---

### Action 3: Create Supabase Storage Buckets (5 minutes)

Go to: https://app.supabase.com → Your Project → Storage

**Create 4 buckets:**

1. **New bucket** button → `face-photos` → Private
2. **New bucket** button → `voice-samples` → Private  
3. **New bucket** button → `voice-output` → Private
4. **New bucket** button → `avatars` → Public

---

### Action 4: Run Database Migration (5 minutes)

```powershell
# Get your Supabase direct connection from:
# https://app.supabase.com → Project Settings → Database → Connection Pooler

# For Windows use the CONNECTION STRING (not pooler)
# Format: postgresql://postgres:PASSWORD@aws-region.supabase.co:5432/postgres

# Set environment variable (replace with your actual connection)
$env:DATABASE_URL = "postgresql://postgres:YOUR_PASSWORD@aws-region.supabase.co:5432/postgres"
$env:DATABASE_URL = 'postgresql://postgres:Sujaygodugu@0908@db.ihygwqrqkvkwlpzjrhdg.supabase.co:5432/postgres'
$env:DATABASE_URL="postgresql+asyncpg://postgres:Sujaygodugu@0908@db.ihygwqrqkvkwlpzjrhdg.supabase.co:5432/postgres"

db.ihygwqrqkvkwlpzjrhdg.supabase.co
# Run migration
cd c:\Users\sujay\Downloads\mirror-self-ai\mirrorself\backend
python -m alembic upgrade head
```

**Expected output:**
```
INFO [alembic.runtime.migration] Running upgrade 0001_initial -> 0002_supabase_auth
INFO [alembic.runtime.migration] Done.
```

---

### Action 5: Create Google Cloud Secrets (10 minutes)

```powershell
# Set environment variables with YOUR credentials:
$env:SUPABASE_URL = "https://ihygwqrqkvkwlpzjrhdg.supabase.co"
$env:SUPABASE_PUBLISHABLE_KEY = "sb_publishable_JbcTkFomYiFfUsHosr5r1w_rZMrgEQq"
$env:SUPABASE_SERVICE_ROLE_KEY = "[paste your service role key]"
$env:SUPABASE_JWKS_URL = "https://ihygwqrqkvkwlpzjrhdg.supabase.co/auth/v1/.well-known/jwks.json"
$env:DATABASE_URL = "[paste your pooler connection string]"
$env:REDIS_URL = "redis://default:gQAAAAAAAaTTAAIgcDEzMjJhNDE5ZGE3OGM0MzgxYjcxMGIwMTk4MmJjMmRjOA@immortal-hagfish-107731.upstash.io:6379"
$env:ANTHROPIC_API_KEY = "sk-ant-test-12345"

# Authenticate Docker
gcloud auth configure-docker --quiet

# Run the secret creation script
cd c:\Users\sujay\Downloads\mirror-self-ai\mirrorself
& .\scripts\create-secrets.ps1
```

**Expected output:**
```
Created/Updated: 7
Failed: 0
✅ All secrets created successfully!
```

---

### Action 6: Deploy Backend to Cloud Run (15 minutes)

```powershell
cd c:\Users\sujay\Downloads\mirror-self-ai\mirrorself

# Run the deployment script
& .\scripts\deploy-cloud-run-windows.ps1

# This will:
# - Build Docker image
# - Push to Google Container Registry  
# - Deploy to Cloud Run
# - Verify health check
```

**Expected output:**
```
🚀 Deploying MirrorSelf Backend to Cloud Run
✅ Build complete
✅ Push complete
✅ Deployment complete!
🌐 Service URL: https://mirrorself-api-xxxxx.run.app
```

**IMPORTANT: Save the Service URL!** You'll need it for Firebase deployment.

---

### Action 7: Update Frontend Environment

Create/update `frontend/.env.production`:

```env
NEXT_PUBLIC_SUPABASE_URL=https://ihygwqrqkvkwlpzjrhdg.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publicable_JbcTkFomYiFfUsHosr5r1w_rZMrgEQq
NEXT_PUBLIC_API_BASE=/api
API_INTERNAL_URL=https://mirrorself-api-xxxxx.run.app/api
```

⚠️ Replace `mirrorself-api-xxxxx.run.app` with your actual Cloud Run URL!

---

### Action 8: Deploy Frontend to Firebase (5 minutes)

```powershell
cd c:\Users\sujay\Downloads\mirror-self-ai\mirrorself\frontend

# Build production version
npm run build

# Deploy to Firebase
firebase deploy
```

**Expected output:**
```
✔ Deploy complete!
✔ Hosting URL: https://mirrorself-d6f1b.web.app
```

---

### Action 9: Verify Everything Works (5 minutes)

**Test backend health:**
```powershell
$BACKEND = "https://mirrorself-api-xxxxx.run.app"
curl "$BACKEND/health"
curl "$BACKEND/health/ready"
```

**Test frontend:**
```powershell
start "https://mirrorself-d6f1b.web.app"
```

**In your browser:**
1. Go to login page
2. Create new account (sign up)
3. Complete onboarding (upload face photo, voice)
4. Test chat functionality

---

## ⏱️ Timeline

| Step | Time | Status |
|------|------|--------|
| Install gcloud | 10 min | ⏳ NOW |
| Authenticate | 5 min | Next |
| Create Supabase buckets | 5 min | Next |
| Run migration | 5 min | Next |
| Create secrets | 10 min | Next |
| Deploy backend | 15 min | Next |
| Update frontend | 2 min | Next |
| Deploy frontend | 5 min | Next |
| Verify | 5 min | Final |
| **TOTAL** | **~60 min** | Go! |

---

## ⚠️ Important Notes

1. **Save all URLs** - You'll need them for connecting services
2. **Keep secrets safe** - Don't commit .env files to git
3. **Check firewall** - Make sure Cloud Run can be accessed
4. **Monitor costs** - Cloud Run charges for requests, but free tier is generous

---

## 🆘 Common Issues

### "gcloud: command not found"
→ Install Google Cloud SDK (Option A above), restart PowerShell

### "Docker build failed"
→ Make sure Docker Desktop is running: `docker ps`

### "Permission denied" on secrets
→ Run: `gcloud auth configure-docker --quiet`

### "Health check failed"
→ Wait 30 seconds for Cloud Run to initialize, try again

### "Connection refused" on database
→ Use direct connection string (not pooler), verify Supabase project is running

---

## ✅ Checklist Before Starting

- [ ] Google Cloud SDK will be installed
- [ ] Have your Supabase credentials ready
- [ ] Have your Anthropic API key ready
- [ ] Have your Redis URL ready
- [ ] Docker Desktop is installed and running
- [ ] ~60 minutes of time available
- [ ] Reasonable internet connection (Docker builds are large)

---

## 🚀 Ready?

**Start with Action 1: Install Google Cloud CLI**

Once installed, proceed through actions 2-9 in order.

Each action takes 5-15 minutes. You'll have a production deployment running in about an hour!

---

## 📚 Reference Documents

- [DEPLOYMENT_START_HERE.md](DEPLOYMENT_START_HERE.md) - Overview
- [SETUP_GOOGLE_CLOUD.md](SETUP_GOOGLE_CLOUD.md) - Detailed GCP setup
- [RUN_MIGRATION.md](RUN_MIGRATION.md) - Database migration help
- [DEPLOYMENT_EXECUTION.md](DEPLOYMENT_EXECUTION.md) - Detailed checklist
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) - Architecture overview

---

**Go ahead! Install Google Cloud CLI and reply when done. 🚀**
