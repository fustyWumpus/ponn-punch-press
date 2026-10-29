; Inno Setup script for Ponn Punch Press.
;
; Replaces the legacy .vdproj-built MSI + separate WSDK dependency install
; with a single self-contained installer: the PyInstaller --onedir bundle
; carries its own Python runtime, so there's nothing separate to install for
; the app itself (this is what actually fixes "can't install on modern
; Windows" -- the old installer hard-required .NET Framework 1.1, which does
; not exist on Windows 10/11).
;
; Also silently chain-installs Galil's real gclib SDK (installer/vendor/
; gclib_2.4.1.exe, downloaded and sha256-verified from
; https://www.galil.com/gclib/latest -- Galil's own "always latest" alias)
; using the "/S" silent-install switch Galil documents for exactly this
; bundling use case. This is the native driver our app's GclibMotionController
; needs at runtime to talk to the controller over Ethernet; the app's own
; Python-side gclib wrapper is built into PonnPunchPress.exe already (see
; pyproject.toml's "hardware" extra) but is useless without this native half.
;
; Build order:
;   1. pip install -e ".[hardware]"   (once, in the build venv, so PyInstaller
;      bundles the gclib Python wrapper into the app)
;   2. pyinstaller installer/ponn_punch_press.spec --distpath dist --workpath build
;   3. iscc installer/ponn_punch_press.iss
;
; To refresh the vendored gclib installer to a newer release: download from
; https://www.galil.com/gclib/latest, verify its .sha256 file, and replace
; installer/vendor/gclib_2.4.1.exe (updating the filename references below).

#define MyAppName "Ponn Punch Press"
#define MyAppVersion "1.0.5"
#define MyAppExeName "PonnPunchPress.exe"

[Setup]
AppId={{667E2CEF-856F-4BEB-8139-51E48B752573}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=PonnPunchPressSetup
Compression=lzma
SolidCompression=yes
; Everything installed is x64 (app, bundled Python/Qt, Galil gclib.dll). This
; refuses cleanly on 32-bit Windows instead of installing files that can't run;
; x64compatible covers Intel/AMD and Windows 11 on ARM (runs x64 via emulation).
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
; Defaults to installing for all users (needs admin), matching a shared
; shop-floor PC -- but allow a per-user fallback (no admin needed) via
; /CURRENTUSER on the command line or the wizard's privilege page, useful
; for testing or machines where nobody has an admin login handy.
PrivilegesRequiredOverridesAllowed=commandline dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"
Name: "installgclib"; Description: "Install the Galil gclib driver (required to control real hardware; leave checked unless it's already installed)"; GroupDescription: "Galil motion controller software:"; Flags: checkedonce

[Files]
Source: "..\dist\PonnPunchPress\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs
Source: "vendor\gclib_2.4.1.exe"; DestDir: "{tmp}"; Tasks: installgclib

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{tmp}\gclib_2.4.1.exe"; Parameters: "/S"; StatusMsg: "Installing Galil gclib (motion controller driver)..."; Flags: waituntilterminated; Tasks: installgclib
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
