"""Protect Codex project metadata across isolated profile launches.

The Codex desktop app stores local project assignments in two JSON files.  A
profile launch must never start while those files are half-written or while a
known-good project index is only present in one copy.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import time
from typing import Any, Iterator
from uuid import uuid4

from .models import Profile


PROJECT_KEYS = (
    "local-projects",
    "project-order",
    "selected-project",
    "thread-project-assignments",
    "sidebar-project-thread-orders",
    "thread-writable-roots",
    "projectless-thread-ids",
)


class ProjectStateGuard:
    """Snapshot and repair project mappings before a profile is launched."""

    def snapshot_if_valid(self, profile: Profile) -> bool:
        """Persist a known-good state snapshot without changing Codex files."""

        profile.codex_home.mkdir(parents=True, exist_ok=True)
        paths = self._paths(profile)
        paths["snapshot"].parent.mkdir(parents=True, exist_ok=True)
        with self._lock(paths["lock"]):
            primary = self._read_json(paths["primary"])
            backup = self._read_json(paths["backup"])
            candidate = self._best_state(primary, backup, paths)
            if not self._has_projects(candidate):
                return False
            self._save_snapshot(paths["snapshot"], candidate)
            self._log(profile, "多开器关闭前已保存当前有效项目快照。")
            return True

    def prepare(self, profile: Profile) -> bool:
        """Repair a profile and return whether a snapshot was restored."""

        profile.codex_home.mkdir(parents=True, exist_ok=True)
        paths = self._paths(profile)
        paths["snapshot"].parent.mkdir(parents=True, exist_ok=True)
        with self._lock(paths["lock"]):
            primary = self._read_json(paths["primary"])
            backup = self._read_json(paths["backup"])
            snapshot = self._read_snapshot(paths["snapshot"])
            candidate = self._best_state(primary, backup, paths)

            if self._has_projects(candidate):
                self._save_snapshot(paths["snapshot"], candidate)
                if primary != candidate or backup != candidate:
                    self._backup_live_state(paths)
                    self._write_pair(paths, candidate)
                    self._log(
                        profile,
                        "主状态文件与备用副本不一致，已在启动前同步。",
                    )
                return False

            if self._has_projects(snapshot):
                restored = self._merge_project_state(primary or backup or {}, snapshot)
                self._backup_live_state(paths)
                self._write_pair(paths, restored)
                self._save_snapshot(paths["snapshot"], restored)
                self._log(
                    profile,
                    "检测到项目索引为空，已从最近的可验证快照恢复。",
                )
                return True

            self._log(profile, "未发现可恢复的项目快照，保留现有状态。")
            return False

    @staticmethod
    def _paths(profile: Profile) -> dict[str, Path]:
        root = profile.codex_home
        state_root = root.parent / "launcher-state"
        return {
            "primary": root / ".codex-global-state.json",
            "backup": root / ".codex-global-state.json.bak",
            "snapshot": state_root / "project-state-snapshot.json",
            "backup_dir": state_root / "state-backups",
            "lock": state_root / "project-state.lock",
        }

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @classmethod
    def _read_snapshot(cls, path: Path) -> dict[str, Any] | None:
        payload = cls._read_json(path)
        if not payload:
            return None
        state = payload.get("state")
        return state if isinstance(state, dict) else None

    @classmethod
    def _best_state(
        cls,
        primary: dict[str, Any] | None,
        backup: dict[str, Any] | None,
        paths: dict[str, Path],
    ) -> dict[str, Any] | None:
        candidates = [item for item in (primary, backup) if item is not None]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (
                cls._project_count(item),
                cls._mtime(paths["primary"] if item is primary else paths["backup"]),
            ),
        )

    @staticmethod
    def _mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    @staticmethod
    def _project_count(state: dict[str, Any] | None) -> int:
        if not state:
            return 0
        projects = state.get("local-projects")
        return len(projects) if isinstance(projects, dict) else 0

    @classmethod
    def _has_projects(cls, state: dict[str, Any] | None) -> bool:
        return cls._project_count(state) > 0

    @classmethod
    def _merge_project_state(
        cls,
        current: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        restored = dict(current)
        for key in PROJECT_KEYS:
            if key in snapshot:
                restored[key] = snapshot[key]

        current_atoms = current.get("electron-persisted-atom-state")
        snapshot_atoms = snapshot.get("electron-persisted-atom-state")
        if isinstance(current_atoms, dict) and isinstance(snapshot_atoms, dict):
            atoms = dict(current_atoms)
            for key, value in snapshot_atoms.items():
                if (
                    key.startswith("thread-workspace-state-v1:")
                    or key.startswith("sidebar-project-")
                    or key in {"flat-project-sidebar-preferences-v1", "sidebar-project-list-expanded-v1"}
                ):
                    atoms[key] = value
            restored["electron-persisted-atom-state"] = atoms
        elif isinstance(snapshot_atoms, dict):
            restored["electron-persisted-atom-state"] = snapshot_atoms
        return restored

    @staticmethod
    def _write_pair(paths: dict[str, Path], state: dict[str, Any]) -> None:
        payload = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        for target_key in ("primary", "backup"):
            target = paths[target_key]
            temporary = target.with_name(f".{target.name}.codexprofiles-{uuid4().hex}.tmp")
            try:
                with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                json.loads(temporary.read_text(encoding="utf-8"))
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)

    @classmethod
    def _save_snapshot(cls, path: Path, state: dict[str, Any]) -> None:
        payload = {
            "schema": 1,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "state": state,
        }
        temporary = path.with_name(f".{path.name}.codexprofiles-{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def _backup_live_state(cls, paths: dict[str, Path]) -> None:
        existing = [
            paths[key]
            for key in ("primary", "backup")
            if paths[key].is_file()
        ]
        if not existing:
            return
        destination = paths["backup_dir"] / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        destination.mkdir(parents=True, exist_ok=False)
        for source in existing:
            shutil.copy2(source, destination / source.name)

    @staticmethod
    @contextmanager
    def _lock(path: Path) -> Iterator[None]:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as handle:
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except ImportError:
                yield

    @staticmethod
    def _log(profile: Profile, message: str) -> None:
        log_path = profile.codex_home.parent / "launcher-state" / "project-state.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {message}\n")
