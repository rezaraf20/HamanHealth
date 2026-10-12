#!/usr/bin/env bash
# Deploys the pre-built Haman Health web SPA to app.hamanhealth.com.
#
# WHY PRE-BUILT: The server runs Node 16; vite requires Node 18+.
# Build on your dev machine, then upload the static output here.
#
# ── Build on your machine ────────────────────────────────────────────────────
#   cd web
#   bun install
#   VITE_API_BASE_URL=https://api.hamanhealth.com/api VITE_USE_MOCKS=false bun run build
#   # Output lands in: web/.output/public/
#
# ── Upload to server ─────────────────────────────────────────────────────────
#   scp -P 2025 -r web/.output/public/ root@128.140.54.86:/tmp/haman-web-build/
#   # Then on the server:
#   bash /opt/hamanhealth/deploy/deploy-web.sh /tmp/haman-web-build
#
# Usage: bash deploy/deploy-web.sh [BUILD_DIR]
#   BUILD_DIR: path to the pre-built static files (default: /tmp/haman-web-build)

set -euo pipefail

BUILD_DIR="${1:-/tmp/haman-web-build}"
DA_USER="hamanhea"
DA_DOMAIN="hamanhealth.com"
APP_SUBDOMAIN="app.hamanhealth.com"
PUBLIC_HTML="/home/${DA_USER}/domains/${APP_SUBDOMAIN}/public_html"
MARKER="# haman-app.hamanhealth.com — DO NOT REMOVE"

echo "=== Haman Health — web deploy to ${APP_SUBDOMAIN} ==="

