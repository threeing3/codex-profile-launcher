from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from launcher.codex_app import CodexLauncher
from launcher.models import Profile, ProfileKind
from launcher.project_state import ProjectStateGuard


class ProjectStateGuardContracts(unittest.TestCase):
    def _profile(self, root: Path) -> Profile:
        return Profile.create(
            name="Isolated",
            kind=ProfileKind.ACCOUNT,
            profiles_root=root / "profiles",
        )

    @staticmethod
    def _state() -> dict[str, object]:
        return {
            "local-projects": {
                "project-1": {
                    "id": "project-1",
                    "name": "Example",
                    "rootPaths": ["C:/workspace/example"],
                }
            },
            "project-order": ["project-1"],
            "selected-project": {"type": "local", "projectId": "project-1"},
            "thread-project-assignments": {
                "thread-1": {"projectKind": "local", "projectId": "project-1"}
            },
            "sidebar-project-thread-orders": {"project-1": {"threadIds": ["thread-1"]}},
            "thread-writable-roots": {"thread-1": ["C:/workspace/example"]},
            "projectless-thread-ids": [],
            "electron-persisted-atom-state": {
                "thread-workspace-state-v1:thread-1": {"projectId": "project-1"},
                "sidebar-project-expanded-v1-codex:project-1": True,
            },
            "unrelated-setting": "keep-current-value",
        }

    @staticmethod
    def _write(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_snapshots_and_restores_empty_project_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = self._profile(Path(temporary))
            state = self._state()
            primary = profile.codex_home / ".codex-global-state.json"
            backup = profile.codex_home / ".codex-global-state.json.bak"
            self._write(primary, state)
            self._write(backup, state)
            guard = ProjectStateGuard()

            self.assertFalse(guard.prepare(profile))
            snapshot = profile.codex_home.parent / "launcher-state" / "project-state-snapshot.json"
            self.assertTrue(snapshot.is_file())

            empty = {
                "local-projects": {},
                "electron-persisted-atom-state": {},
                "unrelated-setting": "keep-current-value",
            }
            self._write(primary, empty)
            self._write(backup, empty)
            self.assertTrue(guard.prepare(profile))

            for path in (primary, backup):
                restored = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(restored["local-projects"]["project-1"]["name"], "Example")
                self.assertEqual(restored["unrelated-setting"], "keep-current-value")

    def test_repairs_missing_backup_from_valid_primary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = self._profile(Path(temporary))
            state = self._state()
            primary = profile.codex_home / ".codex-global-state.json"
            self._write(primary, state)
            ProjectStateGuard().prepare(profile)
            backup = profile.codex_home / ".codex-global-state.json.bak"
            backup.write_text("not json", encoding="utf-8")

            self.assertFalse(ProjectStateGuard().prepare(profile))
            self.assertEqual(json.loads(backup.read_text(encoding="utf-8")), state)

    def test_does_not_invent_projects_without_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = self._profile(Path(temporary))
            primary = profile.codex_home / ".codex-global-state.json"
            backup = profile.codex_home / ".codex-global-state.json.bak"
            empty = {"local-projects": {}}
            self._write(primary, empty)
            self._write(backup, empty)

            self.assertFalse(ProjectStateGuard().prepare(profile))
            self.assertEqual(json.loads(primary.read_text(encoding="utf-8")), empty)

    def test_launcher_never_duplicates_an_existing_profile_window(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = self._profile(Path(temporary))
            locator = Mock()
            guard = Mock()
            launcher = CodexLauncher(locator, guard)
            with patch.object(launcher, "_profile_process_ids", return_value=[4242]):
                with self.assertRaisesRegex(RuntimeError, "已经在运行"):
                    launcher.launch(profile)
            guard.prepare.assert_not_called()


if __name__ == "__main__":
    unittest.main()
