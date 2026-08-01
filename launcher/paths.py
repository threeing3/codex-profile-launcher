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
