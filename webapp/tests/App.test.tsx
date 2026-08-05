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

  // The home page is now one box: a mode chip (gene | screen), a "+" for a ranked gene list, and
  // a type-ahead. These target the CONTROLS — role, label, placeholder — rather than the sentence
  // around them, so re-wording the page does not read as a regression.
  it("renders without crashing", async () => {
    render(<App />);
    await screen.findByRole("textbox");
  });

  it("shows RETICLE branding on the home page", async () => {
    render(<App />);
    // The wordmark is RETI<b>C</b>LE, so it spans elements — match on the composed text.
    const marks = await screen.findAllByText(
      (_content, el) => el?.textContent?.replace(/\s+/g, "").startsWith("RETICLE") ?? false,
    );
    expect(marks.length).toBeGreaterThan(0);
  });

  it("offers both search modes from the chip", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { expanded: false }));
    const items = await screen.findAllByRole("menuitem");
    // Matched on the leading label, not the accessible name: each item's name also carries its
    // blurb, and the Gene blurb ends "...what the screens say", which /Screen/i happily matches.
    expect(items.map((i) => i.textContent?.split(/(?=[A-Z][a-z]+ )/)[0])).toEqual(
      expect.arrayContaining([expect.stringMatching(/^Gene/), expect.stringMatching(/^Screen/)]),
    );
  });

  it("navigates into a sub-flow and back via the sticky Home control", async () => {
    render(<App />);
    // The "+" is the ranked-gene-list route.
    fireEvent.click(await screen.findByLabelText(/Analyse a ranked gene list/i));
    // The sticky Home control is only shown off the home page.
    fireEvent.click(await screen.findByText("Home"));
    expect(await screen.findByRole("textbox")).toBeTruthy();
  });

  it("carries a typed gene into the wiki instead of making the user retype it", async () => {
    render(<App />);
    const box = await screen.findByRole("textbox");
    fireEvent.change(box, { target: { value: "FANCD2" } });
    fireEvent.click(screen.getByLabelText("Search"));
    // Leaving the home page is the observable part; the vendored bundle owns what happens next
    // and does not run under jsdom.
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
  });
});

describe("App (signed out)", () => {
  beforeEach(() => {
    mock.state.account = null;
    mock.instance.loginRedirect.mockClear();
  });

  // Signed-out visitors now land on the public marketing page and reach the SSO card from its CTA,
  // rather than being dropped straight onto the login prompt.
  it("shows the marketing landing page", async () => {
    render(<App />);
    expect(
      await screen.findByText(/AI-powered bioinformatics/i),
    ).toBeTruthy();
  });

  // The SSO button now names the identity provider — "Login" said what the button was, not what
  // pressing it does.
  it("shows the Login landing page after Sign in is clicked", async () => {
    render(<App />);
    fireEvent.click((await screen.findAllByText(/^Sign in$/i))[0]);
    expect(await screen.findByText(/Sign in with WashU/i)).toBeTruthy();
  });

  it("starts SSO login when the WashU button is clicked", async () => {
    render(<App />);
    fireEvent.click((await screen.findAllByText(/^Sign in$/i))[0]);
    fireEvent.click(await screen.findByText(/Sign in with WashU/i));
    await waitFor(() => expect(mock.instance.loginRedirect).toHaveBeenCalled());
  });
});
