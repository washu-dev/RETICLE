# Branch Naming Conventions

All branches follow GitFlow. This table is the authoritative reference.

| Pattern | Source | Merges into | Purpose |
|---|---|---|---|
| `main` | — | — | Production. Protected. Only release and hotfix branches merge here. |
| `develop` | — | — | Integration branch. Default target for all feature work. |
| `feature/<asana-id>-<slug>` | `develop` | `develop` | One branch per Asana backlog task. Kebab-case slug. |
| `bugfix/<asana-id>-<slug>` | `develop` | `develop` | Bug fix tracked in Asana. |
| `release/<version>` | `develop` | `main` + `develop` | Stabilization only — no new features after cut. |
| `hotfix/<version>-<slug>` | `main` | `main` + `develop` | Critical production fix. |
| `chore/<slug>` | `develop` | `develop` | Non-functional work (deps, tooling, docs). |

## Rules

- Branch names are **kebab-case** only — no underscores, no camelCase.
- Include the Asana task ID where one exists: `feature/24-fastapi-api`.
- The config-engineer cuts all branches from the correct source — do not
  create branches manually from an arbitrary commit.
- Never push directly to `main` or `develop`. Open a pull request and get
  at least one approval.
- CI runs on every push to any branch (path-filtered to the relevant
  service directory). Deployments run only on merges to `main`.

## Required GitHub Secrets

Set these in the repository's Settings > Secrets and variables > Actions
before the deploy stage will function:

| Secret | Used by |
|---|---|
| `AWS_ACCESS_KEY_ID` | Both workflows |
| `AWS_SECRET_ACCESS_KEY` | Both workflows |
| `REACT_APP_API_BASE_URL` | webapp workflow (build step) |
