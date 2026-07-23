# SSO & AWS Secrets — local setup

The API no longer stores DB / SSO / secure-API credentials in a plaintext
`.env`. They live in **AWS Secrets Manager** under `RETICLE/*` (provisioned by
`terraform/`) and are pulled into the process environment at startup by
`api/config.py`.

Auth is **Microsoft Entra ID (Azure AD)** single sign-on using the **SPA**
model: the browser does the login itself with **MSAL.js** (OAuth2 authorization
code + **PKCE**, *no client secret*). The webapp shows a single **Login** button;
the actual credential entry happens on Microsoft's hosted login page.

The backend does **not** handle tokens or sessions. Its only auth job is to serve
the *public* SSO config (client id, tenant, authority, redirect URI) so the SPA
can initialise MSAL — keeping AWS Secrets Manager as the single source of truth.

## How it fits together

```
Browser ─"Login"─▶ MSAL.js loginRedirect ─▶ Microsoft login (WashU creds, PKCE)
   ▲                                                    │
   └──────── redirect back to FRONTEND_URL ◀────────────┘
            MSAL stores the account in sessionStorage; App gates on it.

On load:  App ─▶ GET /api/auth/config ─▶ init MSAL ─▶ signed in? show app : show Login
```

- `api/config.py` — loads `RETICLE/*` from Secrets Manager → env vars
  (`AWS_DB_*`, `SSO_*`, `SECURE_API_*`).
- `api/services/auth_service.py` + `api/routers/auth.py` — one endpoint,
  `GET /api/auth/config` (public: client id, tenant, authority, redirect URI).
- `webapp/src/services/msalClient.ts` — fetches that config, builds + initialises
  the MSAL `PublicClientApplication`.
- `webapp/src/services/auth.ts` — `initAuth()` / `startLogin()` / `logout()`.
- `webapp/src/components/LoginLanding.jsx` — the Login page.
- `webapp/src/App.tsx` — auth gate (signed in ⇢ app; otherwise ⇢ Login).

> **Note:** per the current decision, backend API routes are **not** token-
> protected yet — the gate is client-side only. When you want the API to enforce
> auth, add bearer-token validation (validate the Entra token's signature via the
> tenant JWKS, `aud` = client id) as a FastAPI dependency; the SPA already holds
> a token it can attach as `Authorization: Bearer …`.

## Prerequisites

1. **AWS credentials** on your machine (`aws configure` / SSO). `config.py`
   reads the secrets with your identity. Verify: `aws sts get-caller-identity`.
   To assume the reader role instead, set
   `RETICLE_SECRETS_ROLE_ARN=arn:aws:iam::<acct>:role/RETICLE-secrets-reader`.

2. **Azure app registration — SPA platform** (one-time, done in the Entra portal
   by whoever owns app registration `27f47244-…`):
   Authentication → Add a platform → **Single-page application** → redirect URI
   **`http://localhost:3001`**. The *SPA* platform (not *Web*) is what enables
   PKCE + the CORS token endpoint and requires **no client secret**. Without it,
   Microsoft returns `AADSTS50011 (redirect URI mismatch)`.
   (The production origin, e.g. `https://reticle.washu.edu`, is added the same
   way as a second SPA redirect URI when you deploy.)

## Run locally

```bash
npm run dev:all          # API on :8000, webapp on :3001
```

Open http://localhost:3001 → click **Login** → sign in with your WashU account →
Microsoft redirects you back and the app loads.

### Useful env overrides (`api/.env`, all optional)

| Var | Default (local) | Purpose |
| --- | --- | --- |
| `FRONTEND_URL` | `http://localhost:3001` | CORS origin + default SSO redirect target |
| `SSO_REDIRECT_URI` | = `FRONTEND_URL` | Override the MSAL redirect URI |
| `CORS_ALLOW_ORIGINS` | — | Extra allowed origins (comma-separated) |
| `RETICLE_SKIP_AWS_SECRETS` | unset | `1` = don't call AWS (offline/tests, mock data) |

## Quick verification (no browser)

```bash
curl -s localhost:8000/api/auth/config   # → {"configured":true,"clientId":...,"redirectUri":"http://localhost:3001"}
```

## How each surface gets its secrets

Both the API and the webapp source everything from **AWS Secrets Manager**
(`RETICLE/*`); nothing sensitive is committed.

| Surface | Secrets it needs | How it gets them |
| --- | --- | --- |
| **API** (ECS) | DB, Secure-AI, SSO | Reads `RETICLE/*` at runtime via `config.py` (boto3). The ECS **task role must be `RETICLE-secrets-reader`** (terraform trusts `ecs-tasks.amazonaws.com` to assume it). |
| **Webapp** (S3/CloudFront) | Public SSO client + tenant id | The `webapp` CI job assumes the least-privilege **`RETICLE-sso-ci-reader`** role, reads `RETICLE/sso/APP_ID` + `RETICLE/sso/TENANT_ID`, and injects them as `REACT_APP_SSO_*` into the build. That role can read *only* those two SSO ids. |

### CI/CD (GitHub Actions)

The `arifs` IAM user's keys (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`
secrets) drive both pipelines:

- **`webapp-ci-cd.yml`** — build job assumes `RETICLE_SSO_CI_ROLE_ARN`
  (`RETICLE-sso-ci-reader`), loads the SSO ids from Secrets Manager, then builds.
  Deploy job (main only) syncs to S3 + invalidates CloudFront.
- **`api-ci-cd.yml`** — builds/pushes the image and updates the ECS service. The
  running task reads secrets itself via its task role — no build-time injection.

The `RETICLE-sso-ci-reader` role is provisioned by `terraform/` when
`ci_principal_arns` is set (see `terraform.tfvars`); its ARN is the
`sso_ci_reader_role_arn` output.

## Production checklist

- Add the prod origin as a second **SPA** redirect URI in the Entra app registration.
- Set `FRONTEND_URL` (and `CORS_ALLOW_ORIGINS` if the API is on a different host)
  to the prod domains.
- Ensure the ECS task role is `RETICLE-secrets-reader` so the API can read `RETICLE/*`.
- No client secret or session cookie is involved in the SPA flow.
