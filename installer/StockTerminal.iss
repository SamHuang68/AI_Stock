; ============================================================
;  Stock Terminal — Inno Setup 安裝腳本
;  個人安裝(免系統管理員)。server 已用 PyInstaller 凍結成 server.exe,
;  內含 Python,收件人不需另外安裝任何東西。
;  編譯方式:安裝 Inno Setup 後,用 ISCC 編譯,或直接跑 build_installer.bat。
; ============================================================

#define MyAppName "Stock Terminal"
#define MyAppVersion "4.0"
#define MyAppExe "server.exe"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Sam
DefaultDirName={localappdata}\Programs\Stock Terminal
DefaultGroupName=Stock Terminal
DisableProgramGroupPage=yes
DisableDirPage=auto
; 個人安裝:不需系統管理員權限
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=dist_installer
OutputBaseFilename=StockTerminal-Setup-v{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExe}

[Languages]
Name: "cht"; MessagesFile: "compiler:Languages\ChineseTraditional.isl"
Name: "en";  MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; 凍結好的 server(含 Python) — 由 build_installer.bat 產生到 installer\build\
Source: "build\server.exe";            DestDir: "{app}";       Flags: ignoreversion
; 已預先 build 好的 UI(不需在收件人端再跑 build_v2.py)
Source: "..\stock_terminal_v2.html";   DestDir: "{app}";       Flags: ignoreversion
; 前端模組
Source: "..\src\*";                    DestDir: "{app}\src";   Flags: ignoreversion recursesubdirs createallsubdirs
; 資料:只放 ETF 目錄設定,不含任何機密/歷史快照
Source: "..\data\etf_catalog.json";    DestDir: "{app}\data";  Flags: ignoreversion

[Dirs]
; server 執行時會寫入的資料夾(個人目錄下,可寫,免權限)
Name: "{app}\data\etf_history"
Name: "{app}\data\chip_history"

[Icons]
Name: "{group}\Stock Terminal";          Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}"
Name: "{group}\Uninstall Stock Terminal"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Stock Terminal";    Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
; 安裝完可選擇立即啟動(server.exe 啟動後會自動開瀏覽器)
Filename: "{app}\{#MyAppExe}"; Description: "立即啟動 Stock Terminal"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 移除前先關掉還在跑的 server
Filename: "{cmd}"; Parameters: "/c taskkill /im {#MyAppExe} /f"; Flags: runhidden; RunOnceId: "killserver"
