from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from pathlib import Path

from .codex_app import CodexLauncher
from .paths import AppPaths
from .repository import ProfileRepository
from .service import ProfileService
from .skill_repository import SkillRepository
from .skill_service import SkillService
from .ui import LauncherWindow


APP_USER_MODEL_ID = "threeing3.CodexProfiles"


def run() -> None:
    _enable_windows_dpi_awareness()
    _set_windows_app_identity()
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
    _set_window_icon(root)
    LauncherWindow(root, service)
    root.mainloop()


def _enable_windows_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def _set_windows_app_identity() -> None:
    """Give Windows a stable taskbar identity for grouping and icon selection."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass


def _set_window_icon(root: tk.Tk) -> None:
    icon_path = _resource_path("assets", "codex-profiles.ico")
    if not icon_path.is_file():
        return
    try:
        root.iconbitmap(default=str(icon_path))
    except (OSError, tk.TclError):
        pass


def _resource_path(*parts: str) -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root).joinpath(*parts)
    return Path(__file__).resolve().parent.parent.joinpath(*parts)
