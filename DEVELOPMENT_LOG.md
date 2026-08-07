# Development log

## 2026-08-07 — Shared user skills

- Added a central user-skill library under `%LOCALAPPDATA%\CodexProfileLauncher\shared-skills` while keeping each account's `.system` skills, plugin state, login data, chats, and projects isolated.
- Added a preview-first migration flow that scans every profile, deduplicates identical skills, requires an explicit source choice for content conflicts, and warns about likely credentials.
- Added per-skill Windows directory junctions, operation staging, pre-change backups, filesystem rollback, readable operation logs, persistent policies and bindings, and permanent skill snapshots.
- Added account-level and per-skill detach operations that preserve independent copies, launch-time broken-link validation, snapshot restoration, external-change snapshots, and automatic recovery from unexpected shared-skill deletion.
- Added the dedicated “共享技能” management window and account status summaries. Real profile migration remains gated behind the UI preview and confirmation step.
- Added eleven skill-sharing contract tests. The complete suite now contains 23 passing tests, including real Windows junction behavior, failure rollback, and global removal in temporary directories.

## 2026-08-02 — Open-source cleanup

- Removed obsolete design references, generated build environments, intermediate build folders, and Python cache directories.
- Kept the current source tree, tests, build script, documentation, and the locally generated one-folder EXE.
- Added a project-level MIT license and a public-facing Chinese README focused on local account isolation and safe boundaries.

## 2026-08-02 — Windows installer release build

- Installed Inno Setup 6.7.3 locally and added `installer.iss` plus `build_release.ps1`.
- The release script now builds the one-folder EXE first, checks build exit codes, and then creates `dist-v0.10\CodexProfiles-Setup-v0.10.0.exe`.
- The installer is per-user by default, creates an optional desktop shortcut, registers a Start-menu shortcut, and keeps account data under `%LOCALAPPDATA%\CodexProfileLauncher`.
- First packaging attempt detected a running project EXE and correctly failed to replace its files; after stopping only that project process, the clean rebuild and Inno Setup compile completed successfully.

## 2026-08-02 — Sidebar overlap fix

- Reproduced the reported overlap on a high-DPI Windows display.
- Root cause: the default `Secondary.TButton` request width made the bottom action row wider than the fixed sidebar. Grid then expanded the sidebar's internal column, and the `Treeview` account list extended into the main panel.
- Fixed by giving the bottom actions explicit compact widths. No decorative separator or overlay workaround was added.
- Verified widget geometry at the default window size: sidebar width 292, main panel starts at x=293, account list width 250.

## 2026-08-01 — High-DPI responsive layout

- Lowered the minimum window width to 640 logical pixels so compact mode can be reached on high-DPI displays.
- Narrow windows stack the account sidebar above the detail panel; the detail content keeps the full available width.
- Toolbar actions and detail value wrapping adapt to the compact layout.

## 2026-08-01 — Windows operation, Apple-inspired content

- Kept the native Windows title bar, minimize/maximize/close controls, dragging, and resizing.
- Applied the Apple-inspired visual direction only to the content area: light neutral palette, grouped cards, system-blue primary action, and consistent typography.
- Reverted the borderless custom title-bar experiment because it made native Windows window management and automation less reliable.

## Verification

```powershell
python -m compileall -q launcher tests
python -m unittest discover -s tests -v
.\build_exe.ps1
.\build_release.ps1
```

The current test suite contains 12 contract tests covering profile storage, directory isolation, provider configuration boundaries, default Codex behavior, and browser settings. The current one-folder build is emitted under `dist-v0.10\CodexProfiles\`, and the installable release artifact is emitted under `dist-v0.10\CodexProfiles-Setup-v0.10.0.exe`; both are ignored by Git.
