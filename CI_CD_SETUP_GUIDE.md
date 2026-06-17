# CI/CD Setup Guide for RETICLE

Comprehensive, reproducible checklist for implementing CI/CD pipelines for FastAPI APIs and React web apps.

## Overview

This guide documents the exact pattern used to set up CI/CD for:
- **API**: FastAPI 0.104.1 + Python 3.12 (App Engine / ECS Express)
- **Webapp**: React 18.2.0 + TypeScript (CloudFront + S3)

Both follow a consistent pattern: **Build → Test → Scan → Deploy**

---

## Part A: Prerequisites & AWS/GCP Setup

### 1. AWS Infrastructure (for API deployment to ECS Express)

Required resources:
- **ECR Repository**: `reticle-api` (store Docker images)
- **ECS Cluster**: `reticle-cluster` (or `default`)
- **ECS Service**: `reticle-api-service` (or `reticle-api-c7e2` for ECS Express)
- **ECS Task Definition**: `reticle-api-task`

Optional (if using EC2):
- EC2 instances in cluster
- ALB with health check on `/health` endpoint

For ECS Express (managed, no EC2):
- Service automatically manages container orchestration
- Service endpoint: `https://<service-name>.ecs.<region>.on.aws/`

### 2. AWS Infrastructure (for Webapp deployment to CloudFront)

Required resources:
- **S3 Bucket**: `reticle-webapp-prod` (store built webapp)
- **CloudFront Distribution**: `EAV26T9QAOA4Q` (CDN, points to S3)
- **S3 Bucket Policy**: Allow public GetObject for CloudFront (or authenticated access)
- **CloudFront Default Root Object**: Set to `index.html`

### 3. GitHub Secrets (must be set in repository settings)

```
AWS_ACCESS_KEY_ID          # AWS IAM user with ECR/ECS/S3/CloudFront permissions
AWS_SECRET_ACCESS_KEY      # AWS IAM user secret key
REACT_APP_API_BASE_URL     # API endpoint (e.g., https://api.example.com or ECS endpoint)
```

### 4. File Structure

```
repo-root/
├── .github/
│   └── workflows/
│       ├── api-ci-cd.yml          # API pipeline
│       └── webapp-ci-cd.yml        # Webapp pipeline
├── api/
│   ├── main.py
│   ├── requirements.txt
│   ├── tests/
│   │   ├── conftest.py            # CRITICAL: pytest fixture setup
│   │   └── test_main.py
│   ├── Dockerfile
│   └── .dockerignore
├── webapp/
│   ├── package.json
│   ├── webpack.config.js
│   ├── public/
│   │   └── index.html
│   ├── src/
│   │   └── index.web.tsx
│   └── .env.production
├── VERSION                         # Version file (e.g., 2026.06.17.001)
└── CI_CD_SETUP_GUIDE.md           # This file
```

---

## Part B: API Pipeline Setup (FastAPI)

### Step 1: Create `api/requirements.txt`

```txt
fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.0
pydantic-settings==2.1.0
python-dotenv==1.0.0
httpx==0.24.1
```

**Critical**: Pin `httpx==0.24.1` to match starlette API (TestClient compatibility).

### Step 2: Create `api/Dockerfile`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Step 3: Create `api/tests/conftest.py`

```python
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app


@pytest.fixture(scope="session")
def client() -> TestClient:
    """Provide TestClient for all tests."""
    return TestClient(app)
```

**Why this is critical**: 
- Ensures Python path includes parent directory (so `from main import app` works)
- Provides shared TestClient fixture for all tests
- `scope="session"` avoids recreating client per test

### Step 4: Create `api/tests/test_main.py`

Example test structure:

```python
import pytest
from fastapi.testclient import TestClient


class TestHealth:
    def test_health_check(self, client: TestClient) -> None:
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "reticle-api-server"
        assert "version" in data


class TestLogin:
    def test_login_success(self, client: TestClient) -> None:
        payload = {"username": "testuser", "password": "testpass", "scopes": []}
        response = client.post("/api/login", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "Bearer"

    def test_login_missing_username(self, client: TestClient) -> None:
        payload = {"username": "", "password": "testpass"}
        response = client.post("/api/login", json=payload)
        assert response.status_code == 401
```

