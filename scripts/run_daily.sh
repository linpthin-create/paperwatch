#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_DIR"
mkdir -p data/logs data/digests

if command -v paperwatch >/dev/null 2>&1; then
  exec paperwatch run --config config.toml --days "${PAPERWATCH_DAYS:-1}"
fi

PYTHONPATH=src exec "${PYTHON:-python3}" -m paperwatch run --config config.toml --days "${PAPERWATCH_DAYS:-1}"
