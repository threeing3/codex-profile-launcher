from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .models import Profile


CREATE_NO_WINDOW = 0x08000000


class CodexAppNotFound(RuntimeError):
    pass


class CodexAppLocator:
    def locate(self) -> Path:
        install_location = self._find_store_install_location()
        executable = install_location / "app" / "ChatGPT.exe"
        if not executable.is_file():
            raise CodexAppNotFound(f"Codex executable not found at {executable}")
        return executable

    @staticmethod
    def _find_store_install_location() -> Path:
        command = (
            "(Get-AppxPackage -Name OpenAI.Codex | "
            "Select-Object -First 1 -ExpandProperty InstallLocation)"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
        location = result.stdout.strip()
        if result.returncode != 0 or not location:
            raise CodexAppNotFound("Microsoft Store package OpenAI.Codex was not found.")
        return Path(location)


@dataclass(slots=True)
class RunningProfile:
    profile_id: str
    process: subprocess.Popen[bytes]

    @property
    def is_running(self) -> bool:
        return self.process.poll() is None


class CodexLauncher:
    def __init__(self, locator: CodexAppLocator | None = None) -> None:
        self.locator = locator or CodexAppLocator()
        self._running: dict[str, RunningProfile] = {}

    def launch(self, profile: Profile) -> RunningProfile:
        if profile.is_system_default:
            return self.launch_default(profile.id)

        current = self._running.get(profile.id)
        if current and current.is_running:
            return current

        profile.codex_home.mkdir(parents=True, exist_ok=True)
        profile.user_data_dir.mkdir(parents=True, exist_ok=True)
        executable = self.locator.locate()
        command = [str(executable), f"--user-data-dir={profile.user_data_dir}"]
        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(profile.codex_home)
        process = subprocess.Popen(
            command,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        running = RunningProfile(profile.id, process)
        self._running[profile.id] = running
        return running

    def launch_default(
        self,
        profile_id: str = "__system_default__",
    ) -> RunningProfile:
        executable = self.locator.locate()
        environment = os.environ.copy()
        environment.pop("CODEX_HOME", None)
        process = subprocess.Popen(
            [str(executable)],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        running = RunningProfile(profile_id, process)
        self._running[profile_id] = running
        return running

    def is_running(self, profile_id: str) -> bool:
        running = self._running.get(profile_id)
        return bool(running and running.is_running)

    def refresh(self) -> None:
        stopped = [profile_id for profile_id, item in self._running.items() if not item.is_running]
        for profile_id in stopped:
            self._running.pop(profile_id, None)