### Step 5: Create `api/main.py`

Minimal example:

```python
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class LoginRequest(BaseModel):
    username: str
    password: str
    scopes: list[str] = []


class LoginResponse(BaseModel):
    access_token: str
    token_type: str


app = FastAPI(
    title="API",
    description="Your API",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthResponse)
@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="healthy",
        service="reticle-api-server",
        version="0.1.0",
    )


@app.post("/api/login", response_model=LoginResponse)
async def login(request: LoginRequest) -> LoginResponse:
    if not request.username or not request.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    return LoginResponse(
        access_token=f"placeholder_token_for_{request.username}",
        token_type="Bearer",
    )
```

**Critical Details**:
- Endpoints: `/api/health` AND `/health` (ALB needs `/health` for health checks)
- Response models: Use Pydantic BaseModel for validation
- CORS: Allow all origins for dev/demo (restrict in production)

### Step 6: Create `.github/workflows/api-ci-cd.yml`

```yaml
name: API CI/CD

on:
  push:
    branches:
      - main
    paths:
      - 'api/**'
      - '.github/workflows/api-ci-cd.yml'
  workflow_dispatch:

env:
  AWS_REGION: us-east-1
  ECR_REPOSITORY: reticle-api
  ECS_CLUSTER: default
  ECS_EXPRESS_SERVICE: reticle-api-c7e2

jobs:
  build:
    name: Build
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: api

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'

      - run: |
          pip install -r requirements.txt
          pip install ruff mypy pytest pytest-asyncio httpx

      - name: Lint with ruff
        run: ruff check .

      - name: Typecheck with mypy
        run: mypy . --ignore-missing-imports

      - name: Run tests
        run: pytest tests/ -v

  security:
    name: Security Scan
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: api

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install Bandit
        run: pip install bandit[toml]

      - name: Run Bandit (SAST)
        run: bandit -r . -x ./tests -ll

      - name: Run Trivy (Filesystem scan)
        uses: aquasecurity/trivy-action@master
        with:
          scan-type: fs
          scan-ref: api/
          exit-code: '1'
          severity: CRITICAL,HIGH

  deploy:
    name: Deploy to ECS Express
    runs-on: ubuntu-latest
    needs: [build, security]
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    environment: production

    steps:
      - uses: actions/checkout@v4

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: ${{ env.AWS_REGION }}

      - name: Login to Amazon ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2

      - name: Build and push Docker image
        env:
          ECR_REGISTRY: ${{ steps.login-ecr.outputs.registry }}
          IMAGE_TAG: ${{ github.sha }}
        run: |
          cd api
          docker build -t $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG .
          docker tag $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG $ECR_REGISTRY/$ECR_REPOSITORY:latest
          docker push $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG
          docker push $ECR_REGISTRY/$ECR_REPOSITORY:latest
          echo "Image pushed: $ECR_REGISTRY/$ECR_REPOSITORY:latest"

      - name: Update ECS service
        run: |
          aws ecs update-service \
            --cluster ${{ env.ECS_CLUSTER }} \
            --service ${{ env.ECS_EXPRESS_SERVICE }} \
            --force-new-deployment \
            --region ${{ env.AWS_REGION }}

      - name: Wait for stable deployment
        run: |
          for i in {1..30}; do
            RUNNING=$(aws ecs describe-services \
              --cluster ${{ env.ECS_CLUSTER }} \
              --services ${{ env.ECS_EXPRESS_SERVICE }} \
              --region ${{ env.AWS_REGION }} \
              --query 'services[0].runningCount' --output text)
            DESIRED=$(aws ecs describe-services \
              --cluster ${{ env.ECS_CLUSTER }} \
              --services ${{ env.ECS_EXPRESS_SERVICE }} \
              --region ${{ env.AWS_REGION }} \
              --query 'services[0].desiredCount' --output text)
            if [ "$RUNNING" = "$DESIRED" ] && [ "$RUNNING" = "1" ]; then
              echo "✓ Deployment stable: $RUNNING/$DESIRED tasks running"
              exit 0
            fi
            echo "Attempt $i: $RUNNING/$DESIRED tasks running..."
            sleep 10
          done
          echo "✗ Deployment timeout"
          exit 1
```

