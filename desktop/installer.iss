; desktop/installer.iss — Inno Setup script packaging the PyInstaller onedir output.
; Build the onedir first (build_win.ps1), then compile this with Inno Setup (iscc installer.iss).
; Code-sign the produced setup .exe AND the app .exe separately with your OV/EV cert (signtool) — not done here.

[Setup]
AppName=CloakBrowser Manager
AppVersion=0.1.0
AppPublisher=CloakHQ
DefaultDirName={autopf}\CloakBrowser Manager
DefaultGroupName=CloakBrowser Manager
OutputBaseFilename=CloakBrowserManager-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
WizardStyle=modern

[Files]
Source: "dist\CloakBrowser Manager\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\CloakBrowser Manager"; Filename: "{app}\CloakBrowser Manager.exe"
Name: "{autodesktop}\CloakBrowser Manager"; Filename: "{app}\CloakBrowser Manager.exe"

[Run]
; Win11 ships the WebView2 runtime. On Win10 it is frequently ABSENT — download the Evergreen
; bootstrapper (MicrosoftEdgeWebview2Setup.exe) next to this script and uncomment the line below.
; Source it in [Files] too if you bundle it.
;Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; Flags: waituntilterminated
Filename: "{app}\CloakBrowser Manager.exe"; Description: "Launch CloakBrowser Manager"; Flags: nowait postinstall skipifsilent
