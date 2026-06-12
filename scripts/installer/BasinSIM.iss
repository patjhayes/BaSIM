; Inno Setup Script for BasinSIM
; Build prerequisites:
;  1) Run build.ps1 -Clean -DownloadMf6
;  2) Compile this script with Inno Setup Compiler (iscc.exe)

#define MyAppName "BaSIM - Basin Simulator"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Innealta Software"
#define MyAppExeName "BasinSIM.exe"

[Setup]
AppId={{0F0C31F9-0E05-4B74-9324-1A4F524EC8C2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Innealta\BasinSIM
DefaultGroupName=Innealta\BasinSIM
DisableProgramGroupPage=yes
LicenseFile=..\..\src\legal\eula.txt
OutputDir=..\..\installer_output
OutputBaseFilename=BasinSIM_Setup_{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; Package the one-dir output contents
Source: "..\..\dist\BasinSIM\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