**Pipeline Stages**:
1. **Build**: Installs deps, runs ruff lint, mypy type check, pytest tests
2. **Security**: Bandit SAST + Trivy filesystem scan (both blocking on CRITICAL/HIGH)
3. **Deploy**: Builds Docker image, pushes to ECR, updates ECS service, waits for stability

**All failures block deployment** (no `|| true` bypasses).

---

## Part C: Webapp Pipeline Setup (React + Webpack)

### Step 1: Create `webapp/webpack.config.js`

```javascript
const path = require("path");
const HtmlWebpackPlugin = require("html-webpack-plugin");
const webpack = require("webpack");

module.exports = {
  entry: "./src/index.web.tsx",
  output: {
    path: path.resolve(__dirname, "web-build"),
    filename: "static/js/[name].[contenthash].js",
    clean: true,
  },
  resolve: {
    alias: {
      "react-native$": "react-native-web",
    },
    extensions: [".web.tsx", ".web.ts", ".web.js", ".tsx", ".ts", ".js"],
  },
  module: {
    rules: [
      {
        test: /\.(tsx?|jsx?)$/,
        exclude: /node_modules/,
        use: {
          loader: "babel-loader",
        },
      },
    ],
  },
  plugins: [
    new HtmlWebpackPlugin({
      template: "./public/index.html",
    }),
    new webpack.DefinePlugin({
      "process.env.REACT_APP_API_BASE_URL": JSON.stringify(
        process.env.REACT_APP_API_BASE_URL || "http://localhost:8000"
      ),
    }),
  ],
  devServer: {
    port: 3001,
    hot: true,
    open: true,
  },
};
```

**Critical**: `webpack.DefinePlugin` injects environment variables at **build time**, not runtime. This prevents "process is not defined" errors.

### Step 2: Create `webapp/.env.production`

```bash
REACT_APP_API_BASE_URL=https://api.example.com
```

This file is auto-generated by the deploy script. **Never commit this file with secrets.**

### Step 3: Create `webapp/package.json`

Key scripts:

```json
{
  "name": "reticle-webapp",
  "version": "0.1.0",
  "scripts": {
    "build:web": "webpack --mode production",
    "start": "webpack serve --mode development",
    "lint": "eslint src --ext .ts,.tsx",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "react": "18.2.0",
    "react-dom": "18.2.0",
    "react-native": "^0.72.0",
    "react-native-web": "^0.18.0",
    "typescript": "^5.0.0"
  },
  "devDependencies": {
    "@babel/core": "^7.22.0",
    "@babel/preset-env": "^7.22.0",
    "@babel/preset-react": "^7.22.0",
    "@babel/preset-typescript": "^7.22.0",
    "babel-loader": "^9.1.0",
    "html-webpack-plugin": "^5.5.0",
    "webpack": "^5.88.0",
    "webpack-cli": "^5.1.0",
    "webpack-dev-server": "^4.15.0"
  }
}
```

### Step 4: Create `.github/workflows/webapp-ci-cd.yml`

```yaml
name: Webapp CI/CD

on:
  push:
    branches:
      - main
    paths:
      - 'webapp/**'
      - '.github/workflows/webapp-ci-cd.yml'
  workflow_dispatch:

env:
  AWS_REGION: us-east-1
  S3_BUCKET: reticle-webapp-prod
  CLOUDFRONT_DISTRIBUTION_ID: EAV26T9QAOA4Q

jobs:
  build:
    name: Build
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: webapp

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: npm
          cache-dependency-path: webapp/package-lock.json

      - run: npm ci

      - name: Lint
        run: npm run lint --if-present || true

      - name: Type check
        run: npm run typecheck --if-present || true

      - name: Build web bundle
        env:
          REACT_APP_API_BASE_URL: ${{ secrets.REACT_APP_API_BASE_URL }}
        run: npm run build:web

      - name: Upload artifact
        id: artifact
        uses: actions/upload-artifact@v4
        with:
          name: webapp-build
          path: webapp/web-build/
          retention-days: 1

  deploy:
    name: Deploy to CloudFront
    runs-on: ubuntu-latest
    needs: build
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    environment: production

    steps:
      - name: Download build artifact
        uses: actions/download-artifact@v4
        with:
          name: webapp-build
          path: web-build/

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: ${{ env.AWS_REGION }}

      - name: Deploy to S3
        run: |
          aws s3 sync web-build/ s3://${{ env.S3_BUCKET }}/ --delete

      - name: Invalidate CloudFront
        run: |
          aws cloudfront create-invalidation \
            --distribution-id ${{ env.CLOUDFRONT_DISTRIBUTION_ID }} \
            --paths "/*"
```

