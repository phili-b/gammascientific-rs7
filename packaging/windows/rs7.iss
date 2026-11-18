; Inno Setup script. Build: iscc /DAppVersion=0.4.0 packaging\windows\rs7.iss  (needs dist\rs7 from PyInstaller)
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6E0B5D6A-52E0-4C0F-9A55-7B8B2F3E9D11}
AppName=RS-7 Control
AppVersion={#AppVersion}
AppPublisher=phili-b
AppPublisherURL=https://github.com/phili-b/gammascientific-rs7
DefaultDirName={autopf}\RS-7 Control
DefaultGroupName=RS-7 Control
UninstallDisplayIcon={app}\rs7-gui.exe
SetupIconFile=..\rs7.ico
OutputDir=..\..\dist
OutputBaseFilename=gammascientific-rs7-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ChangesEnvironment=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: unchecked
Name: "addpath"; Description: "Add the rs7 command to &PATH"

[Files]
Source: "..\..\dist\rs7\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\RS-7 Control"; Filename: "{app}\rs7-gui.exe"
Name: "{group}\Uninstall RS-7 Control"; Filename: "{uninstallexe}"
Name: "{autodesktop}\RS-7 Control"; Filename: "{app}\rs7-gui.exe"; Tasks: desktopicon

[Registry]
; per-user PATH when installed without admin, system PATH otherwise
Root: HKA; Subkey: "{code:EnvKey}"; ValueType: expandsz; ValueName: "Path"; \
  ValueData: "{olddata};{app}"; Tasks: addpath; Check: NeedsPath(ExpandConstant('{app}'))

[Run]
Filename: "{app}\rs7-gui.exe"; Description: "Start RS-7 Control"; Flags: nowait postinstall skipifsilent

[Code]
function EnvKey(Param: string): string;
begin
  if IsAdminInstallMode then
    Result := 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
  else
    Result := 'Environment';
end;

function NeedsPath(Dir: string): Boolean;
var
  Paths: string;
begin
  if not RegQueryStringValue(HKA, EnvKey(''), 'Path', Paths) then
    Paths := '';
  Result := Pos(';' + Lowercase(Dir) + ';', ';' + Lowercase(Paths) + ';') = 0;
end;
