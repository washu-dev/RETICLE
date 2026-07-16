import type { AccountInfo } from "@azure/msal-browser";
import { getMsal } from "./msalClient";

export interface User {
  oid: string;
  name: string;
  email: string;
  tenant: string;
}

// OIDC scopes only — enough to sign in and read the user's identity. No
// Microsoft Graph / admin-consent permissions are requested.
const LOGIN_SCOPES = ["openid", "profile", "email"];

function toUser(account: AccountInfo | null): User | null {
  if (!account) return null;
  const claims = (account.idTokenClaims ?? {}) as Record<string, unknown>;
  return {
    oid: (claims.oid as string) ?? account.localAccountId,
    name: account.name ?? "",
    email: account.username ?? (claims.preferred_username as string) ?? "",
    tenant: (claims.tid as string) ?? account.tenantId ?? "",
  };
}

/**
 * Initialise auth on app load: process any redirect coming back from Microsoft,
 * then return the signed-in user (or null if not signed in). Safe to call once
 * on mount. Throws only if the SSO config can't be loaded.
 */
export async function initAuth(): Promise<User | null> {
  const msal = await getMsal();

  // If we're returning from a login redirect, this consumes the response.
  const result = await msal.handleRedirectPromise();
  if (result?.account) {
    msal.setActiveAccount(result.account);
    return toUser(result.account);
  }

  let account = msal.getActiveAccount();
  if (!account) {
    const accounts = msal.getAllAccounts();
    if (accounts.length > 0) {
      account = accounts[0];
      msal.setActiveAccount(account);
    }
  }
  return toUser(account);
}

/** Redirect the browser to Microsoft to sign in. */
export async function startLogin(): Promise<void> {
  const msal = await getMsal();
  await msal.loginRedirect({ scopes: LOGIN_SCOPES });
}

/** Sign the user out (clears the MSAL cache and redirects through Microsoft). */
export async function logout(): Promise<void> {
  const msal = await getMsal();
  const account = msal.getActiveAccount() ?? undefined;
  await msal.logoutRedirect({ account });
}
