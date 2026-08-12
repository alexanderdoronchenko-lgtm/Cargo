#!/usr/bin/env bash
# Builds and deploys the Mini App + API behind Nginx, with a real Let's
# Encrypt certificate. Run AFTER scripts/deploy_bot.sh has already set up
# the bot (needs the same DEPLOY_DIR/service user to exist). Idempotent:
# safe to re-run to pick up a new commit, rebuild the frontend, or renew
# the Nginx config.
#
# Run as root. Requires a domain whose A record already points at this
# server — Let's Encrypt cannot issue a certificate for a bare IP.
#
#   DOMAIN               - required, e.g. coachgm.online (no https://, no
#                            trailing slash)
#   LETSENCRYPT_EMAIL     - required: cert-expiry notifications go here
#   DEPLOY_DIR             - optional, defaults to /opt/cargo-bot (must
#                            match what deploy_bot.sh used)
#   SERVICE_USER           - optional, defaults to "cargo"
#   NODE_MAJOR             - optional, defaults to 20 (NodeSource LTS —
#                            apt's own nodejs package is too old on most
#                            Debian/Ubuntu releases for this Vite version)
#
# Usage:
#   DOMAIN=coachgm.online LETSENCRYPT_EMAIL=you@example.com ./deploy_miniapp.sh

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this as root (or with sudo)." >&2
    exit 1
fi

DEPLOY_DIR="${DEPLOY_DIR:-/opt/cargo-bot}"
SERVICE_USER="${SERVICE_USER:-cargo}"
NODE_MAJOR="${NODE_MAJOR:-20}"

if [ -z "${DOMAIN:-}" ]; then
    read -rp "DOMAIN (e.g. coachgm.online — its A record must already point here): " DOMAIN
fi
if [ -z "${LETSENCRYPT_EMAIL:-}" ]; then
    read -rp "LETSENCRYPT_EMAIL (for cert-expiry notices): " LETSENCRYPT_EMAIL
fi

if [ ! -d "$DEPLOY_DIR/.git" ]; then
    echo "$DEPLOY_DIR doesn't look like the bot's checkout — run scripts/deploy_bot.sh first." >&2
    exit 1
fi
ENV_FILE="$DEPLOY_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "$ENV_FILE not found — run scripts/deploy_bot.sh first." >&2
    exit 1
fi

if ! command -v apt-get >/dev/null; then
    echo "This script targets Debian/Ubuntu (apt-get)." >&2
    exit 1
fi

echo "==> Installing Nginx + certbot"
apt-get update -y
apt-get install -y nginx certbot python3-certbot-nginx

if ! command -v node >/dev/null || [ "$(node -e 'console.log(process.versions.node.split(".")[0])')" -lt "$NODE_MAJOR" ]; then
    echo "==> Installing Node.js $NODE_MAJOR.x via NodeSource (apt's own nodejs is too old on most distros)"
    curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
    apt-get install -y nodejs
fi

echo "==> Building the Mini App (VITE_API_BASE_URL=https://$DOMAIN)"
cat > "$DEPLOY_DIR/miniapp/.env.production" <<EOF
VITE_API_BASE_URL=https://$DOMAIN
EOF
sudo -u "$SERVICE_USER" bash -c "cd '$DEPLOY_DIR/miniapp' && npm ci && npm run build"

echo "==> Installing the systemd service for the API (uvicorn)"
cat > /etc/systemd/system/cargo-api.service <<EOF
[Unit]
Description=Cargo Mini App API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$DEPLOY_DIR
ExecStart=$DEPLOY_DIR/venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable cargo-api.service
systemctl restart cargo-api.service

echo "==> Writing the Nginx site (HTTP only for now — certbot adds the HTTPS block below)"
cat > "/etc/nginx/sites-available/$DOMAIN" <<EOF
server {
    listen 80;
    server_name $DOMAIN;

    root $DEPLOY_DIR/miniapp/dist;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # Vite hashes every built filename (index-<hash>.js/.css) — a new build
    # gets a new hash, so the old file is simply never requested again once
    # index.html below points at it. Safe to cache for a year.
    location /assets/ {
        add_header Cache-Control "public, max-age=31536000, immutable" always;
    }

    # index.html is the only file whose name never changes, and it's the
    # one place that references the current hashed asset filenames — it
    # must never be cached, or a rebuild never reaches existing clients.
    # Telegram's in-app WebView caches HTML at the client level in a way
    # its own "clear cache" doesn't reach, so this has to be enforced here.
    # The \`= /index.html\` block also covers the try_files fallback below
    # (an internal redirect to /index.html re-runs location matching).
    location = /index.html {
        add_header Cache-Control "no-store, must-revalidate" always;
    }

    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
EOF
ln -sf "/etc/nginx/sites-available/$DOMAIN" "/etc/nginx/sites-enabled/$DOMAIN"
[ -f /etc/nginx/sites-enabled/default ] && rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
    echo "==> ufw is active — allowing Nginx (80/443)"
    ufw allow 'Nginx Full' || true
fi

echo "==> Requesting the Let's Encrypt certificate for $DOMAIN"
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$LETSENCRYPT_EMAIL" --redirect

echo "==> Updating MINIAPP_URL in $ENV_FILE"
if grep -q '^MINIAPP_URL=' "$ENV_FILE"; then
    sed -i "s#^MINIAPP_URL=.*#MINIAPP_URL=https://$DOMAIN/#" "$ENV_FILE"
else
    echo "MINIAPP_URL=https://$DOMAIN/" >> "$ENV_FILE"
fi

echo "==> Restarting the bot to pick up the new MINIAPP_URL"
systemctl restart cargo-bot.service

echo
echo "==> Done."
echo "Mini App:  https://$DOMAIN/"
echo "API check: curl -s https://$DOMAIN/api/audio/tracks"
echo "Nginx:     systemctl status nginx"
echo "API:       systemctl status cargo-api"
echo "Bot:       systemctl status cargo-bot"
echo "Certbot renewal is installed automatically (systemctl list-timers | grep certbot)."
