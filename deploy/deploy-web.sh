#!/usr/bin/env bash
# Builds the Haman Health web SPA and deploys it to hamanhealth.com.
#
# This runs on the Hetzner server (128.140.54.86, root).
# The SPA is served as static files from the DirectAdmin public_html directory.
#
# Usage: bash deploy/deploy-web.sh
# Run after: bash deploy/setup-server.sh  (sets up the API)

set -euo pipefail

REPO_DIR="/opt/hamanhealth"
WEB_DIR="$REPO_DIR/web"
BUILD_OUT="$WEB_DIR/.output/public"      # TanStack Start SPA output
DA_USER="hamanhea"
PUBLIC_HTML="/home/${DA_USER}/domains/hamanhealth.com/public_html"
CUST_HTTPD="/home/${DA_USER}/domains/hamanhealth.com/cust_httpd"
DOMAIN="hamanhealth.com"
MARKER="# haman-web static — DO NOT REMOVE"

echo "=== Haman Health — web deploy ==="

# ── 1. Ensure bun is available ────────────────────────────────────────────────
if ! command -v bun &>/dev/null; then
  echo "Installing bun..."
  curl -fsSL https://bun.sh/install | bash
  export PATH="$HOME/.bun/bin:$PATH"
fi
echo "bun: $(bun --version)"

# ── 2. Install deps ───────────────────────────────────────────────────────────
echo "Installing web dependencies..."
(cd "$WEB_DIR" && bun install --frozen-lockfile)

# ── 3. Build production SPA ───────────────────────────────────────────────────
echo "Building production SPA..."
(cd "$WEB_DIR" && VITE_API_BASE_URL=https://api.hamanhealth.com/api \
                  VITE_USE_MOCKS=false \
                  bun run build)

if [ ! -d "$BUILD_OUT" ]; then
  echo "Build output not found at $BUILD_OUT — build may have failed."
  exit 1
fi

echo "Build complete. Files in $BUILD_OUT:"
ls "$BUILD_OUT" | head -20

# ── 4. Sync to public_html ────────────────────────────────────────────────────
echo "Syncing to $PUBLIC_HTML..."
# rsync: delete files not in source, preserve permissions, skip git internals
rsync -av --delete \
  --exclude='.git' \
  --exclude='.env*' \
  "$BUILD_OUT/" "$PUBLIC_HTML/"
chown -R "${DA_USER}:${DA_USER}" "$PUBLIC_HTML"

echo "Web files deployed to $PUBLIC_HTML"

# ── 5. Ensure SPA routing (mod_rewrite) in cust_httpd ────────────────────────
if grep -qF "$MARKER" "$CUST_HTTPD" 2>/dev/null; then
  echo "SPA routing rules already in $CUST_HTTPD — skipping."
else
  echo "Adding SPA routing rules to $CUST_HTTPD..."
  cat >> "$CUST_HTTPD" <<BLOCK

${MARKER}
# Serve hamanhealth.com as a static SPA (TanStack Start, Capacitor web layer)
# All non-file requests fall back to index.html for client-side routing.
<VirtualHost *:80>
    ServerName ${DOMAIN}
    ServerAlias www.${DOMAIN}
    DocumentRoot ${PUBLIC_HTML}
    # HTTP → HTTPS redirect
    RewriteEngine On
    RewriteRule ^ https://%{SERVER_NAME}%{REQUEST_URI} [R=301,L]
</VirtualHost>

<VirtualHost *:443>
    ServerName ${DOMAIN}
    ServerAlias www.${DOMAIN}
    DocumentRoot ${PUBLIC_HTML}

    SSLEngine on
    SSLCertificateFile    /usr/local/directadmin/data/users/${DA_USER}/domains/${DOMAIN}.cert
    SSLCertificateKeyFile /usr/local/directadmin/data/users/${DA_USER}/domains/${DOMAIN}.key
    SSLCACertificateFile  /usr/local/directadmin/data/users/${DA_USER}/domains/${DOMAIN}.cacert

    # SPA fallback: route all non-file, non-directory requests to index.html
    <Directory ${PUBLIC_HTML}>
        Options -Indexes +FollowSymLinks
        AllowOverride None
        Require all granted

        RewriteEngine On
        RewriteCond %{REQUEST_FILENAME} !-f
        RewriteCond %{REQUEST_FILENAME} !-d
        RewriteRule ^ /index.html [L]
    </Directory>

    # Cache control for immutable hashed assets
    <FilesMatch "\.(js|css|woff2?|png|svg|ico|webp)$">
        Header set Cache-Control "public, max-age=31536000, immutable"
    </FilesMatch>
    <FilesMatch "index\.html$">
        Header set Cache-Control "no-cache, no-store, must-revalidate"
    </FilesMatch>

    Header always set X-Frame-Options "SAMEORIGIN"
    Header always set X-Content-Type-Options "nosniff"
    Header always set Referrer-Policy "strict-origin-when-cross-origin"

    ErrorLog  /var/log/httpd/${DOMAIN}-error.log
    CustomLog /var/log/httpd/${DOMAIN}-access.log combined
</VirtualHost>
BLOCK

  echo "SPA routing rules added."
fi

# ── 6. Reload Apache ──────────────────────────────────────────────────────────
if systemctl is-active --quiet httpd 2>/dev/null; then
  systemctl reload httpd
  echo "Apache reloaded."
elif systemctl is-active --quiet lsws 2>/dev/null; then
  /usr/local/lsws/bin/lswsctrl restart
  echo "LiteSpeed restarted."
fi

echo ""
echo "=== Done! Web app deployed ==="
echo "Visit: https://${DOMAIN}"
echo "API:   https://api.${DOMAIN}/api/health"
