#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 /path/to/paperwatch-private [config.toml]" >&2
  exit 2
fi

private_repo="$1"
source_config="${2:-config.toml}"
target_config="$private_repo/config.toml"

if [[ ! -d "$private_repo/.git" ]]; then
  echo "Private repository path is not a git checkout: $private_repo" >&2
  exit 2
fi

if [[ ! -f "$source_config" ]]; then
  echo "Config file not found: $source_config" >&2
  exit 2
fi

cp "$source_config" "$target_config"

# Keep routing, model, source, interest, and schedule settings in config.toml.
# Keep credentials in GitHub Secrets instead of committing them to git.
perl -0pi -e 's/api_key = "[^"]*"/api_key = ""/g' "$target_config"
perl -0pi -e 's/webhook_url = "[^"]*"/webhook_url = ""/g' "$target_config"
perl -0pi -e 's/secret = "[^"]*"/secret = ""/g' "$target_config"

git -C "$private_repo" add config.toml
if git -C "$private_repo" diff --cached --quiet; then
  echo "No config changes to sync."
  exit 0
fi

git -C "$private_repo" commit -m "Update private PaperWatch config"
git -C "$private_repo" push
