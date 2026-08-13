from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from launcher.codex_app import CodexLauncher, RunningProfile
from launcher.models import Profile, ProfileKind
from launcher.paths import AppPaths
from launcher.provider_config import initialize_provider_config, render_provider_config, sync_provider_config
from launcher.repository import ProfileRepository
from launcher.service import ProfileService


class ProfileContracts(unittest.TestCase):
    def test_system_default_points_to_existing_user_state(self) -> None:
        profile = Profile.system_default()

        self.assertTrue(profile.is_system_default)
        self.assertEqual(profile.id, "__system_default__")
        self.assertEqual(profile.codex_home.name, ".codex")

    def test_profiles_use_distinct_directories(self) -> None:
        root = Path("C:/profiles")
        first = Profile.create(name="Work", kind=ProfileKind.ACCOUNT, profiles_root=root)
        second = Profile.create(name="Personal", kind=ProfileKind.ACCOUNT, profiles_root=root)

        self.assertNotEqual(first.codex_home, second.codex_home)
        self.assertNotEqual(first.user_data_dir, second.user_data_dir)
        self.assertEqual(first.codex_home.parent, first.user_data_dir.parent)

    def test_provider_requires_base_url(self) -> None:
        profile = Profile.create(
            name="Provider", kind=ProfileKind.PROVIDER, profiles_root=Path("C:/profiles")
        )
        with self.assertRaisesRegex(ValueError, "Base URL"):
            profile.validate()


class ProviderConfigContracts(unittest.TestCase):
    def test_provider_config_contains_no_api_key(self) -> None:
        profile = Profile.create(
            name="Provider",
            kind=ProfileKind.PROVIDER,
            profiles_root=Path("C:/profiles"),
            base_url="https://example.test/v1",
            model="gpt-test",
        )
        rendered = render_provider_config(profile)

        self.assertIn('openai_base_url = "https://example.test/v1"', rendered)
        self.assertIn('model = "gpt-test"', rendered)
        self.assertNotIn("api_key", rendered.lower())

    def test_existing_config_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = Profile.create(
                name="Provider",
                kind=ProfileKind.PROVIDER,
                profiles_root=Path(temporary),
                base_url="https://example.test/v1",
            )
            profile.codex_home.mkdir(parents=True)
            config = profile.codex_home / "config.toml"
            config.write_text("existing = true\n", encoding="utf-8")

            created = initialize_provider_config(profile)

            self.assertFalse(created)
            self.assertEqual(config.read_text(encoding="utf-8"), "existing = true\n")

    def test_sync_preserves_unowned_config_and_creates_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = Profile.create(
                name="Provider",
                kind=ProfileKind.PROVIDER,
                profiles_root=Path(temporary),
                base_url="https://new.example/v1",
                model="gpt-new",
            )
            profile.codex_home.mkdir(parents=True)
            config = profile.codex_home / "config.toml"
            config.write_text(
                'model = "old"\nopenai_base_url = "https://old.example/v1"\napproval_policy = "on-request"\n',
                encoding="utf-8",
            )

            sync_provider_config(profile)

            updated = config.read_text(encoding="utf-8")
            self.assertIn('model = "gpt-new"', updated)
            self.assertIn('openai_base_url = "https://new.example/v1"', updated)
            self.assertIn('approval_policy = "on-request"', updated)
            self.assertTrue((profile.codex_home / "config.toml.bak").exists())


class RepositoryContracts(unittest.TestCase):
    def test_crud_preserves_profile_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "launcher.db"
            repository = ProfileRepository(database)
            repository.initialize()
            profile = Profile.create(
                name="Work", kind=ProfileKind.ACCOUNT, profiles_root=Path(temporary) / "profiles"
            )

            repository.save(profile)
            loaded = repository.get(profile.id)
            repository.remove_record(profile.id)

            self.assertEqual(loaded, profile)
            self.assertIsNone(repository.get(profile.id))


