import { PublicClientApplication } from "@azure/msal-browser";
import { API_BASE_URL } from "../config/env";

// Public (non-secret) SSO config needed to initialise MSAL.js.
interface SsoConfig {
  clientId: string;
  tenantId: string;
  authority: string;
  redirectUri: string;
}

let instancePromise: Promise<PublicClientApplication> | null = null;

/**
 * Resolve the SSO config. Preference order:
 *   1. Build-time env (REACT_APP_SSO_*) — no backend round-trip. Client id and
 *      tenant id are public, so baking them into the bundle is fine and lets the
 *      login page work even when the API is down.
 *   2. Fallback: fetch GET /api/auth/config from the backend (AWS-sourced).
 */
async function resolveSsoConfig(): Promise<SsoConfig> {
  const clientId = process.env.REACT_APP_SSO_CLIENT_ID ?? "";
  const tenantId = process.env.REACT_APP_SSO_TENANT_ID ?? "";

  if (clientId && tenantId) {
    return {
      clientId,
      tenantId,
      authority:
        process.env.REACT_APP_SSO_AUTHORITY ||
        `https://login.microsoftonline.com/${tenantId}`,
      // Default the redirect URI to wherever the app is actually served from —
      // works for localhost and prod without extra config (must be registered
      // as an SPA redirect URI in Azure).
      redirectUri:
        process.env.REACT_APP_SSO_REDIRECT_URI || window.location.origin,
    };
  }

  const res = await fetch(`${API_BASE_URL}/api/auth/config`, {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) throw new Error(`Could not load SSO config (${res.status})`);
  const cfg = (await res.json()) as {
    configured: boolean;
    clientId: string;
    tenantId: string;
    authority: string;
    redirectUri: string;
  };
  if (!cfg.configured || !cfg.clientId || !cfg.tenantId) {
    throw new Error("SSO is not configured on the server");
  }
  return {
    clientId: cfg.clientId,
    tenantId: cfg.tenantId,
    authority: cfg.authority,
    redirectUri: cfg.redirectUri || window.location.origin,
  };
}

/**
 * Lazily build + initialise the MSAL instance (once per page load).
 */
export function getMsal(): Promise<PublicClientApplication> {
  if (!instancePromise) {
    instancePromise = (async () => {
      const cfg = await resolveSsoConfig();
      const instance = new PublicClientApplication({
        auth: {
          clientId: cfg.clientId,
          authority: cfg.authority,
          redirectUri: cfg.redirectUri,
          postLogoutRedirectUri: cfg.redirectUri,
        },
        cache: {
          // Per-tab session storage: closing the tab ends the session.
          cacheLocation: "sessionStorage",
        },
      });
      await instance.initialize();
      return instance;
    })();
  }
  return instancePromise;
}