**Pipeline Stages**:
1. **Build**: Install deps, lint (non-blocking), typecheck (non-blocking), webpack build, upload artifact
2. **Deploy**: Download artifact, sync to S3, invalidate CloudFront cache

---

## Part D: Common Pitfalls & Solutions

### API Tests Failing

**Problem**: `TypeError: Client.__init__() got an unexpected keyword argument 'app'`

**Root Cause**: httpx version mismatch with starlette

**Solution**: Pin `httpx==0.24.1` in requirements.txt (see Part B, Step 1)

---

### Tests Not Finding Fixtures

**Problem**: `fixture 'client' not found`

**Root Cause**: Missing conftest.py or incorrect Python path

**Solution**: Create `api/tests/conftest.py` with path setup (see Part B, Step 3)

---

### Environment Variables Not Injected

**Problem**: JavaScript error "process is not defined"

**Root Cause**: Environment variables not injected at build time

**Solution**: Use webpack.DefinePlugin (see Part C, Step 1)

---

### ALB Returns 503 Service Unavailable

**Problem**: Health check fails with 404

**Root Cause**: ALB configured to check `/health`, but app only has `/api/health`

**Solution**: Add both endpoints to app (see Part B, Step 5)

---

### S3/CloudFront Returns 403 Forbidden

**Problem**: XML AccessDenied error from S3

**Root Cause**: Missing S3 bucket policy or Block Public Access enabled

**Solution**:
1. Disable S3 Block Public Access for the bucket
2. Add bucket policy:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::reticle-webapp-prod/*"
    }
  ]
}
```
3. Set CloudFront default root object to `index.html`

---

### Docker Build Fails in CI

**Problem**: Docker not available or context issues

**Solution**:
- Use `docker build -t $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG ./api` (specify context)
- Tag as both SHA and latest: push both `$IMAGE_TAG` and `latest`

---

## Part E: Validation Checklist

After implementing both pipelines, verify:

### API Pipeline
- [ ] Push triggers workflow on changes to `api/**`
- [ ] Ruff lint runs and fails on violations
- [ ] Mypy type check runs
- [ ] Pytest discovers and runs all tests
- [ ] Bandit SAST scans Python code
- [ ] Trivy scans filesystem for vulnerabilities
- [ ] All scans block on CRITICAL/HIGH
- [ ] Docker image builds successfully
- [ ] ECR image push succeeds
- [ ] ECS service updates and stabilizes
- [ ] Health endpoint responds at `/health` and `/api/health`

### Webapp Pipeline
- [ ] Push triggers workflow on changes to `webapp/**`
- [ ] NPM CI installs dependencies
- [ ] Webpack build succeeds
- [ ] REACT_APP_API_BASE_URL injected at build time
- [ ] Artifact uploaded to S3
- [ ] CloudFront cache invalidated
- [ ] Webapp loads at CloudFront URL
- [ ] API calls hit correct endpoint

---

## Part F: Reproducible Pattern Summary

To apply this to new apps, follow in order:

1. **Prerequisites**: Set up AWS/GCP resources, GitHub secrets
2. **Dependencies**: Pin exact versions (fastapi, httpx, react, etc.)
3. **Tests**: Create conftest.py + test files (use TestClient for APIs)
4. **Build Tools**: Create Dockerfile or webpack.config.js
5. **Workflow**: Copy template workflow, update env vars and service names
6. **Security**: Add Bandit + Trivy to API, lint + typecheck to webapp
7. **Deploy**: S3/CloudFront for web, ECR/ECS for API
8. **Validation**: Run through checklist, fix any failures

**Key Principles**:
- All failures block deployment (no `|| true` bypasses)
- Security scans are mandatory, not optional
- Environment variables injected at build time (not runtime)
- Pin dependency versions for reproducibility
- Use conftest.py for shared test fixtures
- Separate build, test, security, and deploy stages
