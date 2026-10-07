#!/usr/bin/env bash
# Sets up api.hamanhealth.com as a reverse proxy to haman-api (127.0.0.1:8002)
# using DirectAdmin's cust_httpd mechanism (NOT /etc/httpd/conf.d/).
#
# HOW THIS SERVER WORKS (hamanhealth.com on DirectAdmin, user: hamanhea)
# ─────────────────────────────────────────────────────────────────────
#  • DirectAdmin user: hamanhea
#  • Subdomains managed via: Domains → Subdomain Management in DA panel
#  • Per-domain extra Apache config goes in:
#      /home/hamanhea/domains/hamanhealth.com/cust_httpd
#    (one file covers all vhosts for hamanhealth.com, including subdomains
#     via <VirtualHost> blocks; the wildcard cert *.hamanhealth.com is
#     already installed and managed by DirectAdmin)
#
# PRE-REQUISITES
# ─────────────────────────────────────────────────────────────────────
#  1. api.hamanhealth.com subdomain exists in DirectAdmin (Subdomain Management)
#  2. Wildcard cert *.hamanhealth.com is active (it is — valid until Dec 2026)
#  3. haman-api Docker container is running on 127.0.0.1:8002
#
# USAGE
# ─────────────────────────────────────────────────────────────────────
# This script is a REFERENCE / one-shot helper. Run as root on the server:
#   bash deploy/directadmin-proxy-setup.sh
#
# If the cust_httpd already has the proxy block (from a previous run), the
# script exits safely without duplicating it.

set -euo pipefail

DA_USER="hamanhea"
DA_DOMAIN="hamanhealth.com"
API_SUBDOMAIN="api.hamanhealth.com"
PROXY_TARGET="http://127.0.0.1:8002"
CUST_HTTPD="/home/${DA_USER}/domains/${DA_DOMAIN}/cust_httpd"
MARKER="# haman-api proxy — DO NOT REMOVE THIS LINE"

# ── Guard: already configured? ────────────────────────────────────────────────
if grep -qF "$MARKER" "$CUST_HTTPD" 2>/dev/null; then
  echo "Proxy block already present in $CUST_HTTPD — nothing to do."
  echo "Test: curl https://${API_SUBDOMAIN}/api/health"
  exit 0
fi

# ── Append proxy vhost block ──────────────────────────────────────────────────
# The wildcard cert path is managed by DirectAdmin; adjust if yours differs.
SSL_CERT="/usr/local/directadmin/data/users/${DA_USER}/domains/${DA_DOMAIN}.cert"
SSL_KEY="/usr/local/directadmin/data/users/${DA_USER}/domains/${DA_DOMAIN}.key"
SSL_CA="/usr/local/directadmin/data/users/${DA_USER}/domains/${DA_DOMAIN}.cacert"

cat >> "$CUST_HTTPD" <<BLOCK

${MARKER}
<VirtualHost *:80>
    ServerName ${API_SUBDOMAIN}
    RewriteEngine On
    RewriteRule ^ https://%{SERVER_NAME}%{REQUEST_URI} [R=301,L]
</VirtualHost>

<VirtualHost *:443>
    ServerName ${API_SUBDOMAIN}

    SSLEngine on
    SSLCertificateFile    ${SSL_CERT}
    SSLCertificateKeyFile ${SSL_KEY}
    SSLCACertificateFile  ${SSL_CA}

    ProxyPreserveHost On
    ProxyPass        / ${PROXY_TARGET}/
    ProxyPassReverse / ${PROXY_TARGET}/

    # WebSocket support
    RewriteEngine On
    RewriteCond %{HTTP:Upgrade} websocket [NC]
    RewriteCond %{HTTP:Connection} upgrade [NC]
    RewriteRule ^/?(.*) ws://${PROXY_TARGET}/$1 [P,L]

    Header always set X-Frame-Options "SAMEORIGIN"
    Header always set X-Content-Type-Options "nosniff"

    ErrorLog  /var/log/httpd/${API_SUBDOMAIN}-error.log
    CustomLog /var/log/httpd/${API_SUBDOMAIN}-access.log combined
</VirtualHost>
BLOCK

echo "Proxy block appended to $CUST_HTTPD"

# ── Reload Apache ─────────────────────────────────────────────────────────────
if systemctl is-active --quiet httpd 2>/dev/null; then
  systemctl reload httpd
  echo "Apache reloaded."
elif systemctl is-active --quiet lsws 2>/dev/null; then
  /usr/local/lsws/bin/lswsctrl restart
  echo "LiteSpeed restarted."
else
  echo "Could not detect running web server — reload manually."
fi

echo ""
echo "Done! Test: curl https://${API_SUBDOMAIN}/api/health"
