# Deployment

## Goal

Phase 14 deploys the app to a VPS behind nginx with TLS, while keeping Docker Compose as
the process boundary for the FastAPI app, Qdrant, and PostgreSQL.

This repository now includes:

- hardened `Dockerfile`
- `docker-compose.yml` for the full stack
- `docker-compose.prod.yml` for prebuilt-image deploys
- `.env.production.example`
- `deploy/nginx.conf`
- `deploy/voice-commerce.service`
- `.github/workflows/deploy.yml`

## Recommended target

- Ubuntu 24.04 VPS
- Docker Engine with Compose plugin
- nginx on the host machine
- domain name pointed at the VPS public IP
- TLS certificates managed by certbot

## Files and roles

- `Dockerfile`: production image build
- `docker-compose.yml`: base app, Qdrant, PostgreSQL stack
- `docker-compose.prod.yml`: adds the pushed GHCR image and pull policy for VPS deploys
- `.env.production.example`: production env template
- `deploy/nginx.conf`: reverse proxy with WebSocket support
- `deploy/voice-commerce.service`: systemd unit for the compose stack
- `.github/workflows/deploy.yml`: test, build, push, and remote deploy workflow

## Prepare the VPS

Install Docker and nginx, then clone the repository:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg nginx certbot python3-certbot-nginx git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER

sudo mkdir -p /opt/voice-commerce-agent
sudo chown "$USER":"$USER" /opt/voice-commerce-agent
git clone https://github.com/YOUR_ORG/voice-commerce-agent.git /opt/voice-commerce-agent
cd /opt/voice-commerce-agent
```

Create the production env file:

```bash
cp .env.production.example .env.production
```

Fill in at minimum:

- `GEMINI_API_KEY`
- `ADMIN_API_KEY`
- `POSTGRES_PASSWORD`
- `CORS_ALLOW_ORIGINS`
- `DEMO_TENANT_API_KEY` or your real tenant values

## Start the stack locally on the VPS

For first deployment, you can build on the VPS directly:

```bash
docker compose --env-file .env.production up -d --build
```

Verify:

```bash
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/ready
curl --fail -H "X-Admin-Key: $ADMIN_API_KEY" http://127.0.0.1:8000/metrics
```

## nginx setup

Copy `deploy/nginx.conf` to `/etc/nginx/sites-available/voice-commerce` and update:

- `server_name`
- TLS certificate paths

Enable it:

```bash
sudo ln -s /etc/nginx/sites-available/voice-commerce /etc/nginx/sites-enabled/voice-commerce
sudo nginx -t
sudo systemctl reload nginx
```

The critical WebSocket directives are already included:

```nginx
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection $connection_upgrade;
```

## TLS with certbot

After DNS points at the VPS:

```bash
sudo certbot --nginx -d voice.example.com
```

Then reload nginx.

## systemd service

Install the unit file:

```bash
sudo cp deploy/voice-commerce.service /etc/systemd/system/voice-commerce.service
sudo systemctl daemon-reload
sudo systemctl enable voice-commerce.service
sudo systemctl start voice-commerce.service
```

The service expects:

- repo path: `/opt/voice-commerce-agent`
- env file: `/opt/voice-commerce-agent/.env.production`

It pulls the prebuilt app image first, then runs Compose with `--no-build`.

Adjust the unit if your deployment path differs.

## GitHub Actions deploy

The included workflow builds and pushes an image to GHCR, then deploys over SSH.

Required repository secrets:

- `VPS_HOST`
- `VPS_USER`
- `VPS_SSH_KEY`
- `VPS_DEPLOY_PATH`
- `GHCR_USER`
- `GHCR_PAT`

Expected remote shape:

- repository cloned at `$VPS_DEPLOY_PATH`
- `.env.production` present there
- Docker already installed

The workflow will:

1. run Ruff
2. run non-integration tests
3. build and push the image to GHCR
4. SSH into the VPS
5. `git checkout` the deployed commit
6. `docker compose pull app`
7. `docker compose up -d --no-build`
8. hit `/health` and `/ready`

## Smoke test checklist

After deployment, verify:

1. `https://voice.example.com/health`
2. `https://voice.example.com/ready`
3. `https://voice.example.com/static/widget.js`
4. WebSocket connect to `wss://voice.example.com/ws/voice`
5. one text query
6. one audio query
7. one product search
8. one add-to-cart action
9. one checkout flow
10. `curl -H "X-Admin-Key: ..." https://voice.example.com/metrics`
11. `curl -H "X-Admin-Key: ..." https://voice.example.com/admin/usage`

Expected results:

- `/ready` reports ready
- widget loads cross-origin from the storefront
- WebSocket survives nginx proxying
- metrics and usage counters increase
- active session gauge returns to zero after disconnect

## Notes

- `APP_DEBUG=false` is the intended production default.
- `ENABLE_PUBLIC_DEMO=false` keeps the demo storefront off public deployments.
- `METRICS_REQUIRE_ADMIN_KEY=true` should remain enabled outside local debug.
- `CORS_ALLOW_ORIGINS` should be a real allowlist, not `[*]`.
- `docker-compose.yml` keeps PostgreSQL and Qdrant private to the compose network.
