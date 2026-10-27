; Inno Setup script for 83 MEN'S WEAR POS (https://jrsoftware.org/isinfo.php)
; Build after PyInstaller:   iscc packaging\installer.iss
; Output: dist\83MensWear-Setup-<version>.exe
;
; The installer only installs program files. Shop data lives in %APPDATA%\83MensWear and backups in
; Documents\83MensWear Backups. Uninstalling NEVER removes those folders.

#define AppName "83 MEN'S WEAR POS"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{E9DAE1D5-6E3A-46E0-843A-0B7B447BD3DF}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=83 MEN'S WEAR
DefaultDirName={autopf}\83MensWear
DefaultGroupName=83 MEN'S WEAR
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=83MensWear-Setup-{#AppVersion}
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\83MensWear.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
MinVersion=10.0

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\83MensWear\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\83 MEN'S WEAR POS"; Filename: "{app}\83MensWear.exe"
Name: "{autodesktop}\83 MEN'S WEAR POS"; Filename: "{app}\83MensWear.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\83MensWear.exe"; Description: "Start 83 MEN'S WEAR POS now"; Flags: nowait postinstall skipifsilent

; No [UninstallDelete] section on purpose: shop data and backups are kept.
