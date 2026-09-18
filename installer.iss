#define MyAppName "Secretaría de Tránsito y Transporte - Desvinculaciones"
#define MyAppVersion "1.1.18"
#define MyAppPublisher "Secretaría de Tránsito y Transporte"
#define MyAppExeName "SistemaDesvinculaciones.exe"
#if FileExists("OllamaSetup.exe")
  #define HasOllamaInstaller
#endif

[Setup]
AppId={{B2BFF6E6-4B77-4D76-A6C8-2D0B7C3A4A01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\SistemaDesvinculaciones
DefaultGroupName={#MyAppName}
OutputDir=installer
OutputBaseFilename=SistemaDesvinculaciones-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=images\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no
; La aplicación guarda sus datos en %LOCALAPPDATA%, fuera de {app}.
; El actualizador desinstala la versión anterior antes de iniciar esta instalación.
Uninstallable=yes

[InstallDelete]
Type: filesandordirs; Name: "{app}\*"

[Files]
Source: "dist\SistemaDesvinculaciones\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "images\icon.ico"; DestDir: "{app}\images"; Flags: ignoreversion
#ifdef HasOllamaInstaller
Source: "OllamaSetup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
#endif

[Run]
#ifdef HasOllamaInstaller
Filename: "{tmp}\OllamaSetup.exe"; Parameters: "/silent"; Flags: runhidden waituntilterminated; Check: ShouldInstallOllama
#endif

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\images\icon.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\images\icon.ico"

; La aplicación se abre manualmente desde el acceso directo del menú de inicio.
; Evitamos iniciar el proceso desde el instalador para no generar el error
; "CallSpawnServer: Unexpected response: 0" durante la finalización.

[Code]
function OllamaExecutableExists(): Boolean;
begin
  Result :=
    FileExists(ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe')) or
    FileExists(ExpandConstant('{pf}\Ollama\ollama.exe'));
end;

function ShouldInstallOllama(): Boolean;
begin
  Result := not OllamaExecutableExists();
end;
