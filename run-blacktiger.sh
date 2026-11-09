#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON=""
for cmd in python3.11 python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        PYTHON="$(command -v "$cmd")"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "Error: Python 3 not found. Install Python 3 with: sudo apt install -y python3"
    exit 1
fi

exec "$PYTHON" "$SCRIPT_DIR/blacktiger_app.py" "$@"
