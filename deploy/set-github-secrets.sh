#!/usr/bin/env bash
set -euo pipefail

REPO="${1:-HachHQ/transcribator3000}"
ENV_FILE="${2:-.env}"
SSH_KEY="${3:-./github_actions_deploy}"

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI is required: https://cli.github.com/"
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Env file not found: $ENV_FILE"
  echo "Usage: bash deploy/set-github-secrets.sh [repo] [env-file] [ssh-private-key]"
  exit 1
fi

set_secret() {
  local name="$1"
  local value="$2"
  if [[ -z "$value" ]]; then
    echo "skip $name (empty)"
    return
  fi
  gh secret set "$name" --body "$value" -R "$REPO"
  echo "set $name"
}

echo "==> Uploading bot secrets from $ENV_FILE to $REPO"

while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%%#*}"
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  [[ -z "$line" ]] && continue
  [[ "$line" != *=* ]] && continue

  key="${line%%=*}"
  value="${line#*=}"
  set_secret "$key" "$value"
done < "$ENV_FILE"

if [[ -f "$SSH_KEY" ]]; then
  gh secret set VPS_SSH_KEY < "$SSH_KEY" -R "$REPO"
  echo "set VPS_SSH_KEY"
else
  echo "skip VPS_SSH_KEY ($SSH_KEY not found)"
fi

read -r -p "VPS host IP [$REPO — press Enter to skip]: " VPS_HOST_INPUT
if [[ -n "${VPS_HOST_INPUT:-}" ]]; then
  gh secret set VPS_HOST --body "$VPS_HOST_INPUT" -R "$REPO"
  echo "set VPS_HOST"
fi

read -r -p "VPS user [root]: " VPS_USER_INPUT
VPS_USER_INPUT="${VPS_USER_INPUT:-root}"
gh secret set VPS_USER --body "$VPS_USER_INPUT" -R "$REPO"
echo "set VPS_USER"

echo
echo "Done. Secrets: https://github.com/$REPO/settings/secrets/actions"
echo
echo "Note: this script does NOT start the deploy pipeline."
echo "Trigger deploy with: git push origin main"
echo "Or manually: https://github.com/$REPO/actions/workflows/ci-cd.yml → Run workflow"
