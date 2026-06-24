# Google Cloud Setup Instructions

## Step 1: Install Google Cloud CLI

### Windows Installation

1. Download installer:
   ```powershell
   (New-Object Net.WebClient).DownloadFile('https://dl.google.com/dl/cloudsdk/channels/rapid/GoogleCloudSDKInstaller.exe', "$env:TEMP\GoogleCloudSDKInstaller.exe")
   & "$env:TEMP\GoogleCloudSDKInstaller.exe"
   ```

2. Follow the installer wizard (default settings are fine)

3. Open a new PowerShell terminal and verify:
   ```powershell
   gcloud --version
   ```

Alternatively, use Chocolatey:
```powershell
choco install google-cloud-sdk
```

Or download directly from: https://cloud.google.com/sdk/docs/install-sdk

## Step 2: Authenticate with Google Cloud

```powershell
gcloud auth login
```

This will open a browser window. Sign in with your Google account.

## Step 3: Configure Project

```powershell
gcloud config set project project-14346235-d9f7-4d14-b72
gcloud config list
```

You should see:
```
[core]
project = project-14346235-d9f7-4d14-b72
```

## Step 4: Configure Docker Authentication

```powershell
gcloud auth configure-docker
```

## Step 5: Verify Setup

```powershell
# Check project details
gcloud projects describe project-14346235-d9f7-4d14-b72

# List available services
gcloud services list --available
```

## Next Steps

Once installed, proceed with:
1. Creating Cloud Run secrets
2. Building and pushing Docker image
3. Deploying to Cloud Run

See: [DEPLOYMENT_EXECUTION.md](DEPLOYMENT_EXECUTION.md) Phase 2 onwards
