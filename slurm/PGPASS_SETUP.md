# PostgreSQL .pgpass Setup for RETICLE HPC

Use `.pgpass` for secure credential storage on HPC clusters. No plaintext passwords in files or environment.

## Quick Setup (3 Steps)

### Step 1: Create ~/.pgpass on HPC Login Node

```bash
# On your HPC login node
cat > ~/.pgpass <<'EOF'
your.postgres.host:5432:reticle_biogrid:reticle_admin:YOUR_PASSWORD_HERE
EOF

# Make it readable only by you (REQUIRED - pgpass won't work otherwise)
chmod 600 ~/.pgpass

# Verify
ls -l ~/.pgpass
# Should show: -rw------- (600)
```

### Step 2: Test Connection

```bash
# Test that psycopg2 can read credentials from .pgpass
psql -h your.postgres.host -U reticle_admin -d reticle_biogrid -c "SELECT 1"

# If successful, you'll see: ?column?
#                              1
# (1 row)
```

### Step 3: No Changes Needed to RETICLE Scripts

The ETL pipeline automatically uses `.pgpass` when credentials are available:

```bash
cd /Volumes/SD Media/projects/RETICLE/slurm
./submit-etl-job.sh 2  # Ready to go!
```

---

## How It Works

1. **config.py** — Doesn't include password in psycopg2 params
2. **psycopg2** — Automatically reads `~/.pgpass` when password is absent
3. **HPC job** — Inherits your home directory, accesses `.pgpass` automatically

No environment variables, no .env files, no plaintext passwords in scripts.

---

## .pgpass Format

```
hostname:port:database:username:password
```

**Example:**
```
# Production Cloud SQL
cloudsql.c.di2-summercorp.internal:5432:reticle_biogrid:reticle_admin:your_password_here

# Local development
localhost:5432:reticle_biogrid:reticle_admin:your_local_password

# Multiple hosts (one per line)
host1.example.com:5432:reticle_biogrid:user1:password1
host2.example.com:5432:reticle_biogrid:user2:password2
```

---

## Security Notes

⚠️ **IMPORTANT:** `.pgpass` must have permissions `600` (readable only by you):

```bash
# Correct
chmod 600 ~/.pgpass

# Wrong - psycopg2 will reject this
chmod 644 ~/.pgpass
chmod 755 ~/.pgpass
```

**Why?** PostgreSQL refuses to use `.pgpass` with world-readable permissions because other users could steal your credentials.

---

## Verification on HPC

After submitting a job, verify `.pgpass` is being used:

```bash
# Check job log
./monitor-etl-jobs.sh <job_id> log | head -20

# Should show successful database connection without "password" in the output
```

If you see "psycopg2.OperationalError: password authentication failed", then:

1. Check `.pgpass` format: `cat ~/.pgpass`
2. Check permissions: `ls -l ~/.pgpass` (should be `-rw-------`)
3. Test manually: `psql -h <host> -U <user> -d <dbname> -c "SELECT 1"`

---

## Migrating from .env File

If you previously used `.env` file:

```bash
# 1. Create .pgpass from .env
cat scripts/.env | grep DB_ 

# 2. Extract credentials and create ~/.pgpass
# (Use the format above)

# 3. Delete .env to prevent accidental commits
rm scripts/.env

# 4. Update .gitignore
echo "scripts/.env" >> .gitignore
```

---

## Troubleshooting

### "password authentication failed"

**Check 1: Format**
```bash
cat ~/.pgpass
# Should look like: host:5432:db:user:password
```

**Check 2: Permissions**
```bash
ls -l ~/.pgpass
# Should be: -rw------- (600)
chmod 600 ~/.pgpass  # Fix if needed
```

**Check 3: Whitespace**
```bash
# Make sure there are NO spaces around colons
# ✓ correct: host:5432:db:user:pass
# ✗ wrong:   host : 5432 : db : user : pass
```

**Check 4: Newline at end**
```bash
# Ensure file ends with newline
echo "" >> ~/.pgpass
```

### "psycopg2: module not found"

This is a Python environment issue, not `.pgpass`. Check:

```bash
# In your conda environment
conda list | grep psycopg2
# Should show: psycopg2 (some version)
```

### Job can't find .pgpass

On HPC, `.pgpass` must be in your home directory:

```bash
# On HPC login node
echo $HOME
# Verify .pgpass is there
ls -l ~/.pgpass
```

---

## Reference

- PostgreSQL `.pgpass` docs: https://www.postgresql.org/docs/current/libpq-pgpass.html
- psycopg2 connection: https://www.psycopg.org/psycopg3/basic/basic.html#connection-strings

---

## Next Steps

1. ✅ Create `~/.pgpass` on your HPC login node
2. ✅ Test: `psql -h <host> -U <user> -d <dbname> -c "SELECT 1"`
3. ✅ Run SLURM job: `./submit-etl-job.sh 2`

Done! Credentials are now secure.
