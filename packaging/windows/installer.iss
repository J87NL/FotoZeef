#define AppName "FotoZeef"
#define AppVersion "0.4.1"
#define AppPublisher "Johan Montenij"
#define AppExe "FotoZeef.exe"

[Setup]
AppId={{B1F2B0F2-7D77-4E2B-9E0C-3E6B4B5A1D21}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputBaseFilename=FotoZeef-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
WizardStyle=modern
; Asks to close a running FotoZeef before replacing its files.
CloseApplications=yes
; Follows the Windows language without asking.
ShowLanguageDialog=auto

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "nl"; MessagesFile: "compiler:Languages\Dutch.isl"

[CustomMessages]
en.NewerInstalled=FotoZeef %1 is already installed, which is newer than this installer (%2).%n%nAn older version cannot open projects saved by a newer one, so this installer stops here. Download the latest version instead.
nl.NewerInstalled=FotoZeef %1 is al geïnstalleerd en is nieuwer dan dit installatieprogramma (%2).%n%nEen oudere versie kan projecten van een nieuwere versie niet openen, dus de installatie stopt hier. Download in plaats daarvan de nieuwste versie.

[InstallDelete]
; The previous version's program files, so nothing stale is left behind.
; Projects, settings and thumbnails live in the user profile, not here.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\..\dist\FotoZeef\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{B1F2B0F2-7D77-4E2B-9E0C-3E6B4B5A1D21}_is1';

{ Takes the next number off a dotted version such as 0.10.2. }
function NextNumber(var Version: String): Integer;
var
  Dot: Integer;
begin
  Dot := Pos('.', Version);
  if Dot = 0 then
  begin
    Result := StrToIntDef(Version, 0);
    Version := '';
  end
  else
  begin
    Result := StrToIntDef(Copy(Version, 1, Dot - 1), 0);
    Delete(Version, 1, Dot);
  end;
end;

{ 1 when A is newer than B, -1 when older, 0 when the same. }
function CompareVersions(A, B: String): Integer;
var
  X, Y: Integer;
begin
  Result := 0;
  while (Result = 0) and ((A <> '') or (B <> '')) do
  begin
    X := NextNumber(A);
    Y := NextNumber(B);
    if X > Y then
      Result := 1
    else if X < Y then
      Result := -1;
  end;
end;

function InstalledVersion(): String;
begin
  Result := '';
  if not RegQueryStringValue(HKCU, UninstallKey, 'DisplayVersion', Result) then
    RegQueryStringValue(HKLM, UninstallKey, 'DisplayVersion', Result);
end;

function InitializeSetup(): Boolean;
var
  Installed: String;
begin
  Result := True;
  Installed := InstalledVersion();
  if (Installed <> '') and (CompareVersions(Installed, '{#AppVersion}') > 0) then
  begin
    SuppressibleMsgBox(FmtMessage(CustomMessage('NewerInstalled'), [Installed, '{#AppVersion}']),
      mbError, MB_OK, IDOK);
    Result := False;
  end;
end;
