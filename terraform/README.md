# RETICLE secrets (AWS Secrets Manager)

Terraform that manages a group of RETICLE secrets in AWS Secrets Manager,
encrypted with a dedicated KMS key, and readable only by a single IAM role that
you assume. Mirrors the TWAIN secrets module.

## What it creates

| Resource | Purpose |
| --- | --- |
| `aws_secretsmanager_secret` (one per entry in `secrets.json`) | Named `RETICLE/<key>` and tagged `Project=RETICLE`, `Category=RETICLE` |
| `aws_kms_key` + alias `alias/reticle-secrets` | Customer-managed key encrypting every secret; only the read role may `Decrypt` |
| `aws_iam_role` `RETICLE-secrets-reader` | The only non-admin principal allowed to read/decrypt; its trust policy lets **you** (and, optionally, ECS tasks) assume it |
| `aws_iam_role` `RETICLE-sso-ci-reader` (optional) | Least-privilege CI role — reads **only** `sso/APP_ID` + `sso/TENANT_ID` for injecting `REACT_APP_SSO_*` into the web build. Created when `ci_principal_arns` is set; ARN exposed as the `sso_ci_reader_role_arn` output |

Access model: the KMS key policy grants `Decrypt` only to `RETICLE-secrets-reader`
(plus account administrators, who can always access account resources). The
role's identity policy scopes `GetSecretValue`/`DescribeSecret` to exactly the
`RETICLE/*` secrets. Assume the role → read the secrets; nobody else (short of
an account admin) can read the values.

## Secret definitions — `secrets.json` (never committed)

```bash
cp secrets.example.json secrets.json   # then fill in real values
```

Each entry is `"<name>": { "description": "...", "value": "..." }`. The `<name>`
may contain `/` to sub-group (e.g. `database/DB_PASSWORD` → secret
`RETICLE/database/DB_PASSWORD`). Both `secrets.json` and `terraform.tfstate`
hold secret values and are git-ignored.

## Usage

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # optional; pin region / your ARN
cp secrets.example.json secrets.json           # fill in real values

terraform init
terraform plan
terraform apply
```

## Reading a secret (after apply)

```bash
creds=$(aws sts assume-role \
  --role-arn "$(terraform output -raw role_arn)" \
  --role-session-name reticle-secrets)
export AWS_ACCESS_KEY_ID=$(echo "$creds"     | jq -r .Credentials.AccessKeyId)
export AWS_SECRET_ACCESS_KEY=$(echo "$creds" | jq -r .Credentials.SecretAccessKey)
export AWS_SESSION_TOKEN=$(echo "$creds"     | jq -r .Credentials.SessionToken)

aws secretsmanager get-secret-value \
  --secret-id RETICLE/database/DB_PASSWORD \
  --query SecretString --output text
```

## Wiring the app to read these

Point RETICLE services at Secrets Manager instead of plaintext `.env` — the ECS
task role should be `RETICLE-secrets-reader` (or assume it), then fetch
`RETICLE/database/*` at startup. See the TWAIN `api/database.py` pattern.
