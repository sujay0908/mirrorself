# Run Supabase Database Migration

## Prerequisites

1. Your Supabase project is created
2. You have the direct database connection string (for migrations, not pooler)
3. Python is installed on your system

## What This Migration Does

The migration `0002_supabase_auth.py` adds:
- `supabase_user_id` column (String, unique, indexed)
- Makes `hashed_password` nullable (for future migration from custom auth)

## Running the Migration

### Step 1: Get Your Direct Database Connection String

From Supabase:
1. Go to https://app.supabase.com → Your Project → Project Settings → Database
2. Copy the connection string under "Connection Pooler" → "Connection String"
   - Format: `postgresql://postgres:password@aws-region.pooler.supabase.com:6543/postgres`

### Step 2: Set Environment Variable

```powershell
# Replace with your actual connection string
$env:DATABASE_URL = "postgresql://postgres:YOUR_PASSWORD@aws-region.pooler.supabase.com:6543/postgres"

# For Windows, you can also use the direct connection (not pooler):
# postgresql://postgres:PASSWORD@aws-region.supabase.co:5432/postgres
```

### Step 3: Run Migration

From project root:

```powershell
cd backend

# Option A: Using Python directly
ech

# Option B: Using the migration script (if available)
python migrate.py

# Option C: Using Docker
docker-compose exec backend alembic upgrade head
```

### Step 4: Verify Migration

```powershell
# Connect to database and check schema
psql "your-connection-string" -c "\d users"
```

You should see:
```
 supabase_user_id | character varying(255) | | | 
 hashed_password  | character varying(255) | | | 
```

## Expected Output

```
INFO [alembic.runtime.migration] Running upgrade 0001_initial -> 0002_supabase_auth, add supabase auth linkage
INFO [alembic.runtime.migration] Done.
```

## Troubleshooting

### Connection Error
```
psycopg2.OperationalError: could not connect to server
```

**Solution:**
- Verify connection string is correct
- Check if Supabase project is running (sometimes goes to sleep)
- Try the direct connection instead of pooler

### Permission Denied
```
permission denied for schema public
```

**Solution:**
- Use the postgres superuser account for migrations
- In Supabase, use the same credentials you used to create the project

### Already Migrated
```
Target database is not up to date.
```

**Solution:**
Check current migration:
```powershell
python -m alembic current
```

To see all migrations:
```powershell
python -m alembic history
```

## Next Steps

Once migration succeeds:
1. ✅ Database schema updated
2. Continue with Cloud Run deployment (see DEPLOYMENT_EXECUTION.md Phase 2)