class LauncherContracts(unittest.TestCase):
    def test_default_launch_has_no_isolation_overrides(self) -> None:
        locator = Mock()
        locator.locate.return_value = Path("C:/Program Files/WindowsApps/OpenAI.Codex/app/ChatGPT.exe")
        guard = Mock()
        launcher = CodexLauncher(locator, guard)
        process = Mock()
        process.pid = 7
        process.poll.return_value = None
        profile = Profile.system_default()

        with patch.dict("launcher.codex_app.os.environ", {"CODEX_HOME": "C:/isolated"}, clear=False):
            with patch.object(launcher, "_profile_process_ids", return_value=[]):
                with patch("launcher.codex_app.subprocess.Popen", return_value=process) as popen:
                    launcher.launch(profile)

        command = popen.call_args.args[0]
        environment = popen.call_args.kwargs["env"]
        self.assertEqual(len(command), 1)
        self.assertNotIn("CODEX_HOME", environment)
        guard.prepare.assert_called_once_with(profile)

    def test_launch_sets_both_isolation_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "ChatGPT.exe"
            executable.touch()
            locator = Mock()
            locator.locate.return_value = executable
            launcher = CodexLauncher(locator)
            profile = Profile.create(
                name="Work", kind=ProfileKind.ACCOUNT, profiles_root=root / "profiles"
            )
            process = Mock()
            process.pid = 42
            process.poll.return_value = None

            with patch.object(launcher, "_profile_process_ids", return_value=[]):
                with patch("launcher.codex_app.subprocess.Popen", return_value=process) as popen:
                    running = launcher.launch(profile)

            command = popen.call_args.args[0]
            environment = popen.call_args.kwargs["env"]
            self.assertEqual(running.process.pid, 42)
            self.assertIn(f"--user-data-dir={profile.user_data_dir}", command)
            self.assertEqual(environment["CODEX_HOME"], str(profile.codex_home))

    def test_running_profile_scan_distinguishes_default_and_isolated_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = Profile.create(
                name="Work",
                kind=ProfileKind.ACCOUNT,
                profiles_root=Path(temporary) / "profiles",
            )
            rows = [
                {
                    "ProcessId": 41,
                    "CommandLine": f'ChatGPT.exe --user-data-dir="{profile.user_data_dir}"',
                },
                {"ProcessId": 42, "CommandLine": "ChatGPT.exe"},
                {
                    "ProcessId": 43,
                    "CommandLine": "ChatGPT.exe --user-data-dir=C:/another-profile",
                },
            ]
            launcher = CodexLauncher(Mock(), Mock())

            with patch.object(launcher, "_root_process_rows", return_value=rows):
                running = launcher.running_profile_ids([Profile.system_default(), profile])

            self.assertEqual(running, {Profile.system_default().id, profile.id})

    def test_stop_profile_forces_only_residual_profile_process_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = Profile.create(
                name="Work",
                kind=ProfileKind.ACCOUNT,
                profiles_root=Path(temporary) / "profiles",
            )
            guard = Mock()
            launcher = CodexLauncher(Mock(), guard)
            tracked_process = Mock()
            launcher._running[profile.id] = RunningProfile(profile.id, tracked_process)

            with patch.object(launcher, "_profile_process_ids", return_value=[4242]), patch.object(
                launcher, "_request_close_processes"
            ) as request_close, patch.object(
                launcher, "_wait_for_profile_exit", side_effect=[False, True]
            ), patch.object(launcher, "_terminate_process_trees") as terminate:
                stopped = launcher.stop_profile(profile)

            self.assertTrue(stopped)
            guard.snapshot_if_valid.assert_called_once_with(profile)
            request_close.assert_called_once_with([4242])
            terminate.assert_called_once_with([4242])
            self.assertNotIn(profile.id, launcher._running)

    def test_stop_profile_avoids_force_when_normal_close_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = Profile.create(
                name="Work",
                kind=ProfileKind.ACCOUNT,
                profiles_root=Path(temporary) / "profiles",
            )
            launcher = CodexLauncher(Mock(), Mock())

            with patch.object(launcher, "_profile_process_ids", return_value=[5151]), patch.object(
                launcher, "_request_close_processes"
            ), patch.object(launcher, "_wait_for_profile_exit", return_value=True), patch.object(
                launcher, "_terminate_process_trees"
            ) as terminate:
                stopped = launcher.stop_profile(profile)

            self.assertTrue(stopped)
            terminate.assert_not_called()

    def test_restart_profile_stops_before_launching_again(self) -> None:
        profile = Profile.system_default()
        launcher = CodexLauncher(Mock(), Mock())
        process = Mock()
        running = RunningProfile(profile.id, process)

        with patch.object(launcher, "stop_profile", return_value=True) as stop, patch.object(
            launcher, "launch", return_value=running
        ) as launch:
            result = launcher.restart_profile(profile)

        self.assertIs(result, running)
        stop.assert_called_once_with(profile)
        launch.assert_called_once_with(profile)


class ServiceContracts(unittest.TestCase):
    def test_profile_list_starts_with_unpersisted_system_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = AppPaths(root, root / "profiles", root / "launcher.db", root / "logs")
            repository = ProfileRepository(paths.database)
            service = ProfileService(paths, repository, Mock())
            service.initialize()

            profiles = service.list_profiles()

            self.assertTrue(profiles[0].is_system_default)
            self.assertEqual(repository.list(), [])

    def test_removing_record_keeps_profile_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = AppPaths(root, root / "profiles", root / "launcher.db", root / "logs")
            repository = ProfileRepository(paths.database)
            launcher = Mock()
            launcher.is_running.return_value = False
            launcher.is_profile_process_running.return_value = False
            service = ProfileService(paths, repository, launcher)
            service.initialize()
            profile = service.create_profile(name="Work", kind=ProfileKind.ACCOUNT)
            marker = profile.codex_home / "keep.txt"
            marker.write_text("keep", encoding="utf-8")

            service.remove_profile_record(profile)

            self.assertTrue(marker.exists())
            self.assertIsNone(repository.get(profile.id))

    def test_default_apps_settings_uses_windows_settings_uri(self) -> None:
        with patch("os.startfile") as startfile:
            ProfileService.open_default_apps_settings()

        startfile.assert_called_once_with("ms-settings:defaultapps")


if __name__ == "__main__":
    unittest.main()
