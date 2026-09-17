#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"
CONFIG="${1:-config/companion/demo.json}"
if [ "$#" -gt 0 ]; then shift; fi
export PYTHONPATH="$ROOT/vendor${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -B -m apps.companion --config "$CONFIG" "$@"
