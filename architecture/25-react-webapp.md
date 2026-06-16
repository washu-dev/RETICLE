# RETICLE Task #25 — React Native Web App

Technical specification and application architecture.
Companion diagram: `architecture/25-react-webapp.drawio`.

## 1. Scope

A React Native app compiled for the **web runtime** that displays a header, a footer,
and the welcome message fetched from `GET /api/greetings` (Task #24). Static bundle
deployed to **AWS S3 + CloudFront** (confirming the placeholder in `webapp-ci-cd.yml`).
WashU brand and WCAG 2.1 AA compliant.

### Deployment target (confirmation)

**S3 + CloudFront is confirmed as the target.** Rationale: a React Native Web build is
a static bundle (HTML/JS/CSS); no SSR is required for this content. S3 (private, origin
access control) behind CloudFront (TLS, caching, edge) is the lowest-cost,
lowest-ops fit and matches the `webapp-ci-cd.yml` placeholder comment. If SSR/SEO
becomes a requirement later, revisit (Fargate or a Next-style runtime).

### Toolchain decision

Use **Expo (managed) with `expo export --platform web`** (Metro/Webpack web output) OR
plain `react-native-web` + Webpack. **Recommendation: Expo**, because it gives
`react-native-web` integration, a `build:web` script, env handling, and Jest preset out
of the box — minimizing custom config. The CI expects:

- `npm run lint`, `npm run typecheck` (both `--if-present`)
- `npm run build:web` → output to **`webapp/web-build/`** (must match the workflow's
  `path: webapp/web-build/`)
- `npm test -- --watchAll=false --coverage`
- build-time env `REACT_APP_API_BASE_URL` (injected as a GitHub secret)

> Action for the developer: Expo's default web export dir is `dist/`. Either configure
> the export to `web-build/` or add a script that moves it. The CI artifact path
> `webapp/web-build/` is the contract — match it, do not change the workflow.

## 2. Functional requirements (acceptance criteria)

- **FR-1 Greeting display.** On load, the app calls `GET {REACT_APP_API_BASE_URL}/api/greetings`
  and renders the returned `message` in the main content area.
- **FR-2 Loading state.** While the request is in flight, a visible, accessible loading
  indicator is shown (not a blank screen).
- **FR-3 Error state.** On network/HTTP error, a human-readable error message and a
  Retry control are shown; the app does not crash or show a raw error object.
- **FR-4 Header.** A page header renders the product name in the brand serif
  (ivypresto-headline) on every view.
- **FR-5 Footer.** A page footer renders attribution/links in the brand sans
  (ivystyle-sans) on every view.
- **FR-6 Config-driven base URL.** The API base URL is read from `REACT_APP_API_BASE_URL`
  at build time; no hardcoded hostnames in source.
- **FR-7 Responsive.** Layout is usable from 320 px to desktop widths.

## 3. Non-functional requirements (measurable)

| ID | Category | Target |
|---|---|---|
| NFR-1 | Performance | Initial JS bundle (gzipped) < 350 KB; LCP < 2.5 s on a 3G-fast profile |
| NFR-2 | Accessibility | WCAG 2.1 AA (see §8 checklist); zero critical axe violations |
| NFR-3 | Availability | Served from CloudFront edge; SPA fallback for 403/404 → `/index.html` |
| NFR-4 | Security | HTTPS only; CSP + HSTS + X-Content-Type-Options response headers; S3 bucket private (OAC), no public ACLs |
| NFR-5 | Cost | S3 storage + CloudFront for a tiny static bundle ≈ **free-tier / low single-digit USD/month** |
| NFR-6 | Caching | Hashed asset filenames cached long-lived (`max-age=31536000, immutable`); `index.html` `no-cache` so deploys are picked up immediately |
| NFR-7 | Quality | ESLint + TypeScript strict clean; Jest coverage ≥ 70% on components/hooks |
| NFR-8 | Brand | Typography matches WashU stack; verified in §7 checklist |

## 4. Component hierarchy

```
App                       # font + theme provider, layout shell
├─ Header                 # serif product title (ivypresto-headline), role="banner"
├─ main (role="main")
│  └─ GreetingScreen      # consumes useGreeting(); renders Loading | Error | Greeting
│     ├─ LoadingIndicator # accessible busy state
│     ├─ ErrorMessage     # message + Retry button
│     └─ GreetingText     # the welcome message
└─ Footer                 # sans attribution (ivystyle-sans), role="contentinfo"
```

Supporting (non-visual):
```
hooks/useGreeting.ts      # state machine: idle → loading → success | error; exposes retry()
services/api.ts           # apiClient: fetch wrapper, baseURL from env, timeout, error normalization
services/greetings.ts     # getGreeting(): typed call to GET /api/greetings
config/env.ts             # reads REACT_APP_API_BASE_URL, single source of truth
theme/typography.ts       # font family constants + Typekit load
```

### SOLID mapping

- **SRP** — presentation (components) is separate from data fetching (`useGreeting`)
  which is separate from transport (`apiClient`). A component never calls `fetch`.
- **DIP** — `useGreeting` depends on the `getGreeting` service abstraction, not on
  `fetch` directly; in tests the service is mocked, no network.
- **OCP** — adding a second endpoint means a new `services/*.ts` + hook, no edits to
  `apiClient` or existing components.
- **ISP** — `GreetingScreen` receives only the greeting state it needs, not the whole
  app store.

## 5. API client pattern

```ts
// config/env.ts
export const API_BASE_URL = process.env.REACT_APP_API_BASE_URL ?? "http://localhost:8080";

// services/api.ts
export async function apiGet<T>(path: string, opts?: { signal?: AbortSignal }): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal: opts?.signal,
  });
  if (!res.ok) throw new ApiError(res.status, await safeJson(res));
  return res.json() as Promise<T>;
}

// services/greetings.ts
export const getGreeting = () => apiGet<{ message: string }>("/api/greetings");
```

- `useGreeting` owns a `status: "idle" | "loading" | "success" | "error"` state, calls
  `getGreeting()` in an effect with an `AbortController`, and exposes `retry()`.
- Errors are normalized to `ApiError(status, body)` so the UI branches on a typed shape,
  never on raw exceptions.
- No credentials/cookies in this task (CORS simple request); if SSO arrives, auth is
  added in `apiClient` centrally.

## 6. Environment variable handling (12-factor III)

| Var | Source | Notes |
|---|---|---|
| `REACT_APP_API_BASE_URL` | GitHub secret → CI build env | Baked at build time into the bundle; **public** value (it ships to the browser) — never put secrets in `REACT_APP_*` |
| local dev | `webapp/.env` (gitignored) | defaults to `http://localhost:8080` |

- Single read point (`config/env.ts`); the rest of the app imports from there (DRY,
  one place to change).
- `.env.production` is written by CI from the secret (matches the API/WCS deploy
  pattern of injecting at build), never committed.
- Because this is a static bundle, the API URL is **build-time**, not runtime. Changing
  it requires a rebuild+redeploy — acceptable for placeholder; note for the team.

## 7. WashU brand compliance checklist

Typography from `https://use.typekit.net/mav2zlt.css`.

- [ ] Typekit stylesheet loaded once (web `<head>` via `app.json`/template, with
      `rel="preconnect"` to `use.typekit.net` for performance).
- [ ] Sans stack applied as default body font:
      `"ivystyle-sans", Calibri, Tahoma, sans-serif`.
- [ ] Serif stack applied to headings (Header title):
      `"ivypresto-headline", Georgia, serif`.
- [ ] Font fallbacks present so text renders before/if Typekit fails (no invisible
      text — `font-display: swap` behavior).
- [ ] Heading hierarchy semantic (one `h1` for the page title in Header).
- [ ] Colors and spacing follow WashU guidance
      (https://marcomm.washu.edu/typography/); no off-brand fonts introduced.
- [ ] Header and Footer present on every view (FR-4/FR-5).

> React Native Web maps `Text` style `fontFamily`; centralize the two stacks in
> `theme/typography.ts` and apply via a `Typography`/`Text` wrapper so the stacks are
> declared once.

## 8. Accessibility checklist (WCAG 2.1 AA)

Per https://digitalaccessibility.wustl.edu/.

- [ ] Landmarks: `role="banner"` (Header), `role="main"`, `role="contentinfo"`
      (Footer) — via RN Web `accessibilityRole`.
- [ ] Single, descriptive page `h1`; logical heading order.
- [ ] Loading state announced to AT (`accessibilityRole="alert"` /
      `aria-busy="true"` on the region).
- [ ] Error message announced (`role="alert"`); Retry is a real, focusable,
      keyboard-activatable button with an accessible name.
- [ ] Color contrast ≥ 4.5:1 for body text, ≥ 3:1 for large text/UI components.
- [ ] All interactive elements reachable and operable by keyboard; visible focus ring.
- [ ] Text resizes to 200% without loss of content/function; no fixed pixel traps.
- [ ] Reflow usable at 320 px width (no horizontal scroll for content).
- [ ] `lang="en"` set on the document.
- [ ] Images/icons have text alternatives (or `accessibilityElementsHidden` if
      decorative).
- [ ] Automated check: `jest-axe` (or Playwright + axe) in the test suite for zero
      critical violations; manual keyboard + screen-reader pass before merge.

## 9. Build configuration for the static bundle

- `package.json` scripts (names are the CI contract):
  - `"lint": "eslint ."`
  - `"typecheck": "tsc --noEmit"`
  - `"build:web": "<expo export / webpack> && <ensure output at web-build/>"`
  - `"test": "jest"`
- Output dir **`webapp/web-build/`** (matches workflow artifact + future S3 sync).
- TypeScript `strict: true`.
- Asset filenames content-hashed for cache-busting (supports NFR-6).

## 10. CloudFront / S3 hardening (NFR-4)

- S3 bucket `reticle-webapp-prod`: **Block Public Access ON**, no bucket-policy public
  read; access only via CloudFront **Origin Access Control (OAC)**.
- CloudFront: viewer protocol policy **redirect-to-HTTPS**; ACM cert; attach a
  response-headers policy adding `Strict-Transport-Security`,
  `Content-Security-Policy` (allow self + the API origin + `use.typekit.net`),
  `X-Content-Type-Options: nosniff`, `Referrer-Policy`.
- SPA routing: custom error responses map 403/404 → `/index.html` (200) so client
  routing works.
- Deploy step (to replace the workflow placeholder): `aws s3 sync web-build/
  s3://reticle-webapp-prod --delete` then `aws cloudfront create-invalidation
  --paths "/*"`. Set `S3_BUCKET` / `CLOUDFRONT_DISTRIBUTION_ID` in the workflow `env`
  once provisioned. **This is config-engineer work, not in the app code.**

## 11. OWASP Top 10 (client-side relevant)

| Risk | Mitigation |
|---|---|
| A01 Access Control | No auth/secrets in the bundle; only public greeting fetched |
| A02 Crypto Failures | HTTPS only via CloudFront; HSTS; no secrets in `REACT_APP_*` |
| A03 Injection / XSS | React escapes by default; render only the `message` string, never `dangerouslySetInnerHTML`; CSP as defense-in-depth |
| A05 Misconfiguration | Private S3 + OAC; security response headers; no source maps with secrets shipped |
| A06 Vulnerable Components | `npm audit --audit-level=high` + Trivy in CI gate |
| A08 Integrity | CI builds + deploys only from `main`; CloudFront serves immutable hashed assets |
| A09 Logging | Errors surfaced to the user are generic; no PII; no client-side logging of the API base or responses to third parties |

## 12. Confirmed / open items

- **Confirmed:** S3 + CloudFront is the deploy target.
- **Open:** product name / footer copy and link targets for Header/Footer (placeholder
  text acceptable for this task — confirm final wording with the product owner).
- **Open:** exact CSP source list once the API origin (ALB/API-GW domain) from Task #24
  is finalized.
