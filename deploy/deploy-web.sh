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
# DirectAdmin stores the subdomain's public_html here:
PUBLIC_HTML="/home/${DA_USER}/domains/${APP_SUBDOMAIN}/public_html"
# DirectAdmin's real custom config file (NOT cust_httpd inside domains/):
DA_CONF="/usr/local/directadmin/data/users/${DA_USER}/domains/${DA_DOMAIN}.cust_httpd"
MARKER="# haman-app.hamanhealth.com — DO NOT REMOVE"

echo "=== Haman Health — web deploy to ${APP_SUBDOMAIN} ==="

# ── Validate build dir ────────────────────────────────────────────────────────
# scp of a directory with a trailing slash lands the *contents* directly inside
# the destination; without a trailing slash it creates a subdirectory.  Handle
# both: if index.html is one level deeper (e.g. BUILD_DIR/public/index.html),
# descend into that subdirectory automatically.
if [ -f "$BUILD_DIR/public/index.html" ] && [ ! -f "$BUILD_DIR/index.html" ]; then
  BUILD_DIR="$BUILD_DIR/public"
  echo "Auto-detected build in $BUILD_DIR"
fi

if [ ! -f "$BUILD_DIR/index.html" ]; then
  echo "ERROR: $BUILD_DIR/index.html not found."
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

# ── Ensure subdomain public_html exists ───────────────────────────────────────
# The subdomain must already exist in DirectAdmin (Subdomain Management).
if [ ! -d "$PUBLIC_HTML" ]; then
  echo "ERROR: $PUBLIC_HTML does not exist."
  echo "Create the subdomain app.hamanhealth.com in DirectAdmin first:"
  echo "  DirectAdmin → Subdomain Management → Add: app"
  exit 1
fi

# ── Sync static files ─────────────────────────────────────────────────────────
echo "Syncing static files to $PUBLIC_HTML..."
rsync -av --delete \
  --exclude='.git' \
  --exclude='.env*' \
  "$BUILD_DIR/" "$PUBLIC_HTML/"
chown -R "${DA_USER}:${DA_USER}" "$PUBLIC_HTML"

# ── Strip SSR-prerendered content from index.html ────────────────────────────
# TanStack Start / Nitro prerenders the app into index.html even when
# prerender is nominally disabled. On a static Apache host React can't
# hydrate this and throws error #418. We overwrite <body> with an empty
# #root div so React mounts from a blank DOM — all <head> assets are kept.
INDEX="$PUBLIC_HTML/index.html"
if [ -f "$INDEX" ]; then
  echo "Rebuilding index.html as clean SPA shell..."
  python3 - "$INDEX" <<'PYEOF'
import sys, re

path = sys.argv[1]
html = open(path).read()

# TanStack Start / Nitro uses <Scripts /> which only injects <script> tags
# when a Node server is running. On static Apache nothing gets injected, so
# React never boots. Fix: move all modulepreload + module script tags from
# <head> into <body> so the browser can actually run them.

# 1. Extract all modulepreload link tags
modulepreloads = re.findall(r'<link[^>]+rel=["\']modulepreload["\'][^>]*/?\s*>', html, re.DOTALL)

# 2. Extract the entry module script (type="module") if present
entry_scripts = re.findall(r'<script[^>]+type=["\']module["\'][^>]*>.*?</script>', html, re.DOTALL)

# 3. Build script tags from modulepreload hrefs as a fallback
# Find the main entry JS (index-*.js) from modulepreload
entry_href = None
for tag in modulepreloads:
    m = re.search(r'href=["\']([^"\']*index-[^"\']+\.js)["\']', tag)
    if m:
        entry_href = m.group(1)
        break

# 4. Strip body content, keep <body> tag
html = re.sub(
    r'(<body[^>]*>).*?(</body>)',
    r'\1BODY_PLACEHOLDER\2',
    html,
    flags=re.DOTALL
)

# 5. Build body content
if entry_scripts:
    body_content = '\n    <div id="root"></div>\n    ' + '\n    '.join(entry_scripts) + '\n  '
elif entry_href:
    body_content = f'\n    <div id="root"></div>\n    <script type="module" src="{entry_href}"></script>\n  '
else:
    # Last resort: inject all modulepreload scripts
    script_tags = '\n    '.join(
        f'<script type="module" src="{re.search(r\'href=["\\\'](.*?)["\\\']\', t).group(1)}"></script>'
        for t in modulepreloads
        if re.search(r'href=["\\\'].*?["\\\']', t)
    )
    body_content = f'\n    <div id="root"></div>\n    {script_tags}\n  '

html = html.replace('BODY_PLACEHOLDER', body_content)

open(path, 'w').write(html)
print(f"Done — SPA shell written. Entry: {entry_href or 'from script tags'}")
PYEOF
fi

# Write .htaccess for SPA client-side routing fallback
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

# ── Add vhost block to DirectAdmin custom config ──────────────────────────────
# DirectAdmin injects .cust_httpd content inside the existing vhost — so we
# write ONLY directives (no <VirtualHost> wrappers here). However for a
# subdomain we need its own vhost; DirectAdmin handles this via a separate
# subdomain .cust_httpd file.
SUB_CONF="/usr/local/directadmin/data/users/${DA_USER}/domains/${APP_SUBDOMAIN}.cust_httpd"

if grep -qF "$MARKER" "$SUB_CONF" 2>/dev/null; then
  echo "Vhost config already present in $SUB_CONF — skipping."
else
  echo "Writing vhost config to $SUB_CONF..."
  # For subdomains DirectAdmin accepts directives injected into its managed vhost.
  # The wildcard cert *.hamanhealth.com covers app.hamanhealth.com.
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
