#!/usr/bin/env bash
# Deploys/updates the Cargo Telegram bot on a fresh Debian/Ubuntu server —
# bot process only (long-polling, no inbound port needed). Does NOT touch
# the Mini App, Nginx, or SSL — see DEPLOYMENT.md for that separate step.
# Idempotent: safe to re-run to pick up a new commit, rotate a secret, or
# fix a broken step.
#
# Run as root (or via sudo). No secret ever gets hardcoded in this file —
# pass them as environment variables, or the script will prompt for
# whichever ones are missing:
#
#   BOT_TOKEN          - from @BotFather (required)
#   ANTHROPIC_API_KEY  - from console.anthropic.com (required)
#   ADMIN_USER_ID       - optional: your Telegram user_id for unlimited
#                          admin access (see config.py)
#   REPO_URL            - optional, defaults to this project's GitHub repo
#   REPO_BRANCH        - optional, defaults to
#                          claude/telegram-bot-python-aiogram-33pwme
#   DEPLOY_DIR          - optional, defaults to /opt/cargo-bot
#   SERVICE_USER        - optional, defaults to "cargo" (created if missing;
#                          the bot never runs as root)
#
# Usage:
#   BOT_TOKEN=... ANTHROPIC_API_KEY=... ADMIN_USER_ID=... ./deploy_bot.sh

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this as root (or with sudo)." >&2
    exit 1
fi

REPO_URL="${REPO_URL:-https://github.com/alexanderdoronchenko-lgtm/Cargo.git}"
REPO_BRANCH="${REPO_BRANCH:-claude/telegram-bot-python-aiogram-33pwme}"
DEPLOY_DIR="${DEPLOY_DIR:-/opt/cargo-bot}"
SERVICE_USER="${SERVICE_USER:-cargo}"
ADMIN_USER_ID="${ADMIN_USER_ID:-}"

if [ -z "${BOT_TOKEN:-}" ]; then
    read -rp "BOT_TOKEN (from @BotFather): " BOT_TOKEN
fi
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    read -rsp "ANTHROPIC_API_KEY: " ANTHROPIC_API_KEY
    echo
fi

if ! command -v apt-get >/dev/null; then
    echo "This script targets Debian/Ubuntu (apt-get). Adapt the package list for your distro." >&2
    exit 1
fi

echo "==> Installing system packages"
apt-get update -y
# libcairo2: the system library cairosvg (board image rendering) loads at
# runtime — pip installing the cairosvg package alone isn't enough.
apt-get install -y git python3 python3-venv python3-pip libcairo2 stockfish cron curl

STOCKFISH_PATH="$(command -v stockfish || true)"
if [ -z "$STOCKFISH_PATH" ]; then
    echo "stockfish binary not found on PATH after install — aborting." >&2
    exit 1
fi

PYTHON_BIN="python3"
PYVER_OK="$(python3 -c 'import sys; print(1 if sys.version_info >= (3, 10) else 0)')"
if [ "$PYVER_OK" != "1" ]; then
    echo "==> System python3 is older than 3.10 (this codebase uses 3.10+ syntax) — installing python3.11 via deadsnakes"
    apt-get install -y software-properties-common
    add-apt-repository -y ppa:deadsnakes/ppa
    apt-get update -y
    apt-get install -y python3.11 python3.11-venv
    PYTHON_BIN="python3.11"
fi

echo "==> Creating service user $SERVICE_USER (no login shell, never runs as root)"
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --home-dir "$DEPLOY_DIR" --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

echo "==> Fetching code into $DEPLOY_DIR (branch $REPO_BRANCH)"
if [ -d "$DEPLOY_DIR/.git" ]; then
    git -C "$DEPLOY_DIR" fetch origin "$REPO_BRANCH"
    git -C "$DEPLOY_DIR" checkout "$REPO_BRANCH"
    git -C "$DEPLOY_DIR" reset --hard "origin/$REPO_BRANCH"
else
    git clone --branch "$REPO_BRANCH" "$REPO_URL" "$DEPLOY_DIR"
fi
chown -R "$SERVICE_USER":"$SERVICE_USER" "$DEPLOY_DIR"

echo "==> Setting up the virtualenv and installing dependencies"
sudo -u "$SERVICE_USER" "$PYTHON_BIN" -m venv "$DEPLOY_DIR/venv"
sudo -u "$SERVICE_USER" "$DEPLOY_DIR/venv/bin/pip" install --upgrade pip
sudo -u "$SERVICE_USER" "$DEPLOY_DIR/venv/bin/pip" install -r "$DEPLOY_DIR/requirements.txt"

echo "==> Writing .env (not tracked by git — chmod 600, owned by $SERVICE_USER)"
ENV_FILE="$DEPLOY_DIR/.env"
cat > "$ENV_FILE" <<EOF
BOT_TOKEN=$BOT_TOKEN
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
STOCKFISH_PATH=$STOCKFISH_PATH
ADMIN_USER_ID=$ADMIN_USER_ID
EOF
chown "$SERVICE_USER":"$SERVICE_USER" "$ENV_FILE"
chmod 600 "$ENV_FILE"

echo "==> Installing the systemd service (auto-start on boot, auto-restart on crash)"
cat > /etc/systemd/system/cargo-bot.service <<EOF
[Unit]
Description=Cargo Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$DEPLOY_DIR
ExecStart=$DEPLOY_DIR/venv/bin/python $DEPLOY_DIR/bot.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable cargo-bot.service
systemctl restart cargo-bot.service

echo "==> Setting up the daily DB backup cron job (runs as $SERVICE_USER, see scripts/backup_db.py)"
mkdir -p "$DEPLOY_DIR/backups"
chown "$SERVICE_USER":"$SERVICE_USER" "$DEPLOY_DIR/backups"
CRON_LINE="0 3 * * * cd $DEPLOY_DIR && $DEPLOY_DIR/venv/bin/python scripts/backup_db.py >> $DEPLOY_DIR/backups/backup.log 2>&1"
( sudo -u "$SERVICE_USER" crontab -l 2>/dev/null | grep -vF "scripts/backup_db.py" ; echo "$CRON_LINE" ) | sudo -u "$SERVICE_USER" crontab -

echo
echo "==> Done. Service status:"
systemctl --no-pager --full status cargo-bot.service || true
echo
echo "Tail logs with: journalctl -u cargo-bot -f"
echo "Crontab (as $SERVICE_USER): sudo -u $SERVICE_USER crontab -l"
