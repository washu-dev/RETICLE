"""Central configuration + AWS Secrets Manager loader for the RETICLE API.

The secrets that used to live in a plaintext ``.env`` now live in AWS Secrets
Manager (managed by ``terraform/``). This module pulls them at startup and maps
each one into the process environment under the name the rest of the app already
reads, so no downstream module has to know about AWS.

    AWS secret name              ->  environment variable
    ---------------------------      --------------------------
    RETICLE/database/DB_HOST     ->  AWS_DB_HOST
    RETICLE/database/DB_PORT     ->  AWS_DB_PORT
    RETICLE/database/DB_USER     ->  AWS_DB_USER
    RETICLE/database/DB_PASSWORD ->  AWS_DB_PASSWORD
    RETICLE/database/DB_NAME     ->  AWS_DB_NAME
    RETICLE/sso/APP_ID           ->  SSO_CLIENT_ID
    RETICLE/sso/TENANT_ID        ->  SSO_TENANT_ID
    RETICLE/sso/APP_SECRET       ->  SSO_CLIENT_SECRET
    RETICLE/secure_api/CLIENT_ID ->  SECURE_API_CLIENT_ID
    RETICLE/secure_api/CLIENT_SECRET -> SECURE_API_CLIENT_SECRET
    RETICLE/secure_api/API_KEY   ->  SECURE_API_KEY

IMPORTANT: import this module *before* any module that reads ``AWS_DB_*`` at
import time (e.g. ``services.db_service``), so the environment is populated
first. ``main.py`` does this.

Local dev: your default AWS credentials (``aws configure`` / SSO) are used to
read the secrets. Optionally set ``RETICLE_SECRETS_ROLE_ARN`` to assume the
``RETICLE-secrets-reader`` role first. Set ``RETICLE_SKIP_AWS_SECRETS=1`` to
skip AWS entirely and fall back to a local ``.env`` / plain env vars (used by
tests and offline work).
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from dotenv import load_dotenv

if TYPE_CHECKING:
    from boto3.session import Session

logger = logging.getLogger(__name__)

# A local .env still wins over AWS for any value a developer chooses to override.
load_dotenv()

# ── secret name (relative to the RETICLE/ prefix) -> destination env var ──────
_SECRET_ENV_MAP: dict[str, str] = {
    "database/DB_HOST": "AWS_DB_HOST",
    "database/DB_PORT": "AWS_DB_PORT",
    "database/DB_USER": "AWS_DB_USER",
    "database/DB_PASSWORD": "AWS_DB_PASSWORD",
    "database/DB_NAME": "AWS_DB_NAME",
    "sso/APP_ID": "SSO_CLIENT_ID",
    "sso/TENANT_ID": "SSO_TENANT_ID",
    "sso/APP_SECRET": "SSO_CLIENT_SECRET",
    "secure_api/CLIENT_ID": "SECURE_API_CLIENT_ID",
    "secure_api/CLIENT_SECRET": "SECURE_API_CLIENT_SECRET",
    "secure_api/API_KEY": "SECURE_API_KEY",
}

_SECRET_PREFIX = os.getenv("RETICLE_SECRET_PREFIX", "RETICLE")
_AWS_REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))


def _boto_session() -> Session:
    """Return a boto3 Session, optionally assuming RETICLE_SECRETS_ROLE_ARN."""
    import boto3

    role_arn = os.getenv("RETICLE_SECRETS_ROLE_ARN", "").strip()
    if not role_arn:
        return boto3.session.Session(region_name=_AWS_REGION)

    sts = boto3.client("sts", region_name=_AWS_REGION)
    creds = sts.assume_role(RoleArn=role_arn, RoleSessionName="reticle-api-secrets")[
        "Credentials"
    ]
    return boto3.session.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=_AWS_REGION,
    )


def load_secrets() -> bool:
    """Fetch RETICLE/* secrets from AWS Secrets Manager into ``os.environ``.

    A value already present in the environment (e.g. from a local ``.env``) is
    left untouched, so explicit local overrides win.

    Returns True if secrets were loaded from AWS, False if skipped or failed
    (in which case the app runs on whatever env vars are already set).
    """
    if os.getenv("RETICLE_SKIP_AWS_SECRETS", "").lower() in ("1", "true", "yes"):
        logger.info("RETICLE_SKIP_AWS_SECRETS set — not loading secrets from AWS")
        return False

    try:
        client = _boto_session().client("secretsmanager", region_name=_AWS_REGION)
    except Exception as exc:  # noqa: BLE001 — boto/import/credential errors all fall back
        logger.warning("Could not init AWS Secrets Manager client: %s", exc)
        return False

    loaded = 0
    for rel_name, env_var in _SECRET_ENV_MAP.items():
        if os.environ.get(env_var):  # local override already set — keep it
            continue
        secret_id = f"{_SECRET_PREFIX}/{rel_name}"
        try:
            value = client.get_secret_value(SecretId=secret_id)["SecretString"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read secret %s: %s", secret_id, exc)
            continue
        os.environ[env_var] = value
        loaded += 1

    if loaded:
        logger.info("Loaded %d secret(s) from AWS Secrets Manager", loaded)
    return loaded > 0


class _Settings:
    """Runtime settings resolved from the environment (after ``load_secrets``)."""

    # ── Microsoft Entra ID (Azure AD) SSO ────────────────────────────────────
    @property
    def sso_client_id(self) -> str:
        return os.getenv("SSO_CLIENT_ID", "")

    @property
    def sso_tenant_id(self) -> str:
        return os.getenv("SSO_TENANT_ID", "")

    @property
    def sso_authority(self) -> str:
        return f"https://login.microsoftonline.com/{self.sso_tenant_id}"

    @property
    def sso_configured(self) -> bool:
        # SPA model: no client secret needed — the browser does PKCE.
        return bool(self.sso_client_id and self.sso_tenant_id)

    @property
    def spa_redirect_uri(self) -> str:
        """Where Entra redirects the SPA back to after login (the app origin).

        Defaults to FRONTEND_URL; override with SSO_REDIRECT_URI if the app is
        served from a sub-path. This value must be registered in the Azure app
        registration under the *Single-page application* platform.
        """
        return os.getenv("SSO_REDIRECT_URI", self.frontend_url).rstrip("/")

    # ── URLs ─────────────────────────────────────────────────────────────────
    @property
    def frontend_url(self) -> str:
        """The webapp origin — the CORS origin and default SPA redirect target."""
        return os.getenv("FRONTEND_URL", "http://localhost:3001").rstrip("/")

    @property
    def cors_origins(self) -> list[str]:
        extra = [
            o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if o.strip()
        ]
        origins = [self.frontend_url, *extra]
        # de-dupe, preserve order
        return list(dict.fromkeys(origins))


settings = _Settings()

# Populate the environment from AWS at import time. Import order in main.py
# guarantees this runs before services.db_service reads AWS_DB_*.
load_secrets()
