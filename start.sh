#!/usr/bin/env bash
set -euo pipefail
projektordner="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$projektordner"
exec /usr/bin/python3 -B "$projektordner/tiny.py" "$@"
