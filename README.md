# Codex Profiles

Windows desktop launcher for running Codex with separate local account profiles.

Codex normally reuses one local login state. Codex Profiles gives each saved profile its own `CODEX_HOME` and Chromium `user-data-dir`, so you can keep two or more accounts available on the same Windows machine without changing the default Codex data.

> This project is for local desktop account management. It is not an API-key switcher and does not automate account authentication.

## Features

- **System default Codex profile** — opens the existing Codex account and chat history without copying or modifying it.
- **Isolated account profiles** — each new profile gets an independent local data directory and browser state.
- **Manual browser switching** — the **Default browser** button opens Windows Default apps settings before you sign in.
- **Windows-native window behavior** — native title bar, minimize/maximize/close, dragging, resizing, and keyboard shortcuts remain familiar.
- **Responsive Apple-inspired UI** — wide windows use a sidebar/detail layout; narrow windows stack the sidebar above the detail view so the detail panel is never covered.
- **Local-only data** — profile metadata is stored in SQLite under `%LOCALAPPDATA%\CodexProfileLauncher`.
- **No credential storage** — the launcher never stores API keys, cookies, access tokens, or passwords.

## Requirements

- Windows 10 or Windows 11
- Python 3.11 or newer for source execution and packaging
- A local installation of Codex for Windows (the Microsoft Store/AppX package is supported)

## Run from source

```powershell
python app.py
```

The launcher detects the installed Codex executable at runtime. It does not hard-code a versioned `WindowsApps` path.

## Build the EXE

The build script creates an isolated build virtual environment and uses PyInstaller (a Python-to-EXE packager):

```powershell
.\build_exe.ps1
```

The generated one-folder application is written to:

```text
dist-v0.10\CodexProfiles\CodexProfiles.exe
```

Generated build folders and distributions are intentionally ignored by Git. Attach the EXE to a GitHub Release when publishing a binary release.

## Usage

1. Launch `CodexProfiles.exe`.
2. Select **系统默认 Codex** to open the existing local Codex state, or create a saved account profile.
3. For a new profile, enter a name and provider details. Provider profiles only write the model and Base URL fields that the launcher owns.
4. Click **打开隔离 Codex**.
5. If authentication opens in the wrong browser, click **默认浏览器**, change the Windows default browser, and continue the sign-in flow manually.

The launcher does not maintain a second cloud workspace or copy Codex chat history. Project directories are opened by each Codex window, while account isolation is handled locally through separate profile directories.

## Tests

```powershell
python -m unittest discover -s tests -v
```

The test suite covers profile storage, directory isolation, provider configuration boundaries, default Codex behavior, and Windows default-browser settings.

## Project layout

```text
app.py                 Application entry point
build_exe.ps1          Windows EXE build script
launcher/              UI, profile model, service, repository, and Codex launcher
tests/                 Contract tests
DEVELOPMENT_LOG.md     Readable development and verification log
HANDOFF.md             Maintainer handoff notes
```

## Privacy and safety

- Profile data stays on the local machine.
- Removing a profile removes only its launcher record; the profile data directory is retained.
- Existing default Codex data is not overwritten.
- The launcher does not upload account data or chat history.

## License

MIT. See [LICENSE](LICENSE).
