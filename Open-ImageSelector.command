#!/bin/bash
set -e
cd -- "$(dirname -- "$0")"
bundled_python="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [ -x .venv/bin/python ]; then
    exec .venv/bin/python -B app.py "$@"
fi
if [ -x "$bundled_python" ]; then
    exec "$bundled_python" -B app.py "$@"
fi
exec python3 -B app.py "$@"
