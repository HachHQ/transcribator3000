#!/usr/bin/env bash
set -euo pipefail

cd /opt/voice-to-obsidian

git pull --ff-only
docker compose up -d --build
docker compose ps
