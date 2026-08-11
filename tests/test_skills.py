from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

from launcher.models import Profile, ProfileKind
from launcher.paths import AppPaths
from launcher.skill_catalog import SkillCatalog, hash_directory, is_junction
from launcher.skill_models import SkillState
from launcher.skill_repository import SkillRepository
from launcher.skill_service import SkillConflictError, SkillService


def make_profile(root: Path, profile_id: str, name: str) -> Profile:
    profile_root = root / "profiles" / profile_id
    return Profile(
        id=profile_id,
        name=name,
        kind=ProfileKind.ACCOUNT,
        codex_home=profile_root / "codex-home",
        user_data_dir=profile_root / "user-data",
    )


def write_skill(skills_dir: Path, name: str, body: str) -> Path:
    path = skills_dir / name
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return path


class SkillCatalogContracts(unittest.TestCase):
    def test_scan_excludes_system_and_detects_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = make_profile(root, "first", "First")
            second = make_profile(root, "second", "Second")
            write_skill(first.codex_home / "skills", "same", "one")
            write_skill(second.codex_home / "skills", "same", "one")
            write_skill(first.codex_home / "skills", "different", "old")
            write_skill(second.codex_home / "skills", "different", "new")
            write_skill(first.codex_home / "skills", ".system", "internal")

            preview = SkillCatalog(root / "shared-skills").build_preview([first, second])
            plans = {plan.name: plan for plan in preview.plans}

            self.assertEqual(plans["same"].state, SkillState.IDENTICAL)
            self.assertEqual(plans["different"].state, SkillState.CONFLICT)
            self.assertNotIn(".system", plans)

    def test_scan_marks_directory_without_skill_manifest_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = make_profile(root, "first", "First")
            invalid = profile.codex_home / "skills" / "broken"
            invalid.mkdir(parents=True)
            (invalid / "notes.txt").write_text("missing manifest", encoding="utf-8")

            preview = SkillCatalog(root / "shared-skills").build_preview([profile])

            self.assertEqual(preview.plans[0].state, SkillState.INVALID)

    def test_sensitive_file_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = make_profile(root, "first", "First")
            skill = write_skill(profile.codex_home / "skills", "secret", "test")
            (skill / ".env").write_text("API_KEY=abcdefghijklmnop", encoding="utf-8")

            preview = SkillCatalog(root / "shared-skills").build_preview([profile])

            self.assertTrue(preview.plans[0].sources[0].sensitive_findings)


class SkillRepositoryContracts(unittest.TestCase):
    def test_schema_and_default_policy_are_backward_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "launcher.db"
            repository = SkillRepository(database)
            repository.initialize()

            self.assertTrue(repository.policy_enabled("new-profile"))
            repository.set_policy("new-profile", False)
            self.assertFalse(repository.policy_enabled("new-profile"))
            self.assertEqual(repository.snapshot_count(), 0)


