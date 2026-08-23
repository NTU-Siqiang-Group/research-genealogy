#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ ! -x .venv-coi/bin/python ]]; then
  echo "missing .venv-coi; see reports/upstream_check.md"
  exit 2
fi

if [[ ! -x .venv-scychic/bin/python ]]; then
  echo "missing .venv-scychic; see requirements/scychic-p0.txt"
  exit 2
fi

.venv-coi/bin/python -B scripts/00_check_upstreams.py
.venv-coi/bin/python -B -m unittest discover -s tests -v
.venv-coi/bin/python -B scripts/00_offline_p0_smoke.py
LOKY_MAX_CPU_COUNT=8 .venv-scychic/bin/python -B scripts/00_scychic_smoke.py

echo "P0 local smoke suite complete. Live corpus/profile runs require API credentials."

