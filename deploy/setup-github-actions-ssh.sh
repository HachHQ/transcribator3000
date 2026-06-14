#!/usr/bin/env bash
set -euo pipefail

KEY_PATH="${1:-./github_actions_deploy}"

ssh-keygen -t ed25519 -C "github-actions-transcribator3000" -f "$KEY_PATH" -N ""

echo
echo "=== 1. Добавьте публичный ключ на VPS ==="
echo "На сервере выполните:"
echo
cat <<EOF
mkdir -p ~/.ssh
echo '$(cat "${KEY_PATH}.pub")' >> ~/.ssh/authorized_keys
chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys
EOF

echo
echo "=== 2. Добавьте secrets в GitHub ==="
echo "Repository → Settings → Secrets and variables → Actions → New repository secret"
echo
echo "  VPS_HOST     = 94.249.203.188"
echo "  VPS_USER     = root"
echo "  VPS_SSH_KEY  = содержимое файла ${KEY_PATH} (приватный ключ)"
echo
echo "Приватный ключ:"
echo "----------------"
cat "$KEY_PATH"
echo "----------------"
echo
echo "После настройки secrets любой push в main задеплоит проект автоматически."
