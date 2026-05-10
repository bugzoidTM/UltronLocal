; ============================================================
; UltronPRO — Script Inno Setup (instalador .exe profissional)
; ============================================================
; Para compilar: instale o Inno Setup (https://jrsoftware.org/isdl.php)
; e execute: iscc build\installer\ultronpro_setup.iss
; ============================================================

#define AppName "UltronPRO"
#define AppVersion "1.0"
#define AppPublisher "UltronPRO"
#define AppExeName "UltronPRO.exe"

[Setup]
AppId={{7F3A2C1B-DEAD-BEEF-CAFE-0123456789AB}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=..\dist\installer
OutputBaseFilename=UltronPRO_Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; Ícone da janela do instalador
;SetupIconFile=..\icon.ico

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; O executável principal (gerado pelo PyInstaller)
Source: "..\dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; Pasta de dados do backend (modelos de voz, banco, configurações)
Source: "..\..\backend\data\*"; DestDir: "{app}\backend\data"; Flags: ignoreversion recursesubdirs createallsubdirs

; Pasta de tasks
Source: "..\..\tasks\*"; DestDir: "{app}\tasks"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__"

; Pasta de binários (piper TTS)
Source: "..\..\backend\bin\*"; DestDir: "{app}\backend\bin"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\backend\data\logs"
