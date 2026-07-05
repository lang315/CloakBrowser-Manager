# desktop/build_win.ps1 — build the Windows onedir bundle (run inside the Win10/11 VM).
# Prereqs (see ../docs/superpowers/plans/2026-07-05-m0-t9-windows-vm-checklist.md):
#   - Python 3.12 on PATH; a venv at ..\.venv with backend deps + pywebview + pyinstaller + psutil
#   - ..\frontend\dist built (npm run build)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
& "..\.venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean cloakbrowser-manager.spec
Write-Host "Built: $PSScriptRoot\dist\CloakBrowser Manager\CloakBrowser Manager.exe"
