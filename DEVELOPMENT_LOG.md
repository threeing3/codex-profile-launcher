# Development log

## 2026-08-09 — Shared-skill workflow and sidebar clarity

- Reworked the account sidebar so compact windows keep the account list visible: account creation and skill-library entry now live in the title toolbar, nonessential labels collapse at low height, and the sidebar list expands to the full available width.
- Replaced the single dense shared-skill screen with three task-focused tabs: migration guidance, account and per-skill controls, and recovery/maintenance.
- Added a three-step migration guide, explicit next-action text, highlighted unresolved conflicts, contextual button labels, and disabled actions until their required selections exist.
- Corrected empty-library and already-synchronized states so the interface says “等待首次迁移” or “共享库已是最新” instead of implying that sharing is active.
- Verified the compact main window at 820×600, the conflict-selection state transition, Python compilation, and all 23 contract tests.

## 2026-08-09 — Windows application icon and formal rebuild

- Generated an original multi-profile application icon and converted it into a multi-resolution Windows ICO containing sizes from 16×16 through 256×256.
- Added a stable Windows AppUserModelID, applied the icon to the Tk root window, embedded the icon into `CodexProfiles.exe`, and bundled the runtime ICO alongside the executable.
- Made the build output and work directories configurable so a candidate can be built and verified without touching the currently running formal program.
- Ran all 23 contract tests, produced an isolated staging build, extracted the associated icon back from the generated EXE, and verified that the staging window started and closed normally with exit code 0.
- Preserved the previous formal program at `%LOCALAPPDATA%\CodexProfileLauncher\release-backups\CodexProfiles-20260809-112848`, moved the verified candidate into `dist-v0.10\CodexProfiles`, and confirmed that the formal window exposes both large and small Windows class icons.
- Stored the readable test, packaging, staging-launch, and replacement transcript at `build-logs\formal-rebuild-20260809-112658.log` (ignored by Git as a local build artifact).

## 2026-08-09 — High-DPI sidebar correction and transparent icon

- Reproduced the remaining default-window failure from the user screenshot: at approximately 200% Tk scaling, the sidebar title competed with two toolbar buttons, the account summary text was clipped, and the 680-pixel client height left only about 653 pixels for 779 pixels of detail content.
- Rebuilt the sidebar as five independent regions—brand, search, saved-account label, expanding account list, and bottom actions—so buttons no longer alter the title or list width. Short account-state labels keep both current rows fully visible.
- Changed the default window to a screen-bounded, centered 1180×900 layout. The content scrollbar now appears only when required, while the existing stacked compact mode remains available for smaller screens.
- Corrected the system-default launch card wording and kept the full details table, action buttons, and explanatory note visible together at the detected 200% scaling.
- Replaced the dark square icon with a bright blue/yellow/coral multi-profile mark. The built-in image generator produced a flat chroma-key source; the image skill's removal helper generated the final RGBA PNG, which was cropped, padded, and converted into a 16–256 pixel multi-resolution ICO.
- Verified transparent corners in the final PNG, bundled ICO, and the 32×32 icon extracted back from the packaged EXE. The extracted EXE icon contains 336 fully transparent pixels and all four corner alpha values are zero.
- Passed Python compilation, all 23 contract tests, real default and 820×600 compact geometry probes, source screenshots, a clean staging package launch, and packaged large/small window-icon checks.
- Preserved the prior formal program at `%LOCALAPPDATA%\CodexProfileLauncher\release-backups\CodexProfiles-20260809-114601`, replaced the formal directory, and left the verified new program running. The readable experiment transcript is `build-logs\ui-rework-20260809-113829.log`.

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

## 2026-08-11 — Project index recovery guard

- Reproduced the recurring isolated-account failure: the Codex desktop window kept its `state_5.sqlite` conversations, while `.codex-global-state.json` and its `.bak` copy were both reduced to an empty `local-projects` map.
- Added `launcher/project_state.py` with a per-profile lock, readable recovery log, timestamped pre-repair backups, and a project-state snapshot stored outside the Codex state files.
- `CodexLauncher` now validates and snapshots project metadata before launching an isolated profile. If both state copies are empty or divergent, only the known project-related fields are restored from the last validated snapshot; ordinary chats are never guessed into a project.
- Writes are atomic and applied to both the primary and backup state files. A malformed or missing backup is repaired from the valid copy.
- The system-default `.codex` profile uses the same guard, so the default window is protected as well as isolated profiles. Launching a profile that is already detected as running is rejected instead of creating a duplicate process.
- The launcher now snapshots valid project state when its own window closes, skips all state writes while a matching ChatGPT process is alive, and performs repair during startup before any new Codex process is launched. This closes the launcher-restart race instead of relying only on a later manual recovery.
- Added four contract tests covering snapshot/restore, backup repair, no-snapshot safety, and duplicate-window prevention. The full suite now contains 27 passing tests.
- Test log: `build-logs/project-state-guard-20260811-final.log`.

## 2026-08-13 — Window process controls

- Reproduced the blocked-launch state where a Codex window had been closed but its root `ChatGPT.exe` process remained alive. The launcher detected the process correctly, but offered no action to close or restart it.
- Added one-query process discovery for the system-default profile and all isolated profiles, including processes created before the current launcher session.
- Added explicit `关闭进程` and `重启 Codex` controls to each profile. Close first requests a normal window shutdown, waits five seconds, and then force-terminates only the selected profile's remaining process tree. Restart uses the same full stop flow before launching again.
- Valid project state is snapshotted before process cleanup. No profile directory, project, or chat record is deleted.
- The account list, status badge, launch button, and process controls now reflect externally detected processes instead of relying only on the launcher's in-memory process map.
- Added four contract tests covering profile-specific discovery, graceful close, residual-process termination, and stop-before-restart ordering. The full suite now contains 31 passing tests.
- Test and build log: `build-logs/process-control-20260813.log`.

## 2026-08-13 — Runtime dependency packaging guard

- The first process-control build failed at startup with `_ctypes` reporting a DLL load error. The build warning had listed unresolved Conda runtime libraries, but the earlier smoke check incorrectly treated the still-open error process as a successful launch.
- Confirmed that the broken `_internal` directory lacked `ffi.dll`, `libbz2.dll`, `liblzma.dll`, `sqlite3.dll`, `tcl86t.dll`, and `tk86t.dll`, while the last working release contained all six.
- Updated `build_exe.ps1` to resolve the active Python base directory, add each required runtime DLL explicitly, and fail the build if any expected DLL is absent from the packaged application.
- Added an automatic runtime verification step to every one-folder build. It waits up to 15 seconds for the exact expected launcher window title and rejects an exception dialog instead of merely checking whether a process remains alive.
- Rebuilt and replaced the formal application. The verified runtime opened normally with all six dependencies present.

## Verification

```powershell
python -m compileall -q launcher tests
python -m unittest discover -s tests -v
.\build_exe.ps1
.\build_release.ps1
```

The current test suite contains 31 contract tests covering profile storage, directory isolation, provider configuration boundaries, default Codex behavior, browser settings, shared-skill migration safety, project-state recovery, and profile-specific process control. The current one-folder build is emitted under `dist-v0.10\CodexProfiles\`, and the installable release artifact is emitted under `dist-v0.10\CodexProfiles-Setup-v0.10.0.exe`; both are ignored by Git.
