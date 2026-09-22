#define MyAppName "Secretaría de Tránsito y Transporte - Desvinculaciones"
#define MyAppVersion "1.1.21"
#define MyAppPublisher "Secretaría de Tránsito y Transporte"
#define MyAppExeName "SistemaDesvinculaciones.exe"
#if FileExists("OllamaSetup.exe")
  #define HasOllamaInstaller
#endif
#if DirExists("dist_pdf_editor\EditorPDFLocal")
  #define HasPdfEditor
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
SetupIconFile=icon.ico
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
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion
#ifdef HasOllamaInstaller
Source: "OllamaSetup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
#endif
#ifdef HasPdfEditor
Source: "dist_pdf_editor\EditorPDFLocal\*"; DestDir: "{app}\EditorPDFLocal"; Flags: ignoreversion recursesubdirs createallsubdirs
#endif

[Run]
#ifdef HasOllamaInstaller
Filename: "{tmp}\OllamaSetup.exe"; Parameters: "/silent"; Flags: runhidden waituntilterminated; Check: ShouldInstallOllama
#endif

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"
#ifdef HasPdfEditor
Name: "{group}\Editor PDF local"; Filename: "{app}\EditorPDFLocal\EditorPDFLocal.exe"; WorkingDir: "{app}\EditorPDFLocal"
#endif

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

function OllamaExecutablePath(): String;
begin
  if FileExists(ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe')) then
    Result := ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe')
  else if FileExists(ExpandConstant('{pf}\Ollama\ollama.exe')) then
    Result := ExpandConstant('{pf}\Ollama\ollama.exe')
  else
    Result := '';
end;

function ShouldInstallOllama(): Boolean;
var
  InstalledMajor, InstalledMinor, InstalledRelease, InstalledBuild: Word;
  BundleMajor, BundleMinor, BundleRelease, BundleBuild: Word;
  InstalledPath: String;
begin
  if not OllamaExecutableExists() then
  begin
    Result := True;
    exit;
  end;
  InstalledPath := OllamaExecutablePath();
  if not GetVersionComponents(
    InstalledPath,
    InstalledMajor, InstalledMinor, InstalledRelease, InstalledBuild
  ) then
  begin
    Result := False;
    exit;
  end;
  if not GetVersionComponents(
    ExpandConstant('{tmp}\OllamaSetup.exe'),
    BundleMajor, BundleMinor, BundleRelease, BundleBuild
  ) then
  begin
    Result := False;
    exit;
  end;
  Result :=
    (BundleMajor > InstalledMajor) or
    ((BundleMajor = InstalledMajor) and (BundleMinor > InstalledMinor)) or
    ((BundleMajor = InstalledMajor) and (BundleMinor = InstalledMinor) and
      (BundleRelease > InstalledRelease)) or
    ((BundleMajor = InstalledMajor) and (BundleMinor = InstalledMinor) and
      (BundleRelease = InstalledRelease) and (BundleBuild > InstalledBuild));
end;
