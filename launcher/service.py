from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .codex_app import CodexLauncher
from .models import Profile, ProfileKind
from .paths import AppPaths
from .provider_config import initialize_provider_config, sync_provider_config
from .repository import ProfileRepository


class ProfileService:
    def __init__(
        self,
        paths: AppPaths,
        repository: ProfileRepository,
        launcher: CodexLauncher,
    ) -> None:
        self.paths = paths
        self.repository = repository
        self.launcher = launcher

    def initialize(self) -> None:
        self.paths.ensure()
        self.repository.initialize()

    def list_profiles(self) -> list[Profile]:
        return [Profile.system_default(), *self.repository.list()]

    def create_profile(
        self,
        *,
        name: str,
        kind: ProfileKind,
        provider_name: str = "",
        base_url: str = "",
        model: str = "",
        color: str = "#4F7467",
    ) -> Profile:
        profile = Profile.create(
            name=name,
            kind=kind,
            profiles_root=self.paths.profiles,
            provider_name=provider_name,
            base_url=base_url,
            model=model,
            color=color,
        )
        profile.validate()
        profile.codex_home.mkdir(parents=True, exist_ok=True)
        profile.user_data_dir.mkdir(parents=True, exist_ok=True)
        initialize_provider_config(profile)
        self.repository.save(profile)
        return profile

    def update_profile(
        self,
        profile: Profile,
        *,
        name: str,
        provider_name: str,
        base_url: str,
        model: str,
        color: str,
    ) -> Profile:
        if profile.is_system_default:
            raise ValueError("系统默认 Codex 不需要编辑。")
        updated = replace(
            profile,
            name=name.strip(),
            provider_name=provider_name.strip(),
            base_url=base_url.strip(),
            model=model.strip(),
            color=color,
        )
        updated.validate()
        sync_provider_config(updated)
        self.repository.save(updated)
        return updated

    def launch_profile(self, profile: Profile) -> int:
        return self.launcher.launch(profile).process.pid

    def remove_profile_record(self, profile: Profile) -> None:
        if profile.is_system_default:
            raise RuntimeError("系统默认 Codex 不能从启动器中移除。")
        if self.launcher.is_running(profile.id):
            raise RuntimeError("Close the Codex window before removing this Profile.")
        self.repository.remove_record(profile.id)

    @staticmethod
    def open_directory(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        import os

        os.startfile(path)  # type: ignore[attr-defined]

    @staticmethod
    def open_default_apps_settings() -> None:
        import os

        os.startfile("ms-settings:defaultapps")  # type: ignore[attr-defined]
