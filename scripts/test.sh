#!/usr/bin/env bash
# Run local checks from any working directory.
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

usage() {
    cat <<'EOF'
Usage: bash scripts/test.sh [check|tests|coverage|lint|all] [pytest arguments]

  check     Coverage and Ruff (default; no Docker required)
  tests     Pytest without coverage
  coverage  Pytest with branch coverage and missing lines
  lint      Ruff
  all       Coverage, Ruff, and hassfest (requires Docker)

Examples:
  bash scripts/test.sh
  bash scripts/test.sh tests -k config
  bash scripts/test.sh coverage -x
  bash scripts/test.sh all

Uses PYTHON if set, then the active virtual environment, .venv, venv,
or python3. Install requirements-dev.txt into that environment first.
EOF
}

mode="${1:-check}"
if [[ $# -gt 0 ]]; then
    shift
fi
case "$mode" in
    -h|--help) usage; exit 0 ;;
    check|tests|coverage|all) ;;
    lint)
        if [[ $# -gt 0 ]]; then usage >&2; exit 2; fi
        ;;
    *) usage >&2; exit 2 ;;
esac

if [[ -n "${PYTHON:-}" ]]; then
    test_python="$PYTHON"
elif [[ -n "${VIRTUAL_ENV:-}" ]]; then
    test_python="$VIRTUAL_ENV/bin/python"
elif [[ -x .venv/bin/python ]]; then
    test_python="$repo_dir/.venv/bin/python"
elif [[ -x venv/bin/python ]]; then
    test_python="$repo_dir/venv/bin/python"
else
    test_python=python3
fi

if [[ "$mode" == tests ]]; then
    "$test_python" -m pytest -q "$@"
elif [[ "$mode" != lint ]]; then
    "$test_python" -m pytest -q \
        --cov=custom_components.tile_ble --cov-branch \
        --cov-report=term-missing "$@"
fi

if [[ "$mode" == check || "$mode" == lint || "$mode" == all ]]; then
    "$test_python" -m ruff check custom_components tests
fi

if [[ "$mode" == all ]]; then
    bash "$repo_dir/scripts/hassfest.sh"
fi
