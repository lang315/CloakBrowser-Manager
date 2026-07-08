# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
datas, binaries, hiddenimports = [], [], []
for pkg in ("playwright", "cloakbrowser"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h
# Exclude Playwright's own browser download — cloakbrowser downloads its binary.
datas = [(s, d) for (s, d) in datas if ".local-browsers" not in s]
datas += [("../frontend/dist", "frontend/dist")]

a = Analysis(["app_entry.py"], pathex=[".."], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports + ["backend.main"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="CloakBrowser Manager",
          console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="CloakBrowser Manager")  # onedir
app = BUNDLE(coll, name="CloakBrowser Manager.app",
             bundle_identifier="dev.cloakbrowser.manager")
