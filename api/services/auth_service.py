"""Microsoft Entra ID (Azure AD) SSO — SPA model.

The browser (webapp) performs the interactive login itself using MSAL.js with
the authorization-code + PKCE flow, so there is **no client secret** and the API
never handles tokens or sessions. All this backend does for auth is hand the SPA
the *public* configuration it needs to initialise MSAL (client id, tenant,
authority, redirect URI) — sourced from AWS Secrets Manager via ``config.py`` so
there's a single source of truth.

None of these values are secret: the client id and tenant id are safe to expose
to the browser (that's exactly what MSAL.js needs).
"""

from __future__ import annotations

from config import settings


def public_config() -> dict[str, str | bool]:
    """Public SSO config for the SPA's MSAL initialisation."""
    return {
        "configured": settings.sso_configured,
        "clientId": settings.sso_client_id,
        "tenantId": settings.sso_tenant_id,
        "authority": settings.sso_authority,
        "redirectUri": settings.spa_redirect_uri,
    }
