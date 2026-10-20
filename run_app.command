#!/bin/sh
# Market Sentinel launcher for macOS (double-click) and Linux (sh run_app.command).
# First run: creates a private Python environment and installs the packages (internet needed).
cd "$(dirname "$0")" || exit 1
for py in python3 python3.15 python3.14 python3.13 python3.12 python3.11; do
    if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' 2>/dev/null; then
        exec "$py" launch.py
    fi
done
echo "Python 3.11 or newer was not found. Install it from https://www.python.org/downloads/ and run this file again."
exit 1
