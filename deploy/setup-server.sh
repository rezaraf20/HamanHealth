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
  git -C "$REPO_DIR" fetch origin
  git -C "$REPO_DIR" checkout platform
  git -C "$REPO_DIR" pull origin platform
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

# ── 4. Copy Apache vhost ──────────────────────────────────────────────────────
APACHE_CONF_DIR="/etc/httpd/conf.d"
if [ -d "$APACHE_CONF_DIR" ]; then
  cp "$REPO_DIR/deploy/apache-api.hamanhealth.com.conf" "$APACHE_CONF_DIR/"
  echo "Apache vhost installed. After DNS propagates, run:"
  echo "  certbot --apache -d api.hamanhealth.com"
  echo "Then: systemctl reload httpd"
else
  echo "Apache conf.d not found at $APACHE_CONF_DIR — copy manually."
fi

echo ""
echo "=== Done! API will be live at https://api.hamanhealth.com ==="
echo "Health check: curl http://127.0.0.1:8002/api/health"