# ── Find the actual build root (handle scp with/without trailing slash) ───────
# scp -r dir/  → contents land directly in dest
# scp -r dir   → a subdir is created inside dest
#
# After upload the layout can be:
#   /tmp/haman-web-build/index.html          (trailing-slash scp, correct)
#   /tmp/haman-web-build/public/index.html   (no trailing slash or nested)
#
# Walk down until we find index.html (max 2 levels).
find_build_root() {
  local dir="$1"
  if [ -f "$dir/index.html" ]; then
    echo "$dir"
    return
  fi
  for sub in "$dir"/*/; do
    if [ -f "${sub}index.html" ]; then
      echo "${sub%/}"
      return
    fi
  done
  echo ""
}

BUILD_ROOT=$(find_build_root "$BUILD_DIR")

if [ -z "$BUILD_ROOT" ]; then
  echo "ERROR: Could not find index.html inside $BUILD_DIR (checked 2 levels)."
  echo ""
  echo "Build the app on your dev machine first:"
  echo "  cd web"
  echo "  bun install"
  echo "  VITE_API_BASE_URL=https://api.hamanhealth.com/api VITE_USE_MOCKS=false bun run build"
  echo ""
  echo "Then upload:"
  echo "  scp -P 2025 -r web/.output/public/ root@128.140.54.86:/tmp/haman-web-build/"
  echo "  ssh -p 2025 root@128.140.54.86 'bash /opt/hamanhealth/deploy/deploy-web.sh /tmp/haman-web-build'"
  exit 1
fi

echo "Build root: $BUILD_ROOT"
echo "index.html entry JS: $(grep -o 'index-[A-Za-z0-9_-]*\.js' "$BUILD_ROOT/index.html" | head -1)"

# ── Ensure subdomain public_html exists ───────────────────────────────────────
if [ ! -d "$PUBLIC_HTML" ]; then
  echo "ERROR: $PUBLIC_HTML does not exist."
  echo "Create the subdomain app.hamanhealth.com in DirectAdmin first."
  exit 1
fi

# ── Sync static files ─────────────────────────────────────────────────────────
echo "Syncing static files to $PUBLIC_HTML..."
rsync -a --delete \
  --exclude='.git' \
  --exclude='.env*' \
  "${BUILD_ROOT}/" "$PUBLIC_HTML/"
chown -R "${DA_USER}:${DA_USER}" "$PUBLIC_HTML"

# ── Verify the right index.html landed ────────────────────────────────────────
DEPLOYED_ENTRY=$(grep -o 'index-[A-Za-z0-9_-]*\.js' "$PUBLIC_HTML/index.html" | head -1)
echo "Deployed index.html entry JS: $DEPLOYED_ENTRY"

# ── Build clean SPA shell from deployed index.html ───────────────────────────
# TanStack Start prerenders the app and uses <Scripts /> which only works with
# a running Node server. On static Apache, React never boots. Fix: extract the
# entry JS from modulepreload links and inject it explicitly into <body>.
INDEX="$PUBLIC_HTML/index.html"
python3 - "$INDEX" <<'PYEOF'
import sys, re

path = sys.argv[1]
html = open(path).read()

# Find entry JS from modulepreload (index-HASH.js pattern)
entry_href = None
for tag in re.findall(r'<link[^>]+modulepreload[^>]*>', html):
    m = re.search(r'href=["\']([^"\']*?/index-[^"\']+\.js)["\']', tag)
    if m:
        entry_href = m.group(1)
        break

if not entry_href:
    # fallback: any modulepreload JS that looks like the main bundle
    for tag in re.findall(r'<link[^>]+modulepreload[^>]*>', html):
        m = re.search(r'href=["\']([^"\']+\.js)["\']', tag)
        if m:
            entry_href = m.group(1)
            break

script_tag = ('<script type="module" src="' + entry_href + '"></script>') if entry_href else '<!-- ERROR: no entry script found -->'

# Replace body content with empty root + entry script
html = re.sub(
    r'(<body[^>]*>).*?(</body>)',
    r'\1\n    <div id="root"></div>\n    ' + script_tag + r'\n  \2',
    html,
    flags=re.DOTALL
)

open(path, 'w').write(html)
print("SPA shell written. Entry: " + (entry_href or "NOT FOUND — check index.html"))
PYEOF

# ── Write .htaccess for SPA routing ──────────────────────────────────────────
cat > "$PUBLIC_HTML/.htaccess" <<'HTACCESS'
# SPA routing: serve index.html for all non-file requests
<IfModule mod_rewrite.c>
    RewriteEngine On
    RewriteBase /
    RewriteCond %{REQUEST_FILENAME} !-f
    RewriteCond %{REQUEST_FILENAME} !-d
    RewriteRule ^ index.html [L]
</IfModule>

# Cache immutable hashed assets forever
<IfModule mod_headers.c>
    <FilesMatch "\.(js|css|woff2?|png|svg|ico|webp)$">
        Header set Cache-Control "public, max-age=31536000, immutable"
    </FilesMatch>
    <FilesMatch "index\.html$">
        Header set Cache-Control "no-cache, no-store, must-revalidate"
    </FilesMatch>
    Header always set X-Frame-Options "SAMEORIGIN"
    Header always set X-Content-Type-Options "nosniff"
</IfModule>
HTACCESS

echo "Static files deployed and .htaccess written."

# ── Print final index.html body for verification ─────────────────────────────
echo "--- index.html body ---"
grep -A3 '<body' "$PUBLIC_HTML/index.html" | head -6
echo "-----------------------"

# ── Add vhost block to DirectAdmin custom config ──────────────────────────────
SUB_CONF="/usr/local/directadmin/data/users/${DA_USER}/domains/${APP_SUBDOMAIN}.cust_httpd"

if grep -qF "$MARKER" "$SUB_CONF" 2>/dev/null; then
  echo "Vhost config already present in $SUB_CONF — skipping."
else
  echo "Writing vhost config to $SUB_CONF..."
  cat > "$SUB_CONF" <<CONF
${MARKER}
# Allow .htaccess overrides for SPA routing
<Directory ${PUBLIC_HTML}>
    AllowOverride All
    Options -Indexes +FollowSymLinks
    Require all granted
</Directory>
CONF
  chown "${DA_USER}:${DA_USER}" "$SUB_CONF"
  echo "Vhost config written."
fi

# ── Reload Apache ─────────────────────────────────────────────────────────────
if systemctl is-active --quiet httpd 2>/dev/null; then
  systemctl reload httpd
  echo "Apache reloaded."
elif systemctl is-active --quiet lsws 2>/dev/null; then
  /usr/local/lsws/bin/lswsctrl restart
  echo "LiteSpeed restarted."
fi

echo ""
echo "=== Done! ==="
echo "App: https://${APP_SUBDOMAIN}"
echo "API: https://api.${DA_DOMAIN}/api/health"
echo "WordPress on ${DA_DOMAIN} is untouched."