@unittest.skipUnless(__import__("os").name == "nt", "目录联接测试仅适用于 Windows")
class SkillMigrationContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.paths = AppPaths(root, root / "profiles", root / "launcher.db", root / "logs")
        self.paths.ensure()
        self.repository = SkillRepository(self.paths.database)
        self.launcher = Mock()
        self.launcher.is_profile_process_running.return_value = False
        self.service = SkillService(self.paths, self.repository, self.launcher)
        self.service.initialize()
        self.first = make_profile(root, "first", "First")
        self.second = make_profile(root, "second", "Second")
        for profile in (self.first, self.second):
            (profile.codex_home / "skills" / ".system").mkdir(parents=True)

    def tearDown(self) -> None:
        for profile in (self.first, self.second):
            try:
                self.service.detach_profile(profile)
            except Exception:
                pass
        self.temporary.cleanup()

    def test_migration_builds_central_copy_and_per_skill_junctions(self) -> None:
        write_skill(self.first.codex_home / "skills", "alpha", "same")
        write_skill(self.second.codex_home / "skills", "alpha", "same")
        write_skill(self.first.codex_home / "skills", "only-first", "one")
        preview = self.service.preview([self.first, self.second])

        self.service.apply_initial_migration(preview, [self.first, self.second], {})

        shared = self.paths.shared_skills / "alpha"
        self.assertTrue(shared.is_dir())
        self.assertTrue(is_junction(self.first.codex_home / "skills" / "alpha"))
        self.assertTrue(is_junction(self.second.codex_home / "skills" / "alpha"))
        self.assertTrue((self.first.codex_home / "skills" / ".system").is_dir())
        self.assertTrue((self.second.codex_home / "skills" / ".system").is_dir())
        self.assertGreaterEqual(self.repository.snapshot_count(), 2)

    def test_conflict_requires_explicit_source_selection(self) -> None:
        first = write_skill(self.first.codex_home / "skills", "conflict", "old")
        second = write_skill(self.second.codex_home / "skills", "conflict", "new")
        first_digest = hash_directory(first)
        selected_digest = hash_directory(second)
        preview = self.service.preview([self.first, self.second])

        with self.assertRaises(SkillConflictError):
            self.service.apply_initial_migration(preview, [self.first, self.second], {})

        self.service.apply_initial_migration(
            preview,
            [self.first, self.second],
            {"conflict": self.second.id},
        )
        self.assertEqual(
            hash_directory(self.paths.shared_skills / "conflict"),
            selected_digest,
        )
        self.assertNotEqual(first_digest, selected_digest)

    def test_detach_keeps_an_independent_copy(self) -> None:
        write_skill(self.first.codex_home / "skills", "alpha", "same")
        preview = self.service.preview([self.first, self.second])
        self.service.apply_initial_migration(preview, [self.first, self.second], {})

        self.service.detach_profile(self.first)

        detached = self.first.codex_home / "skills" / "alpha"
        self.assertTrue(detached.is_dir())
        self.assertFalse(is_junction(detached))
        self.assertEqual(
            hash_directory(detached),
            hash_directory(self.paths.shared_skills / "alpha"),
        )

    def test_external_change_creates_snapshot(self) -> None:
        write_skill(self.first.codex_home / "skills", "alpha", "same")
        preview = self.service.preview([self.first])
        self.service.apply_initial_migration(preview, [self.first], {})
        before = self.repository.snapshot_count()
        (self.paths.shared_skills / "alpha" / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: changed\n---\n",
            encoding="utf-8",
        )

        self.service.preview([self.first])

        self.assertEqual(self.repository.snapshot_count(), before + 1)

    def test_missing_shared_skill_is_restored_from_latest_snapshot(self) -> None:
        write_skill(self.first.codex_home / "skills", "alpha", "same")
        preview = self.service.preview([self.first])
        self.service.apply_initial_migration(preview, [self.first], {})
        shared = self.paths.shared_skills / "alpha"
        displaced = self.paths.root / "simulated-external-removal" / "alpha"
        displaced.parent.mkdir(parents=True)
        __import__("os").replace(shared, displaced)

        self.service.preview([self.first])

        self.assertTrue(shared.is_dir())

    def test_link_failure_rolls_every_original_directory_back(self) -> None:
        first = write_skill(self.first.codex_home / "skills", "alpha", "first")
        second = write_skill(self.second.codex_home / "skills", "alpha", "first")
        original_digest = hash_directory(first)
        preview = self.service.preview([self.first, self.second])
        from launcher import skill_service as skill_service_module

        real_create = skill_service_module.create_junction
        calls = 0

        def fail_second(target: Path, source: Path) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated junction failure")
            real_create(target, source)

        with patch("launcher.skill_service.create_junction", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "simulated"):
                self.service.apply_initial_migration(preview, [self.first, self.second], {})

        self.assertFalse(is_junction(first))
        self.assertFalse(is_junction(second))
        self.assertEqual(hash_directory(first), original_digest)
        self.assertEqual(hash_directory(second), original_digest)
        self.assertFalse((self.paths.shared_skills / "alpha").exists())

    def test_global_remove_preserves_snapshot_and_moves_all_entries_to_backup(self) -> None:
        write_skill(self.first.codex_home / "skills", "alpha", "same")
        preview = self.service.preview([self.first, self.second])
        self.service.apply_initial_migration(preview, [self.first, self.second], {})
        before = self.repository.snapshot_count()

        operation_id = self.service.remove_shared_skill("alpha", [self.first, self.second])

        self.assertFalse((self.paths.shared_skills / "alpha").exists())
        self.assertFalse((self.first.codex_home / "skills" / "alpha").exists())
        self.assertFalse((self.second.codex_home / "skills" / "alpha").exists())
        self.assertGreater(self.repository.snapshot_count(), before)
        self.assertTrue((self.paths.skill_backups / operation_id / "shared-library" / "alpha").is_dir())


if __name__ == "__main__":
    unittest.main()
