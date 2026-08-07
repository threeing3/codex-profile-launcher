from __future__ import annotations

import ctypes
import tkinter as tk

from .codex_app import CodexLauncher
from .paths import AppPaths
from .repository import ProfileRepository
from .service import ProfileService
from .skill_repository import SkillRepository
from .skill_service import SkillService
from .ui import LauncherWindow


def run() -> None:
    _enable_windows_dpi_awareness()
    paths = AppPaths.default()
    launcher = CodexLauncher()
    skill_service = SkillService(paths, SkillRepository(paths.database), launcher)
    service = ProfileService(
        paths,
        ProfileRepository(paths.database),
        launcher,
        skill_service,
    )
    service.initialize()

    root = tk.Tk()
    LauncherWindow(root, service)
    root.mainloop()


def _enable_windows_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
