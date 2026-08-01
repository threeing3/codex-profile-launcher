#define MyAppVersion "0.10.0"

[Setup]
AppId={{5D0F0E0C-3CF7-4E84-9B65-7F6B0C4D2E91}
AppName=Codex Profiles
AppVersion={#MyAppVersion}
AppPublisher=threeing3
AppPublisherURL=https://github.com/threeing3/codex-profile-launcher
DefaultDirName={localappdata}\Programs\Codex Profiles
DefaultGroupName=Codex Profiles
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist-v0.10
OutputBaseFilename=CodexProfiles-Setup-v{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\CodexProfiles.exe

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："; Flags: unchecked

[Files]
Source: "dist-v0.10\CodexProfiles\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Codex Profiles"; Filename: "{app}\CodexProfiles.exe"
Name: "{autodesktop}\Codex Profiles"; Filename: "{app}\CodexProfiles.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\CodexProfiles.exe"; Description: "启动 Codex Profiles"; Flags: nowait postinstall skipifsilent
