#!/usr/bin/env bash
# Run once on the Hetzner server as root to bootstrap haman-health backend
# Usage: bash setup-server.sh

set -euo pipefail

REPO_DIR="/opt/hamanhealth"
ENV_FILE="$REPO_DIR/deploy/.env"

echo "=== Haman Health — server bootstrap ==="

# ── 1. Clone / update repo ────────────────────────────────────────────────────
if [ -d "$REPO_DIR/.git" ]; then
  echo "Repo exists — pulling platform branch..."
  (cd "$REPO_DIR" && git fetch origin && git checkout platform && git pull origin platform)
else
  echo "Cloning repo..."
  git clone --branch platform https://github.com/rezaraf20/hamanhealth "$REPO_DIR"
fi

# ── 2. Create .env if missing ─────────────────────────────────────────────────
if [ ! -f "$ENV_FILE" ]; then
  echo "Creating .env (you MUST update the secrets!)..."
  cat > "$ENV_FILE" <<EOF
HAMAN_DB_PASS=$(openssl rand -hex 24)
HAMAN_SECRET_KEY=$(openssl rand -hex 32)
EOF
  echo ">>> .env created at $ENV_FILE — save these values somewhere safe!"
  cat "$ENV_FILE"
fi

# ── 3. Start containers ───────────────────────────────────────────────────────
echo "Starting Docker containers..."
docker compose -f "$REPO_DIR/deploy/docker-compose.haman.yml" --env-file "$ENV_FILE" up -d --build

# ── 4. Set up reverse proxy vhost ────────────────────────────────────────────
# This server uses DirectAdmin's cust_httpd pattern, NOT /etc/httpd/conf.d/.
# Wildcard cert *.hamanhealth.com is already installed (valid Dec 2026).
# Run the proxy setup script if this is the first deploy:
if ! grep -qF "haman-api proxy" /home/hamanhea/domains/hamanhealth.com/cust_httpd 2>/dev/null; then
  bash "$REPO_DIR/deploy/directadmin-proxy-setup.sh"
else
  echo "Proxy vhost already configured — skipping."
fi

echo ""
echo "=== Done! API will be live at https://api.hamanhealth.com ==="
echo "Health check: curl http://127.0.0.1:8002/api/health"
echo ""
echo "Next: deploy the web app:"
echo "  bash $REPO_DIR/deploy/deploy-web.sh"
