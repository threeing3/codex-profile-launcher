from __future__ import annotations

import ctypes
import tkinter as tk

from .codex_app import CodexLauncher
from .paths import AppPaths
from .repository import ProfileRepository
from .service import ProfileService
from .ui import LauncherWindow


def run() -> None:
    _enable_windows_dpi_awareness()
    paths = AppPaths.default()
    service = ProfileService(paths, ProfileRepository(paths.database), CodexLauncher())
    service.initialize()

    root = tk.Tk()
    LauncherWindow(root, service)
    root.mainloop()


def _enable_windows_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
