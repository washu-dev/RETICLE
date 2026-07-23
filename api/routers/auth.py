"""SSO auth routes (SPA model).

Only one endpoint: the SPA fetches its public MSAL config here on startup. The
interactive login and token handling happen entirely in the browser.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SsoConfig(BaseModel):
    configured: bool
    clientId: str
    tenantId: str
    authority: str
    redirectUri: str


@router.get("/config", response_model=SsoConfig)
async def sso_config() -> dict[str, str | bool]:
    """Public config the webapp needs to initialise MSAL.js."""
    return auth_service.public_config()
