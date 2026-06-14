#!/usr/bin/env bash
set -euo pipefail

cd /opt/transcribator3000

git pull --ff-only
docker compose up -d --build
docker compose ps
