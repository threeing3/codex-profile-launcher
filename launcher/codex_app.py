from __future__ import annotations

import os
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .models import Profile
from .project_state import ProjectStateGuard


CREATE_NO_WINDOW = 0x08000000
GRACEFUL_CLOSE_TIMEOUT_SECONDS = 5.0
FORCED_CLOSE_TIMEOUT_SECONDS = 5.0


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
    def __init__(
        self,
        locator: CodexAppLocator | None = None,
        state_guard: ProjectStateGuard | None = None,
    ) -> None:
        self.locator = locator or CodexAppLocator()
        self.state_guard = state_guard or ProjectStateGuard()
        self._running: dict[str, RunningProfile] = {}

    def launch(self, profile: Profile) -> RunningProfile:
        if profile.is_system_default:
            return self.launch_default(profile.id)

        current = self._running.get(profile.id)
        if current and current.is_running:
            return current

        if self.is_profile_process_running(profile):
            raise RuntimeError(
                f"配置“{profile.name}”的 Codex 窗口或后台进程已经在运行。"
                "请使用“关闭进程”清理残留进程，或使用“重启 Codex”。"
            )

        self.prepare_profile_state(profile)
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
        profile = Profile.system_default()
        current = self._running.get(profile_id)
        if current and current.is_running:
            return current
        if self.is_profile_process_running(profile):
            raise RuntimeError(
                "系统默认 Codex 窗口或后台进程已经在运行。"
                "请使用“关闭进程”清理残留进程，或使用“重启 Codex”。"
            )
        self.prepare_profile_state(profile)
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

    def is_profile_process_running(self, profile: Profile) -> bool:
        return bool(self._profile_process_ids(profile))

    def running_profile_ids(self, profiles: Iterable[Profile]) -> frozenset[str]:
        """Detect every running profile from one Windows process query."""

        rows = self._root_process_rows()
        return frozenset(
            profile.id
            for profile in profiles
            if self._profile_process_ids(profile, rows)
        )

    def prepare_profile_state(self, profile: Profile) -> bool:
        """Repair only when no matching Codex process can still write the state."""

        if self.is_profile_process_running(profile):
            return False
        return self.state_guard.prepare(profile)

    def snapshot_profile_state(self, profile: Profile) -> bool:
        """Save a read-only snapshot during launcher shutdown."""

        return self.state_guard.snapshot_if_valid(profile)

    def request_close_profile(self, profile: Profile) -> bool:
        process_ids = self._profile_process_ids(profile)
        if not process_ids:
            return True
        self._request_close_processes(process_ids)
        return not self.is_profile_process_running(profile)

    def stop_profile(
        self,
        profile: Profile,
        *,
        graceful_timeout: float = GRACEFUL_CLOSE_TIMEOUT_SECONDS,
        forced_timeout: float = FORCED_CLOSE_TIMEOUT_SECONDS,
    ) -> bool:
        """Close a profile normally, then terminate only its residual process tree."""

        try:
            self.snapshot_profile_state(profile)
        except OSError:
            # Process cleanup must remain available when Codex has a state file locked.
            pass

        process_ids = self._profile_process_ids(profile)
        if not process_ids:
            self._running.pop(profile.id, None)
            return True

        self._request_close_processes(process_ids)
        if self._wait_for_profile_exit(profile, graceful_timeout):
            self._running.pop(profile.id, None)
            return True

        residual_ids = self._profile_process_ids(profile)
        if residual_ids:
            self._terminate_process_trees(residual_ids)
        stopped = self._wait_for_profile_exit(profile, forced_timeout)
        if stopped:
            self._running.pop(profile.id, None)
        return stopped

    def restart_profile(self, profile: Profile) -> RunningProfile:
        """Fully stop one profile before launching it against the same state directory."""

        if not self.stop_profile(profile):
            raise RuntimeError(
                f"无法结束“{profile.name}”的残留进程，请在任务管理器中检查后重试。"
            )
        return self.launch(profile)

    @staticmethod
    def _request_close_processes(process_ids: list[int]) -> None:
        joined = ",".join(str(process_id) for process_id in process_ids)
        script = (
            f"$ids=@({joined}); foreach($id in $ids){{"
            "$p=Get-Process -Id $id -ErrorAction SilentlyContinue;"
            "if($p){$null=$p.CloseMainWindow()}}}"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            check=False,
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
        )

    @staticmethod
    def _terminate_process_trees(process_ids: list[int]) -> None:
        for process_id in process_ids:
            subprocess.run(
                ["taskkill.exe", "/PID", str(process_id), "/T", "/F"],
                check=False,
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
            )

    def _wait_for_profile_exit(self, profile: Profile, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while self.is_profile_process_running(profile):
            if time.monotonic() >= deadline:
                return False
            time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
        return True

    def _profile_process_ids(
        self,
        profile: Profile,
        rows: list[dict[str, Any]] | None = None,
    ) -> list[int]:
        process_rows = self._root_process_rows() if rows is None else rows
        matched: list[int] = []
        expected_data_dir = str(profile.user_data_dir).casefold()
        for row in process_rows:
            command_line = str(row.get("CommandLine") or "")
            lowered = command_line.casefold()
            if profile.is_system_default:
                belongs = "--user-data-dir" not in lowered
            else:
                belongs = "--user-data-dir" in lowered and expected_data_dir in lowered
            if belongs:
                try:
                    matched.append(int(row["ProcessId"]))
                except (KeyError, TypeError, ValueError):
                    continue
        return matched

    @staticmethod
    def _root_process_rows() -> list[dict[str, Any]]:
        script = (
            "Get-CimInstance Win32_Process -Filter \"Name='ChatGPT.exe'\" | "
            "Where-Object { $_.CommandLine -and $_.CommandLine -notmatch '--type=' } | "
            "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []
        rows = payload if isinstance(payload, list) else [payload]
        return [row for row in rows if isinstance(row, dict)]
