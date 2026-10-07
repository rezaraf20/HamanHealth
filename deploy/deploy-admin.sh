#!/usr/bin/env bash
# Deploys the Haman Health admin panel to admin.hamanhealth.com.
#
# The admin panel is a single static HTML file — no build step needed.
#
# ── On your dev machine ───────────────────────────────────────────────────────
#   scp -P 2025 admin/index.html root@128.140.54.86:/tmp/haman-admin-index.html
#   ssh -p 2025 root@128.140.54.86 'bash /opt/hamanhealth/deploy/deploy-admin.sh'
#
# Usage: bash deploy/deploy-admin.sh [SOURCE_FILE]
#   SOURCE_FILE: path to the admin index.html (default: /tmp/haman-admin-index.html)

set -euo pipefail

SOURCE="${1:-/tmp/haman-admin-index.html}"
DA_USER="hamanhea"
ADMIN_SUBDOMAIN="admin.hamanhealth.com"
PUBLIC_HTML="/home/${DA_USER}/domains/${ADMIN_SUBDOMAIN}/public_html"
SUB_CONF="/usr/local/directadmin/data/users/${DA_USER}/domains/${ADMIN_SUBDOMAIN}.cust_httpd"
MARKER="# haman-admin.hamanhealth.com — DO NOT REMOVE"

echo "=== Haman Health — admin deploy to ${ADMIN_SUBDOMAIN} ==="

if [ ! -f "$SOURCE" ]; then
  echo "ERROR: $SOURCE not found."
  echo "Upload the admin panel first:"
  echo "  scp -P 2025 admin/index.html root@128.140.54.86:/tmp/haman-admin-index.html"
  exit 1
fi

# Ensure subdomain public_html exists (create subdomain in DirectAdmin first)
if [ ! -d "$PUBLIC_HTML" ]; then
  echo "Creating $PUBLIC_HTML..."
  mkdir -p "$PUBLIC_HTML"
  chown -R "${DA_USER}:${DA_USER}" "$PUBLIC_HTML"
fi

cp "$SOURCE" "$PUBLIC_HTML/index.html"
chown "${DA_USER}:${DA_USER}" "$PUBLIC_HTML/index.html"
echo "Admin panel deployed to $PUBLIC_HTML/index.html"

# Write vhost config for DirectAdmin
if grep -qF "$MARKER" "$SUB_CONF" 2>/dev/null; then
  echo "Vhost config already present — skipping."
else
  echo "Writing vhost config to $SUB_CONF..."
  cat > "$SUB_CONF" <<CONF
${MARKER}
<Directory ${PUBLIC_HTML}>
    AllowOverride All
    Options -Indexes +FollowSymLinks
    Require all granted
</Directory>
CONF
  chown "${DA_USER}:${DA_USER}" "$SUB_CONF"
  echo "Vhost config written."
fi

# Reload web server
if systemctl is-active --quiet httpd 2>/dev/null; then
  systemctl reload httpd && echo "Apache reloaded."
elif systemctl is-active --quiet lsws 2>/dev/null; then
  /usr/local/lsws/bin/lswsctrl restart && echo "LiteSpeed restarted."
fi

echo ""
echo "=== Done! ==="
echo "Admin: https://${ADMIN_SUBDOMAIN}"
echo ""
echo "NEXT: Create the 'admin.hamanhealth.com' subdomain in DirectAdmin if you haven't already."
echo "      Then set ADMIN_SECRET in deploy/.env and restart the API container."
