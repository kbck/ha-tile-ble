#!/usr/bin/env bash
# Match the standalone hassfest GitHub Action.
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
docker run --rm \
    -v "$repo_dir:/github/workspace" \
    ghcr.io/home-assistant/hassfest
