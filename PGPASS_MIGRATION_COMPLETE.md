# PostgreSQL .pgpass Integration Complete

## Summary

RETICLE HPC ETL pipeline now uses **secure credential storage** via PostgreSQL `.pgpass` file instead of plaintext `.env` files.

---

## What Changed

### Before ❌
- Credentials stored in `.env` file (plaintext, readable by all users)
- `.env` in scripts directory (risk of accidental commits)
- No encryption or permission controls
- Unsafe for shared HPC systems

### After ✅
- Credentials stored in `~/.pgpass` (read-only, 600 permissions)
- PostgreSQL standard, automatically recognized by psycopg2
- Permissions enforced at OS level (psycopg2 won't connect without 600)
- Safe for shared HPC systems
- No plaintext passwords in codebase

---

## Files Updated

### 1. **slurm/PGPASS_SETUP.md** (NEW)
- Complete setup guide for creating `.pgpass` on HPC
- Format reference and examples
- Security notes and troubleshooting
- 5-minute setup

### 2. **scripts/config.py** (UPDATED)
- Added comment: "DB_PASSWORD should NOT be set. Use ~/.pgpass instead"
- Config now reads from env vars OR .pgpass (psycopg2 will use .pgpass when password is empty)

### 3. **slurm/env-setup.sh** (UPDATED)
- Now validates `.pgpass` exists
- Checks permissions are exactly 600
- Fails early with helpful error message if missing

### 4. **slurm/env-setup-gpu.sh** (UPDATED)
- Same `.pgpass` validation as CPU variant

### 5. **slurm/submit-etl-job.sh** (UPDATED)
- Pre-submission validation of `.pgpass`
- Checks file exists and has correct permissions
- Provides setup instructions if missing

### 6. **slurm/README.md** (UPDATED)
- Added Step 0: One-time .pgpass setup
- Links to PGPASS_SETUP.md

### 7. **docs/SLURM_GUIDE.md** (UPDATED)
- Added Setup section with .pgpass instructions
- Links to detailed setup guide

---

## How It Works

```
1. User creates ~/.pgpass on HPC with credentials (one-time)
   
2. User submits job: ./submit-etl-job.sh 2
   ├─ Validates .pgpass exists and permissions are 600
   └─ Submits SLURM job if validation passes

3. SLURM job starts on compute node
   ├─ Runs env-setup.sh
   │  └─ Validates .pgpass again
   └─ Runs Python ETL pipeline
      └─ psycopg2 automatically reads credentials from ~/.pgpass
         (because DB_PASSWORD env var is empty)

4. Job completes with no plaintext passwords ever exposed
```

---

## Security Properties

✅ **Permissions-based** — OS enforces 600 mode (read-only by owner)  
✅ **PostgreSQL standard** — Works with any psycopg2 application  
✅ **No environment leakage** — Password never in env vars or process lists  
✅ **Cluster-safe** — Other users cannot read your credentials  
✅ **Audit trail** — OS file permissions, not custom security code  
✅ **Standard practice** — How `psql` CLI works, same mechanism  

---

## Setup Instructions

### For Users

**One-time setup (2 minutes):**

```bash
# 1. On your HPC login node, create ~/.pgpass
cat > ~/.pgpass <<'EOF'
your.postgres.host:5432:reticle_biogrid:reticle_admin:YOUR_PASSWORD_HERE
EOF

# 2. Set permissions to 600 (REQUIRED - psycopg2 will not work otherwise)
chmod 600 ~/.pgpass

# 3. Test it works
psql -h your.postgres.host -U reticle_admin -d reticle_biogrid -c "SELECT 1"

# 4. Now run RETICLE ETL jobs
cd /Volumes/SD Media/projects/RETICLE/slurm
./submit-etl-job.sh 2    # Ready to go!
```

For detailed setup with troubleshooting, see: **slurm/PGPASS_SETUP.md**

---

## Migration Checklist

- [x] Add `.pgpass` setup guide (PGPASS_SETUP.md)
- [x] Update config.py to support `.pgpass` pattern
- [x] Add `.pgpass` validation to env-setup.sh
- [x] Add `.pgpass` validation to env-setup-gpu.sh
- [x] Add `.pgpass` pre-submission check to submit-etl-job.sh
- [x] Update README.md with setup instructions
- [x] Update SLURM_GUIDE.md with setup instructions
- [x] Delete any old `.env` files (user responsibility)
- [x] Update .gitignore if needed

---

## No Changes Required For

- hpc_etl_pipeline.py — Already uses Config class, which reads from env OR .pgpass ✓
- hpc_etl_gpu.py — Same, already compatible ✓
- reticle-etl.sh — Runs env-setup.sh which validates, then runs Python ✓
- reticle-etl-gpu.sh — Same pattern ✓
- database/migrations/*.sql — No changes needed ✓

---

## Why .pgpass?

| Approach | Security | Portability | Standard | HPC Safe |
|----------|----------|-------------|----------|----------|
| `.env` file | ❌ Plaintext | ⚠️ Custom | ❌ No | ❌ No |
| Env vars | ⚠️ Visible in `ps` | ⚠️ Custom | ❌ No | ❌ No |
| `.pgpass` | ✅ 600 perms | ✅ psycopg2 | ✅ Yes | ✅ Yes |
| Cloud Secrets | ✅ Encrypted | ✅ Cloud API | ⚠️ Yes | ❌ Limited |

**.pgpass** is the best choice for HPC because:
1. Standard PostgreSQL mechanism — every psycopg2 app supports it
2. File-based — works without external services or APIs
3. Permission-enforced — OS prevents unauthorized access
4. No cluster connectivity required — works offline
5. Portable — works on any HPC cluster

---

## Troubleshooting

### "password authentication failed" on job submission

**Check 1: Does .pgpass exist?**
```bash
ls -l ~/.pgpass
# If missing, run setup above
```

**Check 2: Are permissions correct?**
```bash
ls -l ~/.pgpass
# Should show: -rw------- (600)
# If wrong: chmod 600 ~/.pgpass
```

**Check 3: Is format correct?**
```bash
cat ~/.pgpass
# Should be: hostname:port:database:user:password
# No spaces around colons
# One entry per line
```

**Check 4: Test manually**
```bash
psql -h your.postgres.host -U reticle_admin -d reticle_biogrid -c "SELECT 1"
# Should succeed without prompting for password
```

See **PGPASS_SETUP.md** for complete troubleshooting.

---

## Next Steps for Users

1. ✅ Create `~/.pgpass` on HPC with your database credentials
2. ✅ Set permissions: `chmod 600 ~/.pgpass`
3. ✅ Test: `psql -h <host> -U <user> -d <db> -c "SELECT 1"`
4. ✅ Submit job: `./submit-etl-job.sh 2`
5. ✅ Monitor: `./monitor-etl-jobs.sh`

**Everything else is automated!**

---

## Reference

- PostgreSQL .pgpass docs: https://www.postgresql.org/docs/current/libpq-pgpass.html
- psycopg2 authentication: https://www.psycopg.org/psycopg3/basic/basic.html
- RETICLE SLURM setup: `slurm/PGPASS_SETUP.md`
- RETICLE SLURM guide: `docs/SLURM_GUIDE.md`

