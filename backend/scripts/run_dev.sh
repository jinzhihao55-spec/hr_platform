#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  echo "未找到 .venv，请先执行: python3 -m venv .venv && pip install -r requirements.txt"
  exit 1
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

uvicorn app.main:app --reload --host "${APP_HOST:-0.0.0.0}" --port "${APP_PORT:-8000}"
