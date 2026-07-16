import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import App from "../src/App";
import * as msalClient from "../src/services/msalClient";

// The app now gates on Microsoft Entra SSO. In tests there is no backend or real
// MSAL, so we mock the MSAL client (getMsal) with a fake PublicClientApplication.
// The real auth.ts logic (initAuth / toUser / startLogin) still runs against it.
// Everything is defined INSIDE the factory (jest hoists jest.mock above the file's
// other declarations); the controllable handle is exposed as `__mock`.
jest.mock("../src/services/msalClient", () => {
  const state: { account: unknown } = { account: null };
  const instance = {
    handleRedirectPromise: jest.fn().mockResolvedValue(null),
    getActiveAccount: jest.fn(() => state.account),
    getAllAccounts: jest.fn(() => (state.account ? [state.account] : [])),
    setActiveAccount: jest.fn(),
    loginRedirect: jest.fn(),
    logoutRedirect: jest.fn(),
  };
  return {
    getMsal: jest.fn().mockResolvedValue(instance),
    __mock: { state, instance },
  };
});

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const mock = (msalClient as any).__mock as {
  state: { account: unknown };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  instance: Record<string, any>;
};

const signedInAccount = {
  localAccountId: "abc",
  name: "Test User",
  username: "test@wustl.edu",
  idTokenClaims: { oid: "abc", tid: "tenant-1" },
};

describe("App (signed in)", () => {
  beforeEach(() => {
    mock.state.account = signedInAccount;
  });

  it("renders without crashing", async () => {
    render(<App />);
    await screen.findByText("Launch app");
  });

  it("shows RETICLE branding on the landing page", async () => {
    render(<App />);
    expect((await screen.findAllByText("RETICLE")).length).toBeGreaterThan(0);
  });

  it("shows the upload gene list call-to-action", async () => {
    render(<App />);
    expect(await screen.findByText("Upload gene list")).toBeTruthy();
  });

  it("navigates into a sub-flow and back via the sticky Home control", async () => {
    render(<App />);
    // Enter a sub-flow from the landing nav.
    fireEvent.click(await screen.findByText("Launch app"));
    // The sticky Home control is only shown off the landing page.
    fireEvent.click(await screen.findByText("Home"));
    // Home returns us to the main page.
    expect(await screen.findByText("Launch app")).toBeTruthy();
  });
});

describe("App (signed out)", () => {
  beforeEach(() => {
    mock.state.account = null;
    mock.instance.loginRedirect.mockClear();
  });

  it("shows the Login landing page", async () => {
    render(<App />);
    expect(await screen.findByText("Login")).toBeTruthy();
  });

  it("starts SSO login when Login is clicked", async () => {
    render(<App />);
    fireEvent.click(await screen.findByText("Login"));
    await waitFor(() => expect(mock.instance.loginRedirect).toHaveBeenCalled());
  });
});
