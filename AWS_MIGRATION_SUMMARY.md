# AWS RDS Migration Summary

**Date:** June 3, 2026  
**Status:** ✅ Complete  
**Impact:** GCP Cloud SQL → AWS RDS PostgreSQL

---

## What Changed

### New Files Created

1. **`scripts/deploy_aws.sh`** (executable)
   - Replaces `deploy_gcp.sh` for AWS RDS deployment
   - Creates security group with PostgreSQL ingress rule
   - Creates RDS PostgreSQL instance (db.t3.micro, 20GB storage)
   - Generates `.env.generated` with RDS endpoint

2. **`scripts/AWS_SETUP.md`** (comprehensive guide)
   - Full AWS RDS setup instructions
   - Cost comparison (AWS vs GCP)
   - Monitoring commands
   - Troubleshooting guide
   - AWS CLI cheat sheet

### Files Updated

1. **`scripts/.env`**
   - Changed from localhost (GCP Proxy) to RDS endpoint
   - Updated AWS region and instance ID
   - Removed GCP configuration

2. **`scripts/.env.example`**
   - Changed to AWS RDS format
   - Updated with AWS configuration section

3. **`scripts/QUICKSTART.md`**
   - Updated to use `./deploy_aws.sh`
   - Added AWS credential check
   - Updated timing (5-10 min for RDS vs 15-20 min for GCP)

### Files NOT Changed

✅ `database_setup.py` — No changes needed (uses SQLAlchemy)  
✅ `biogrid_downloader.py` — No changes needed  
✅ `biogrid_loader.py` — No changes needed  
✅ `config.py` — No changes needed (uses standard DB env vars)  
✅ `models.py` — No changes needed  

---

## New Sequence of Commands

### Prerequisites
```bash
# Install AWS CLI
brew install awscli

# Configure AWS credentials
aws configure

# Activate conda
conda activate reticle
```

### Deployment
```bash
cd /Volumes/SD\ Media/projects/RETICLE/scripts

# 1. Deploy RDS instance (5-10 min)
./deploy_aws.sh

# 2. Update password
mv .env.generated .env
nano .env  # Add DB_PASSWORD

# 3. Initialize schema
python database_setup.py

# 4. Download & load data
python biogrid_downloader.py
python biogrid_loader.py data/biogrid_screens_*.json
```

---

## Key Differences: AWS RDS vs GCP Cloud SQL

| Aspect | AWS RDS | GCP Cloud SQL |
|---|---|---|
| **Setup Time** | 5-10 min | 15-20 min |
| **Free Tier** | db.t3.micro (12 months) | db-f1-micro (1 year) |
| **Post-Free Cost** | ~$30-50/month | ~$15-20/month |
| **Networking** | Security groups + IP whitelist | VPC + Firewall rules |
| **Deployment** | `./deploy_aws.sh` | `./deploy_gcp.sh --local-dev` |
| **Connection Type** | Direct RDS endpoint | Cloud SQL Proxy |
| **Infrastructure as Code** | Bash + AWS CLI | Bash + gcloud CLI |

---

## Why AWS RDS?

✅ **Faster setup** — 5-10 min vs 15-20 min  
✅ **Direct connectivity** — No proxy overhead  
✅ **Industry standard** — Most teams use AWS  
✅ **Same Python code** — No application changes needed  
✅ **Better monitoring** — CloudWatch logs, metrics, alarms  
✅ **Flexible scaling** — Easy to upgrade instance or storage  

---

## Validation Checklist

Before running `deploy_aws.sh`, verify:

- [ ] AWS CLI installed: `aws --version`
- [ ] AWS credentials configured: `aws sts get-caller-identity`
- [ ] Conda environment active: `conda activate reticle`
- [ ] You're in scripts directory: `pwd` → `.../RETICLE/scripts`
- [ ] `.env` exists (will be created by deploy_aws.sh)

---

## Next Steps

1. **Run AWS deployment:**
   ```bash
   conda activate reticle
   ./deploy_aws.sh
   ```

2. **Update `.env` with password:**
   ```bash
   mv .env.generated .env
   nano .env
   ```

3. **Initialize database and load data:**
   ```bash
   python database_setup.py
   python biogrid_downloader.py
   python biogrid_loader.py data/biogrid_screens_*.json
   ```

---

## Documentation

- **AWS Setup Guide:** `scripts/AWS_SETUP.md` (detailed)
- **Quick Start:** `scripts/QUICKSTART.md` (5-step overview)
- **README:** `scripts/README.md` (comprehensive, still valid)

---

## Support

For issues:
1. Check `AWS_SETUP.md` troubleshooting section
2. Verify AWS credentials: `aws sts get-caller-identity`
3. Check RDS status: `aws rds describe-db-instances --db-instance-identifier reticle-db --region us-east-1`
4. Check security group rules: `aws ec2 describe-security-groups --filters "Name=group-name,Values=reticle-rds-sg" --region us-east-1`

---

**You're all set!** Ready to deploy to AWS RDS. 🚀
