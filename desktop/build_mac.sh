#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
../.venv/bin/python -m PyInstaller --noconfirm --clean cloakbrowser-manager.spec
echo "Built: dist/CloakBrowser Manager.app"
