#!/bin/sh
# Install or upgrade the Eruv agent on a Raspberry Pi. Run as root from any
# directory:  sudo sh pi-agent/deploy/install.sh
#
# - creates the venv in /opt/eruv-agent/venv and installs the agent into it
# - copies config/agent.example.yaml to /etc/eruv-agent/agent.yaml (owner root,
#   mode 0600: it holds the device key); an existing config is kept
# - creates /var/lib/eruv-agent for the spool database
# - installs and enables the systemd unit (starts on boot, restarts on crash)
set -eu

APP_DIR=/opt/eruv-agent
CONF_DIR=/etc/eruv-agent
CONF_FILE=$CONF_DIR/agent.yaml
STATE_DIR=/var/lib/eruv-agent
UNIT=eruv-agent.service
SRC_DIR=$(cd "$(dirname "$0")/.." && pwd)

if [ "$(id -u)" -ne 0 ]; then
    echo "install.sh: run as root (sudo)" >&2
    exit 1
fi

install -d -m 0755 "$APP_DIR"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install --upgrade "$SRC_DIR"

install -d -m 0700 -o root -g root "$CONF_DIR"
if [ -f "$CONF_FILE" ]; then
    NEW_CONFIG=0
    chown root:root "$CONF_FILE"
    chmod 0600 "$CONF_FILE"
else
    NEW_CONFIG=1
    install -m 0600 -o root -g root "$SRC_DIR/config/agent.example.yaml" "$CONF_FILE"
fi

install -d -m 0700 -o root -g root "$STATE_DIR"

install -m 0644 "$SRC_DIR/deploy/$UNIT" "/etc/systemd/system/$UNIT"
systemctl daemon-reload
systemctl enable "$UNIT"

if [ "$NEW_CONFIG" -eq 1 ]; then
    echo "Edit $CONF_FILE (server.base_url, server.device_key), then run:"
    echo "  sudo systemctl start $UNIT"
else
    systemctl restart "$UNIT"
    echo "Restarted $UNIT. Logs: journalctl -u $UNIT -f"
fi
