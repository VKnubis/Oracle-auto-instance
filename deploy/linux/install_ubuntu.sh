#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/loop-oracle"
ENV_FILE="/etc/loop-oracle.env"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer with sudo."
  exit 1
fi

mkdir -p "${APP_DIR}"
cp loop.py requirements.txt "${APP_DIR}/"

python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

if [[ ! -f "${ENV_FILE}" ]]; then
  cp config/config.example.env "${ENV_FILE}"
  chmod 600 "${ENV_FILE}"
fi

cp deploy/systemd/loop-oracle.service /etc/systemd/system/
cp deploy/systemd/loop-oracle.timer /etc/systemd/system/

systemctl daemon-reload
systemctl enable loop-oracle.timer

echo "Installed."
echo "Edit ${ENV_FILE}, then run:"
echo "  sudo systemctl start loop-oracle.timer"
echo "  sudo systemctl status loop-oracle.timer"
