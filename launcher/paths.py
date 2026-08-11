from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppPaths:
    root: Path
    profiles: Path
    database: Path
    logs: Path

    @property
    def shared_skills(self) -> Path:
        return self.root / "shared-skills"

    @property
    def skill_backups(self) -> Path:
        return self.root / "backups" / "skills"

    @property
    def skill_snapshots(self) -> Path:
        return self.root / "snapshots" / "skills"

    @property
    def skill_staging(self) -> Path:
        return self.root / "staging" / "skills"

    @property
    def skill_logs(self) -> Path:
        return self.logs / "skills"

    @classmethod
    def default(cls) -> "AppPaths":
        local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        root = local_app_data / "CodexProfileLauncher"
        return cls(
            root=root,
            profiles=root / "profiles",
            database=root / "launcher.db",
            logs=root / "logs",
        )

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.profiles.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)
        self.shared_skills.mkdir(parents=True, exist_ok=True)
        self.skill_backups.mkdir(parents=True, exist_ok=True)
        self.skill_snapshots.mkdir(parents=True, exist_ok=True)
        self.skill_staging.mkdir(parents=True, exist_ok=True)
        self.skill_logs.mkdir(parents=True, exist_ok=True)
