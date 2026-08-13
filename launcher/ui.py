from __future__ import annotations

import ctypes
import threading
import tkinter as tk
import os
from tkinter import messagebox, ttk
from typing import Callable

from .codex_app import CodexAppNotFound
from .models import Profile, ProfileKind
from .service import ProfileService
from .skill_ui import SkillManagerDialog


FONT_FAMILY = "Microsoft YaHei UI"
DEFAULT_WINDOW_WIDTH = 1180
DEFAULT_WINDOW_HEIGHT = 900
DEFAULT_SIDEBAR_WIDTH = 316


COLORS = {
    "window": "#F2F2F7",
    "sidebar": "#F2F2F7",
    "sidebar_text": "#1D1D1F",
    "sidebar_muted": "#86868B",
    "panel": "#F2F2F7",
    "surface": "#FFFFFF",
    "line": "#D1D1D6",
    "text": "#1D1D1F",
    "muted": "#6E6E73",
    "accent": "#007AFF",
    "accent_hover": "#006EE6",
    "accent_soft": "#E6F1FF",
    "danger": "#D70015",
    "success": "#248A3D",
    "idle": "#86868B",
    "focus": "#0071E3",
    "selected": "#DDEBFF",
    "hover": "#E5E5EA",
    "launch_surface": "#F7FBFF",
    "success_soft": "#EAF6EC",
}

PROFILE_COLORS = {
    "海湾蓝": "#3B82F6",
    "松针绿": "#3D8B6D",
    "珊瑚红": "#D56A5A",
    "石墨灰": "#687078",
    "琥珀金": "#B18432",
}


class LauncherWindow:
    def __init__(self, root: tk.Tk, service: ProfileService) -> None:
        self.root = root
        self.service = service
        self.profiles: list[Profile] = []
        self.selected_profile: Profile | None = None
        self.search_var = tk.StringVar()
        self.app_status_var = tk.StringVar(value="正在检测 Codex…")
        self.profile_status_var = tk.StringVar(value="未启动")
        self._running_profile_ids: frozenset[str] = frozenset()
        self._process_poll_inflight = False
        self._profile_action_inflight: str | None = None
        self._toast: tk.Label | None = None
        self._content_scrollbar_sync_job: str | None = None
        self.launch_button: tk.Button | None = None
        self.close_process_button: ttk.Button | None = None
        self.restart_button: ttk.Button | None = None
        self._launch_button_text = ""
        self._detail_value_labels: list[tk.Label] = []
        self._compact_layout = False

        self._configure_root()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._configure_styles()
        self._build_layout()
        self.root.after_idle(self._style_native_window_frame)
        self.root.after(400, self._sync_layout_mode)
        self._reload_profiles()
        self._detect_codex()
        self._poll_processes()
        self.root.bind("<Control-n>", lambda _event: self._new_profile())
        self.root.bind("<Control-r>", lambda _event: self._detect_codex())
        self.root.bind("<Control-f>", lambda _event: self._focus_search())

    def _on_close(self) -> None:
        """Snapshot valid project state before the launcher itself exits."""

        for profile in self.profiles:
            try:
                self.service.launcher.snapshot_profile_state(profile)
            except OSError:
                # Closing the launcher must remain possible even if a profile
                # state file is temporarily locked by the Codex app.
                continue
        self.root.destroy()

    def _configure_root(self) -> None:
        title = os.environ.get("CODEX_PROFILE_LAUNCHER_TITLE", "Codex Profiles")
        self.root.title(title)
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        window_width = max(640, min(DEFAULT_WINDOW_WIDTH, screen_width - 80))
        window_height = max(520, min(DEFAULT_WINDOW_HEIGHT, screen_height - 96))
        window_x = max(0, (screen_width - window_width) // 2)
        window_y = max(0, (screen_height - window_height) // 2)
        self.root.geometry(f"{window_width}x{window_height}+{window_x}+{window_y}")
        # Keep enough room for the stacked narrow layout on high-DPI Windows displays.
        self.root.minsize(640, 520)
        self.root.configure(bg=COLORS["window"])

    def _style_native_window_frame(self) -> None:
        """Align the Windows caption colors with the in-app Apple-inspired palette."""
        try:
            dwmapi = ctypes.windll.dwmapi
            hwnd = ctypes.windll.user32.GetAncestor(self.root.winfo_id(), 2)  # GA_ROOT
            if not hwnd:
                return
            attributes = (
                (34, 0x00D6D1D1),  # DWMWA_BORDER_COLOR
                (35, 0x00F7F2F2),  # DWMWA_CAPTION_COLOR
                (36, 0x001F1F1D),  # DWMWA_TEXT_COLOR
            )
            for attribute, color in attributes:
                value = ctypes.c_uint(color)
                dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value))
        except (AttributeError, OSError):
            # Older Windows versions may not expose DWM caption-color attributes.
            return

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=COLORS["panel"])
        style.configure("Sidebar.TFrame", background=COLORS["sidebar"])
        style.configure("Panel.TFrame", background=COLORS["panel"])
        style.configure(
            "TLabel",
            background=COLORS["panel"],
            foreground=COLORS["text"],
            font=(FONT_FAMILY, 10),
        )
        style.configure(
            "Muted.TLabel",
            background=COLORS["panel"],
            foreground=COLORS["muted"],
            font=(FONT_FAMILY, 9),
        )
        style.configure(
            "Sidebar.TLabel",
            background=COLORS["sidebar"],
            foreground=COLORS["sidebar_text"],
            font=(FONT_FAMILY, 10),
        )
        style.configure(
            "Title.TLabel",
            background=COLORS["panel"],
            foreground=COLORS["text"],
            font=(FONT_FAMILY, 20, "bold"),
        )
        style.configure(
            "Eyebrow.TLabel",
            background=COLORS["panel"],
            foreground=COLORS["muted"],
            font=(FONT_FAMILY, 9),
        )
        style.configure(
            "Primary.TButton",
            background=COLORS["accent"],
            foreground="#FFFFFF",
            borderwidth=0,
            padding=(18, 11),
            font=(FONT_FAMILY, 10, "bold"),
        )
        style.map("Primary.TButton", background=[("active", COLORS["accent_hover"])])
        style.configure(
            "Secondary.TButton",
            background=COLORS["surface"],
            foreground=COLORS["text"],
            bordercolor=COLORS["line"],
            borderwidth=1,
            padding=(14, 10),
            font=(FONT_FAMILY, 9),
        )
        style.map(
            "Secondary.TButton",
            background=[("active", "#E5E5EA"), ("focus", COLORS["accent_soft"])],
            bordercolor=[("focus", COLORS["focus"])],
        )
        style.configure(
            "SidebarAction.TButton",
            background=COLORS["surface"],
            foreground=COLORS["text"],
            bordercolor=COLORS["line"],
            borderwidth=1,
            padding=(8, 6),
            font=(FONT_FAMILY, 8),
        )
        style.map("SidebarAction.TButton", background=[("active", COLORS["hover"])])
        style.configure(
            "Danger.TButton",
            background=COLORS["surface"],
            foreground=COLORS["danger"],
            bordercolor="#F0C7CB",
            borderwidth=1,
            padding=(13, 9),
            font=(FONT_FAMILY, 9),
        )
        style.map("Danger.TButton", background=[("active", "#FFF0F0")])
        style.configure(
            "Profile.Treeview",
            background=COLORS["sidebar"],
            fieldbackground=COLORS["sidebar"],
            foreground=COLORS["sidebar_text"],
            borderwidth=0,
            relief="flat",
            rowheight=44,
            font=(FONT_FAMILY, 10),
        )
        style.map(
            "Profile.Treeview",
            background=[("selected", COLORS["selected"])],
            foreground=[("selected", COLORS["text"])],
        )
        style.configure(
            "TEntry",
            fieldbackground=COLORS["surface"],
            bordercolor=COLORS["line"],
            lightcolor=COLORS["line"],
            darkcolor=COLORS["line"],
            relief="flat",
            borderwidth=0,
            padding=9,
        )
        style.map("TEntry", bordercolor=[("focus", COLORS["accent"])])
        style.configure(
            "TCombobox",
            fieldbackground=COLORS["surface"],
            bordercolor=COLORS["line"],
            padding=9,
        )
        style.configure("TRadiobutton", background=COLORS["panel"], font=(FONT_FAMILY, 9))
        style.map("TRadiobutton", background=[("active", COLORS["panel"])])
        style.configure(
            "Overline.TLabel",
            background=COLORS["panel"],
            foreground=COLORS["muted"],
            font=(FONT_FAMILY, 9, "bold"),
        )
        style.configure(
            "Toolbar.TLabel",
            background=COLORS["panel"],
            foreground=COLORS["text"],
            font=(FONT_FAMILY, 17, "bold"),
        )

    def _build_layout(self) -> None:
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        sidebar = ttk.Frame(self.root, style="Sidebar.TFrame", width=DEFAULT_SIDEBAR_WIDTH)
        self.sidebar = sidebar
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(3, weight=1)

        brand = ttk.Frame(sidebar, style="Sidebar.TFrame")
        self.brand = brand
        brand.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 16))
        brand.grid_columnconfigure(0, weight=1)
        ttk.Label(
            brand,
            text="Codex Profiles",
            style="Sidebar.TLabel",
            font=(FONT_FAMILY, 15, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            brand,
            text="选择一个账户以继续",
            style="Sidebar.TLabel",
            foreground=COLORS["sidebar_muted"],
            font=(FONT_FAMILY, 9),
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

        search_frame = tk.Frame(sidebar, bg=COLORS["sidebar"])
        self.search_frame = search_frame
        search_frame.grid(row=1, column=0, sticky="ew", padx=16)
        search_frame.grid_columnconfigure(0, weight=1)
        tk.Label(
            search_frame,
            text="账户",
            bg=COLORS["sidebar"],
            fg=COLORS["sidebar_muted"],
            font=(FONT_FAMILY, 9, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 7))
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        self.search_entry.grid(row=1, column=0, sticky="ew")
        self.search_var.trace_add("write", lambda *_: self._render_profile_list())

        self.saved_accounts_label = ttk.Label(
            sidebar,
            text="已保存的账户",
            style="Sidebar.TLabel",
            foreground=COLORS["sidebar_muted"],
        )
        self.saved_accounts_label.grid(
            row=2, column=0, sticky="w", padx=18, pady=(18, 8)
        )

        self.profile_tree = ttk.Treeview(
            sidebar,
            show="tree",
            selectmode="browse",
            style="Profile.Treeview",
        )
        self.profile_tree.grid(row=3, column=0, sticky="nsew", padx=12)
        self.profile_tree.bind("<<TreeviewSelect>>", self._on_profile_selected)
        self.profile_tree.bind("<Double-1>", lambda _event: self._launch_selected())
        self.profile_tree.bind("<Return>", lambda _event: self._launch_selected())
        self.profile_tree.bind("<Motion>", self._on_profile_motion)
        self.profile_tree.bind("<Leave>", self._on_profile_leave)
        self.profile_tree.tag_configure("hover", background=COLORS["hover"], foreground=COLORS["text"])

        sidebar_actions = ttk.Frame(sidebar, style="Sidebar.TFrame")
        self.sidebar_actions = sidebar_actions
        sidebar_actions.grid(row=4, column=0, sticky="ew", padx=16, pady=(12, 0))
        sidebar_actions.grid_columnconfigure(0, weight=1)
        sidebar_actions.grid_columnconfigure(1, weight=1)
        ttk.Button(
            sidebar_actions,
            text="＋ 新建账户",
            style="SidebarAction.TButton",
            command=self._new_profile,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ttk.Button(
            sidebar_actions,
            text="共享技能库",
            style="SidebarAction.TButton",
            command=self._open_skill_manager,
        ).grid(row=0, column=1, sticky="ew", padx=(5, 0))

        self.sidebar_hint = ttk.Label(
            sidebar,
            text="双击或 Enter 启动  ·  Ctrl F 搜索",
            style="Sidebar.TLabel",
            foreground=COLORS["sidebar_muted"],
            font=(FONT_FAMILY, 8),
        )
        self.sidebar_hint.grid(row=5, column=0, sticky="w", padx=18, pady=(10, 14))

        main = ttk.Frame(self.root, style="Panel.TFrame")
        self.main = main
        main.grid(row=0, column=1, sticky="nsew", padx=(1, 0))
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        header = ttk.Frame(main, style="Panel.TFrame")
        self.header = header
        header.grid(row=0, column=0, sticky="ew", padx=36, pady=(26, 0))
        header.grid_columnconfigure(0, weight=1)
        ttk.Label(header, text="账户", style="Toolbar.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(header, textvariable=self.app_status_var, style="Muted.TLabel").grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )
        self.detect_button = ttk.Button(header, text="重新检测", style="Secondary.TButton", command=self._detect_codex)
        self.detect_button.grid(row=0, column=1, rowspan=2)
        self.browser_button = ttk.Button(
            header,
            text="默认浏览器",
            style="Secondary.TButton",
            command=self._open_default_apps_settings,
        )
        self.browser_button.grid(row=0, column=2, rowspan=2, padx=(10, 0))

        content_view = tk.Frame(main, bg=COLORS["panel"], highlightthickness=0, bd=0)
        content_view.grid(row=1, column=0, sticky="nsew")
        content_view.grid_rowconfigure(0, weight=1)
        content_view.grid_columnconfigure(0, weight=1)
        self.content_canvas = tk.Canvas(content_view, bg=COLORS["panel"], highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(content_view, orient="vertical", command=self.content_canvas.yview)
        self.content_scrollbar = scrollbar
        self._content_scrollbar_visible = False
        self.content_canvas.configure(yscrollcommand=scrollbar.set)
        self.content_canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        scrollbar.grid_remove()
        self.content = ttk.Frame(self.content_canvas, style="Panel.TFrame", padding=(36, 24, 36, 28))
        content_window = self.content_canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content_canvas.bind(
            "<Configure>",
            lambda event: self.content_canvas.itemconfigure(content_window, width=max(1, event.width)),
        )
        self.content.bind(
            "<Configure>",
            lambda _event: self._update_content_scrollbar(),
        )
        self.content_canvas.bind("<Enter>", lambda _event: self.root.bind_all("<MouseWheel>", self._on_content_wheel))
        self.content_canvas.bind("<Leave>", lambda _event: self.root.unbind_all("<MouseWheel>"))
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(7, weight=1)
        self._show_empty_state()
        self.root.bind("<Configure>", self._on_window_resize, add="+")

    def _update_content_scrollbar(self) -> None:
        bounds = self.content_canvas.bbox("all")
        if bounds:
            self.content_canvas.configure(scrollregion=bounds)
        if self._content_scrollbar_sync_job is not None:
            self.root.after_cancel(self._content_scrollbar_sync_job)
        self._content_scrollbar_sync_job = self.root.after(80, self._sync_content_scrollbar_visibility)

    def _sync_content_scrollbar_visibility(self) -> None:
        self._content_scrollbar_sync_job = None
        if not self.content_canvas.winfo_exists():
            return
        first, last = self.content_canvas.yview()
        needs_scrollbar = first > 0.001 or last < 0.999
        if needs_scrollbar and not self._content_scrollbar_visible:
            self.content_scrollbar.grid()
            self._content_scrollbar_visible = True
        elif not needs_scrollbar and self._content_scrollbar_visible:
            self.content_scrollbar.grid_remove()
            self._content_scrollbar_visible = False

    def _on_window_resize(self, event: tk.Event) -> None:
        if event.widget is not self.root:
            return
        width = max(1, event.width)
        height = max(1, event.height)
        main_width = self.main.winfo_width()
        physical_width = self._window_pixel_width(width)
        geometry_width = self._geometry_width()
        compact = geometry_width < 1000 or physical_width < 900 or (main_width > 1 and main_width < 520)
        if compact != self._compact_layout:
            self._set_layout_mode(compact)
        if compact:
            sidebar_width, horizontal_pad = max(1, width), 18
            self.sidebar.configure(height=max(260, min(330, int(height * 0.43))))
            self.brand.grid_configure(pady=(14, 10))
            self.saved_accounts_label.grid_remove()
            self.sidebar_hint.grid_remove()
        elif width < 1120:
            sidebar_width, horizontal_pad = 292, 28
            self.sidebar.configure(height=1)
            self.brand.grid_configure(pady=(20, 16))
            self.saved_accounts_label.grid()
        else:
            sidebar_width, horizontal_pad = DEFAULT_SIDEBAR_WIDTH, 36
            self.sidebar.configure(height=1)
            self.brand.grid_configure(pady=(20, 16))
            self.saved_accounts_label.grid()
        self.sidebar.configure(width=sidebar_width)
        vertical_pad = 18 if height < 680 else 24
        if compact or height < 720:
            self.sidebar_hint.grid_remove()
        else:
            self.sidebar_hint.grid()
        self.header.grid_configure(padx=horizontal_pad)
        if compact:
            self.detect_button.grid_configure(row=2, column=0, rowspan=1, sticky="w", pady=(12, 0))
            self.browser_button.grid_configure(row=2, column=1, rowspan=1, padx=(10, 0), pady=(12, 0))
        else:
            self.detect_button.grid_configure(row=0, column=1, rowspan=2, sticky="", pady=0)
            self.browser_button.grid_configure(row=0, column=2, rowspan=2, padx=(10, 0), pady=0)
        self.content.configure(padding=(horizontal_pad, vertical_pad, horizontal_pad, 28))
        content_width = width if compact else width - sidebar_width
        wraplength = max(240, min(560, content_width - (horizontal_pad * 2) - 100))
        for label in self._detail_value_labels:
            if label.winfo_exists():
                label.configure(wraplength=wraplength)
        self._update_content_scrollbar()

    def _window_pixel_width(self, fallback: int) -> int:
        if os.name != "nt":
            return fallback
        try:
            class Rect(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

            user32 = ctypes.windll.user32
            get_ancestor = user32.GetAncestor
            get_ancestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            get_ancestor.restype = ctypes.c_void_p
            get_rect = user32.GetWindowRect
            get_rect.argtypes = [ctypes.c_void_p, ctypes.POINTER(Rect)]
            get_rect.restype = ctypes.c_int
            hwnd = get_ancestor(self.root.winfo_id(), 2)
            rect = Rect()
            if hwnd and get_rect(hwnd, ctypes.byref(rect)):
                return max(1, rect.right - rect.left)
        except (AttributeError, OSError, TypeError, ctypes.ArgumentError):
            pass
        return fallback

    def _geometry_width(self) -> int:
        try:
            return max(1, int(self.root.geometry().split("x", 1)[0]))
        except (AttributeError, ValueError):
            return max(1, self.root.winfo_width())

    def _sync_layout_mode(self) -> None:
        if not self.root.winfo_exists():
            return
        try:
            width = max(1, self.root.winfo_width())
            physical_width = self._window_pixel_width(width)
            main_width = self.main.winfo_width()
            geometry_width = self._geometry_width()
            compact = geometry_width < 1000 or physical_width < 900 or (main_width > 1 and main_width < 520)
            if compact != self._compact_layout:
                self._set_layout_mode(compact)
        finally:
            if self.root.winfo_exists():
                self.root.after(400, self._sync_layout_mode)

    def _set_layout_mode(self, compact: bool) -> None:
        self._compact_layout = compact
        if compact:
            self.root.grid_columnconfigure(0, weight=1)
            self.root.grid_columnconfigure(1, weight=0)
            self.root.grid_rowconfigure(0, weight=0)
            self.root.grid_rowconfigure(1, weight=1)
            self.sidebar.configure(width=1, height=260)
            self.sidebar.grid_configure(row=0, column=0, columnspan=2, sticky="ew")
            self.main.grid_configure(row=1, column=0, columnspan=2, sticky="nsew", padx=0)
        else:
            self.root.grid_columnconfigure(0, weight=0)
            self.root.grid_columnconfigure(1, weight=1)
            self.root.grid_rowconfigure(0, weight=1)
            self.root.grid_rowconfigure(1, weight=0)
            self.sidebar.configure(width=DEFAULT_SIDEBAR_WIDTH, height=1)
            self.sidebar.grid_configure(row=0, column=0, columnspan=1, sticky="nsew")
            self.main.grid_configure(row=0, column=1, columnspan=1, sticky="nsew", padx=(1, 0))

    def _on_content_wheel(self, event: tk.Event) -> str:
        self.content_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def _show_empty_state(self) -> None:
        self._clear_content()
        block = ttk.Frame(self.content, style="Panel.TFrame")
        block.grid(row=0, column=0, sticky="nsew", pady=90)
        ttk.Label(block, text="先建立一个本地账户工作台", style="Title.TLabel").pack()
        ttk.Label(
            block,
            text="账户认证彼此隔离；项目目录由每个 Codex 窗口自行打开。",
            style="Muted.TLabel",
        ).pack(pady=(10, 24))
        self._make_primary_button(block, "新建账户配置", self._new_profile).pack()

    def _show_profile(self, profile: Profile) -> None:
        self._clear_content()
        self.selected_profile = profile
        running = profile.id in self._running_profile_ids or self.service.launcher.is_running(profile.id)
        busy_for_profile = self._profile_action_inflight == profile.id
        any_process_action_busy = self._profile_action_inflight is not None
        if not busy_for_profile:
            self.profile_status_var.set("运行中" if running else "未启动")

        title_row = ttk.Frame(self.content, style="Panel.TFrame")
        title_row.grid(row=0, column=0, sticky="ew")
        title_row.grid_columnconfigure(0, weight=1)
        identity = tk.Frame(title_row, bg=COLORS["panel"])
        identity.grid(row=0, column=0, sticky="w")
        identity_dot = tk.Canvas(
            identity,
            width=16,
            height=16,
            bg=COLORS["panel"],
            highlightthickness=0,
            bd=0,
        )
        identity_dot.create_oval(2, 2, 14, 14, fill=profile.color, outline=profile.color)
        identity_dot.pack(side="left", padx=(0, 9))
        ttk.Label(identity, text="账户详情", style="Eyebrow.TLabel").pack(side="left")
        status = tk.Label(
            title_row,
            textvariable=self.profile_status_var,
            bg=COLORS["accent_soft"] if busy_for_profile else ("#EAF7ED" if running else "#F0F0F2"),
            fg=COLORS["accent"] if busy_for_profile else (COLORS["success"] if running else COLORS["idle"]),
            font=(FONT_FAMILY, 9, "bold"),
            padx=10,
            pady=4,
        )
        status.grid(row=0, column=1, sticky="e")
        ttk.Label(self.content, text=profile.name, style="Title.TLabel").grid(
            row=1, column=0, sticky="w", pady=(7, 4)
        )
        ttk.Label(self.content, text=profile.subtitle, style="Muted.TLabel").grid(
            row=2, column=0, sticky="w"
        )

        details = tk.Frame(
            self.content,
            bg=COLORS["surface"],
            highlightbackground=COLORS["line"],
            highlightthickness=1,
            bd=0,
        )
        details.grid(row=4, column=0, sticky="ew", pady=(12, 18))
        details.grid_columnconfigure(1, weight=1)
        rows = [
            ("类型", self._profile_type_label(profile)),
            ("Provider", profile.provider_name or "官方账号登录"),
            ("模型", profile.model or "由 Codex 配置决定"),
            ("Base URL", profile.base_url or "官方默认"),
            ("配置目录", str(profile.codex_home) if not profile.is_system_default else "本机默认 .codex"),
            ("桌面数据", str(profile.user_data_dir) if not profile.is_system_default else "由系统 Codex 管理"),
        ]
        if self.service.skill_service:
            enabled, binding_count, issue_count = self.service.skill_service.status_for_profile(profile)
            skill_status = (
                f"已开启 · {binding_count} 个共享技能"
                if enabled
                else "已关闭 · 使用账户独立副本"
            )
            if issue_count:
                skill_status += f" · {issue_count} 个异常"
            rows.append(("共享技能", skill_status))
        for index, (label, value) in enumerate(rows):
            tk.Label(
                details,
                text=label,
                bg=COLORS["surface"],
                fg=COLORS["muted"],
                font=(FONT_FAMILY, 9),
                anchor="w",
                width=11,
            ).grid(row=index, column=0, sticky="nw", padx=(16, 10), pady=(7, 5))
            value_label = tk.Label(
                details,
                text=value,
                bg=COLORS["surface"],
                fg=COLORS["text"],
                font=(FONT_FAMILY, 9),
                anchor="w",
                justify="left",
                wraplength=560,
            )
            value_label.grid(row=index, column=1, sticky="ew", padx=(0, 16), pady=(7, 5))
            self._detail_value_labels.append(value_label)
            if index < len(rows) - 1:
                tk.Frame(details, height=1, bg="#E5E5EA").grid(
                    row=index,
                    column=0,
                    columnspan=2,
                    sticky="sew",
                    padx=(16, 16),
                )

        launch_text = "打开默认 Codex" if profile.is_system_default else "启动新 Codex 窗口"
        launch_heading = "打开本机默认窗口" if profile.is_system_default else "启动隔离窗口"
        launch_description = (
            "继续使用原有账号、项目与聊天记录"
            if profile.is_system_default
            else "使用此账户的独立登录和桌面状态"
        )
        self._launch_button_text = launch_text
        launch_card = tk.Frame(
            self.content,
            bg=COLORS["launch_surface"],
            highlightbackground=COLORS["line"],
            highlightthickness=1,
            bd=0,
        )
        launch_card.grid(row=3, column=0, sticky="ew", pady=(18, 12))
        launch_card.grid_columnconfigure(0, weight=1)
        tk.Label(
            launch_card,
            text=launch_heading,
            bg=COLORS["launch_surface"],
            fg=COLORS["text"],
            font=(FONT_FAMILY, 11, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=(18, 12), pady=(15, 2))
        tk.Label(
            launch_card,
            text=launch_description,
            bg=COLORS["launch_surface"],
            fg=COLORS["muted"],
            font=(FONT_FAMILY, 9),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=(18, 12), pady=(0, 15))
        window_controls = tk.Frame(launch_card, bg=COLORS["launch_surface"], bd=0)
        window_controls.grid(row=0, column=1, rowspan=2, padx=(8, 18), pady=14, sticky="e")
        self.launch_button = self._make_primary_button(
            window_controls,
            "窗口已在运行" if running else launch_text,
            self._launch_selected,
        )
        self.launch_button.pack(fill="x")
        if running or any_process_action_busy:
            self.launch_button.configure(state="disabled", cursor="arrow")

        process_actions = tk.Frame(window_controls, bg=COLORS["launch_surface"], bd=0)
        process_actions.pack(fill="x", pady=(8, 0))
        self.restart_button = ttk.Button(
            process_actions,
            text="重启 Codex",
            style="Secondary.TButton",
            command=self._restart_selected,
            state="normal" if running and not any_process_action_busy else "disabled",
        )
        self.restart_button.pack(side="left")
        self.close_process_button = ttk.Button(
            process_actions,
            text="关闭进程",
            style="Danger.TButton",
            command=self._close_selected_process,
            state="normal" if running and not any_process_action_busy else "disabled",
        )
        self.close_process_button.pack(side="left", padx=(8, 0))

        ttk.Label(self.content, text="其他操作", style="Overline.TLabel").grid(
            row=5, column=0, sticky="w", pady=(0, 10)
        )
        actions = ttk.Frame(self.content, style="Panel.TFrame")
        actions.grid(row=6, column=0, sticky="ew")
        ttk.Button(actions, text="打开配置目录", style="Secondary.TButton", command=self._open_selected).pack(
            side="left"
        )
        if self.service.skill_service:
            ttk.Button(
                actions,
                text="管理共享技能",
                style="Secondary.TButton",
                command=self._open_skill_manager,
            ).pack(side="left", padx=(10, 0))
        if not profile.is_system_default:
            ttk.Button(actions, text="编辑配置", style="Secondary.TButton", command=self._edit_selected).pack(
                side="left", padx=(10, 0)
            )
            ttk.Button(actions, text="移除", style="Danger.TButton", command=self._remove_selected).pack(
                side="right"
            )

        note = ttk.Label(
            self.content,
            text=(
                "这是本机原有 Codex，不创建新目录，也不修改已有账号和聊天记录。"
                if profile.is_system_default
                else "启动器不会保存 API Key。账号登录和密钥仍由该独立 Codex 窗口管理。"
            ),
            style="Muted.TLabel",
        )
        note.grid(row=7, column=0, sticky="sw", pady=(22, 0))

    def _clear_content(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()
        self.launch_button = None
        self.close_process_button = None
        self.restart_button = None
        self._detail_value_labels = []

    def _make_primary_button(self, parent: tk.Misc, text: str, command: Callable[[], None]) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=COLORS["accent"],
            activebackground=COLORS["accent_hover"],
            fg="#FFFFFF",
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=18,
            pady=10,
            cursor="hand2",
            font=(FONT_FAMILY, 10, "bold"),
        )
        button.bind("<Enter>", lambda _event: button.configure(bg=COLORS["accent_hover"]))
        button.bind("<Leave>", lambda _event: button.configure(bg=COLORS["accent"]))
        button.bind("<ButtonPress-1>", lambda _event: button.configure(relief="sunken"))
        button.bind("<ButtonRelease-1>", lambda _event: button.configure(relief="flat"))
        return button

    def _on_profile_motion(self, event: tk.Event) -> None:
        item = self.profile_tree.identify_row(event.y)
        selected = self.profile_tree.selection()
        selected_id = selected[0] if selected else None
        for child in self.profile_tree.get_children():
            if child != selected_id:
                self.profile_tree.item(child, tags=("hover",) if child == item else ())

    def _on_profile_leave(self, _event: tk.Event) -> None:
        selected = self.profile_tree.selection()
        for child in self.profile_tree.get_children():
            if not selected or child != selected[0]:
                self.profile_tree.item(child, tags=())

    def _show_toast(self, text: str, success: bool = True) -> None:
        if self._toast is not None and self._toast.winfo_exists():
            self._toast.destroy()
        self._toast = tk.Label(
            self.root,
            text=text,
            bg=COLORS["success_soft"] if success else "#FFF0F0",
            fg=COLORS["success"] if success else COLORS["danger"],
            padx=16,
            pady=9,
            font=(FONT_FAMILY, 9, "bold"),
        )
        self._toast.place(relx=0.5, rely=0.94, anchor="center")
        toast = self._toast
        self.root.after(2800, lambda: toast.destroy() if toast.winfo_exists() else None)

    def _reload_profiles(self, preferred_id: str | None = None) -> None:
        self.profiles = self.service.list_profiles()
        selected_id = preferred_id or (self.selected_profile.id if self.selected_profile else self.profiles[0].id)
        self._render_profile_list(selected_id)
        selected = next((profile for profile in self.profiles if profile.id == selected_id), self.profiles[0])
        self.selected_profile = selected
        self._show_profile(selected)

    def _render_profile_list(self, preferred_id: str | None = None) -> None:
        current = preferred_id or (self.selected_profile.id if self.selected_profile else None)
        query = self.search_var.get().strip().lower()
        self.profile_tree.delete(*self.profile_tree.get_children())
        for profile in self.profiles:
            haystack = f"{profile.name} {profile.subtitle}".lower()
            if query and query not in haystack:
                continue
            if profile.is_system_default:
                state = "运行中" if profile.id in self._running_profile_ids else "默认"
            elif profile.id in self._running_profile_ids or self.service.launcher.is_running(profile.id):
                state = "运行中"
            elif profile.kind is ProfileKind.ACCOUNT:
                state = "ChatGPT"
            else:
                state = profile.provider_name or "自定义"
            self.profile_tree.insert("", "end", iid=profile.id, text=f"  {profile.name}  ·  {state}", tags=())
        if current and self.profile_tree.exists(current):
            self.profile_tree.selection_set(current)
            self.profile_tree.focus(current)

    def _on_profile_selected(self, _event: object = None) -> None:
        selection = self.profile_tree.selection()
        if not selection:
            return
        profile_id = selection[0]
        profile = next((item for item in self.profiles if item.id == profile_id), None)
        if profile:
            for child in self.profile_tree.get_children():
                self.profile_tree.item(child, tags=())
            self._show_profile(profile)

    def _new_profile(self) -> None:
        ProfileDialog(self.root, None, self._save_new_profile)

    def _focus_search(self) -> None:
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, tk.END)

    def _edit_selected(self) -> None:
        if self.selected_profile and not self.selected_profile.is_system_default:
            ProfileDialog(self.root, self.selected_profile, self._save_existing_profile)

    def _save_new_profile(self, values: dict[str, str]) -> None:
        try:
            profile = self.service.create_profile(
                name=values["name"],
                kind=ProfileKind(values["kind"]),
                provider_name=values["provider_name"],
                base_url=values["base_url"],
                model=values["model"],
                color=values["color"],
            )
        except (ValueError, OSError) as error:
            messagebox.showerror("无法创建配置", str(error), parent=self.root)
            return
        self.selected_profile = profile
        self._reload_profiles(profile.id)
        self._show_profile(profile)

    def _save_existing_profile(self, values: dict[str, str]) -> None:
        if not self.selected_profile:
            return
        try:
            profile = self.service.update_profile(
                self.selected_profile,
                name=values["name"],
                provider_name=values["provider_name"],
                base_url=values["base_url"],
                model=values["model"],
                color=values["color"],
            )
        except ValueError as error:
            messagebox.showerror("无法保存配置", str(error), parent=self.root)
            return
        self.selected_profile = profile
        self._reload_profiles(profile.id)
        self._show_profile(profile)

    def _launch_selected(self) -> None:
        profile = self.selected_profile
        if not profile:
            return
        if self._profile_action_inflight is not None:
            self._show_toast("请等待当前窗口操作完成", success=False)
            return
        if profile.id in self._running_profile_ids or self.service.launcher.is_running(profile.id):
            self._show_toast("该 Codex 已在运行，可使用“重启 Codex”或“关闭进程”", success=False)
            return
        self._profile_action_inflight = profile.id
        self.profile_status_var.set("启动中…")
        if self.launch_button is not None:
            self.launch_button.configure(text="正在打开…", state="disabled", cursor="arrow")
        self._run_background(
            lambda: self.service.launch_profile(profile),
            lambda pid: self._on_launch_success(profile, pid),
            lambda error: self._on_launch_error(profile, error),
        )

    def _on_launch_success(self, profile: Profile, pid: int) -> None:
        self._profile_action_inflight = None
        self._running_profile_ids = self._running_profile_ids | {profile.id}
        self._render_profile_list(profile.id)
        self._show_profile(profile)
        self.profile_status_var.set("运行中")
        title = f"Codex Profiles · PID {pid}"
        self.root.title(title)
        self._show_toast(f"{profile.name} 已启动 · PID {pid}")
        if self.launch_button is not None:
            self.launch_button.configure(text="窗口已在运行", state="disabled", cursor="arrow")

    def _on_launch_error(self, profile: Profile, error: Exception) -> None:
        self._profile_action_inflight = None
        self._render_profile_list(profile.id)
        self._show_profile(profile)
        self._show_toast("Codex 启动失败，请查看提示", success=False)
        messagebox.showerror("无法启动 Codex", str(error), parent=self.root)

    def _close_selected_process(self) -> None:
        profile = self.selected_profile
        if not profile:
            return
        confirmed = messagebox.askyesno(
            "关闭 Codex 进程",
            f"关闭“{profile.name}”？\n\n"
            "多开器会先请求正常退出；如果 5 秒后仍有后台残留，"
            "只会强制结束此账户对应的进程树。项目和聊天数据不会删除。",
            parent=self.root,
        )
        if not confirmed:
            return
        self._set_process_action_busy(profile, "正在关闭…")
        self._run_background(
            lambda: self.service.close_profile(profile),
            lambda _result: self._on_close_success(profile),
            lambda error: self._on_process_action_error(profile, "无法关闭 Codex", error),
        )

    def _restart_selected(self) -> None:
        profile = self.selected_profile
        if not profile:
            return
        confirmed = messagebox.askyesno(
            "重启 Codex",
            f"重启“{profile.name}”？\n\n"
            "多开器会先请求正常退出，并在必要时清理该账户的后台残留进程，然后重新启动。",
            parent=self.root,
        )
        if not confirmed:
            return
        self._set_process_action_busy(profile, "正在重启…")
        self._run_background(
            lambda: self.service.restart_profile(profile),
            lambda pid: self._on_restart_success(profile, int(pid)),
            lambda error: self._on_process_action_error(profile, "无法重启 Codex", error),
        )

    def _set_process_action_busy(self, profile: Profile, status: str) -> None:
        self._profile_action_inflight = profile.id
        self.profile_status_var.set(status)
        for button in (self.launch_button, self.close_process_button, self.restart_button):
            if button is not None:
                button.configure(state="disabled")

    def _on_close_success(self, profile: Profile) -> None:
        self._profile_action_inflight = None
        self._running_profile_ids = self._running_profile_ids - {profile.id}
        self._render_profile_list(profile.id)
        self._show_profile(profile)
        self._show_toast(f"{profile.name} 的 Codex 进程已关闭")

    def _on_restart_success(self, profile: Profile, pid: int) -> None:
        self._profile_action_inflight = None
        self._running_profile_ids = self._running_profile_ids | {profile.id}
        self._render_profile_list(profile.id)
        self._show_profile(profile)
        self.root.title(f"Codex Profiles · PID {pid}")
        self._show_toast(f"{profile.name} 已重启 · PID {pid}")

    def _on_process_action_error(self, profile: Profile, title: str, error: Exception) -> None:
        self._profile_action_inflight = None
        self._render_profile_list(profile.id)
        self._show_profile(profile)
        self._show_toast(title, success=False)
        messagebox.showerror(title, str(error), parent=self.root)

    def _open_selected(self) -> None:
        if self.selected_profile and self._profile_action_inflight != self.selected_profile.id:
            path = self.selected_profile.codex_home if self.selected_profile.is_system_default else self.selected_profile.codex_home.parent
            self.service.open_directory(path)

    def _open_default_apps_settings(self) -> None:
        try:
            self.service.open_default_apps_settings()
        except OSError as error:
            messagebox.showerror("无法打开 Windows 设置", str(error), parent=self.root)

    def _open_skill_manager(self) -> None:
        if not self.service.skill_service:
            messagebox.showwarning("功能不可用", "共享技能服务尚未初始化。", parent=self.root)
            return
        SkillManagerDialog(self.root, self.service.skill_service, self.profiles)

    def _remove_selected(self) -> None:
        profile = self.selected_profile
        if not profile:
            return
        confirmed = messagebox.askyesno(
            "移除配置",
            f"从启动器列表移除“{profile.name}”？\n\n数据目录会完整保留，不会删除账号状态或历史。",
            parent=self.root,
        )
        if not confirmed:
            return
        try:
            self.service.remove_profile_record(profile)
        except RuntimeError as error:
            messagebox.showwarning("无法移除", str(error), parent=self.root)
            return
        self.selected_profile = None
        self._reload_profiles()

    def _detect_codex(self) -> None:
        self.app_status_var.set("正在检测 Codex…")
        self._run_background(
            self.service.launcher.locator.locate,
            lambda _path: self.app_status_var.set("Codex 已就绪"),
            lambda _error: self.app_status_var.set("未检测到 Codex"),
        )

    def _poll_processes(self) -> None:
        self.service.launcher.refresh()
        if not self._process_poll_inflight:
            self._process_poll_inflight = True
            profiles = tuple(self.profiles)
            self._run_background(
                lambda: self.service.launcher.running_profile_ids(profiles),
                self._on_process_poll_success,
                self._on_process_poll_error,
            )
        self.root.after(1500, self._poll_processes)

    def _on_process_poll_success(self, detected_ids: object) -> None:
        self._process_poll_inflight = False
        running_profile_ids = frozenset(detected_ids) | frozenset(
            profile.id for profile in self.profiles if self.service.launcher.is_running(profile.id)
        )
        if running_profile_ids != self._running_profile_ids:
            self._running_profile_ids = running_profile_ids
            self._render_profile_list()
        if self.selected_profile:
            running = self.selected_profile.id in running_profile_ids
            expected = "运行中" if running else "未启动"
            if self.profile_status_var.get() != expected:
                self._show_profile(self.selected_profile)

    def _on_process_poll_error(self, _error: Exception) -> None:
        self._process_poll_inflight = False

    @staticmethod
    def _profile_type_label(profile: Profile) -> str:
        if profile.is_system_default:
            return "系统默认"
        if profile.kind is ProfileKind.ACCOUNT:
            return "ChatGPT 账号"
        return "自定义 Provider"

    def _run_background(
        self,
        work: Callable[[], object],
        success: Callable[[object], None],
        failure: Callable[[Exception], None],
    ) -> None:
        def execute() -> None:
            try:
                result = work()
            except Exception as error:  # Boundary: surface background failures in the UI.
                self.root.after(0, lambda: failure(error))
            else:
                self.root.after(0, lambda: success(result))

        threading.Thread(target=execute, daemon=True).start()


class ProfileDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Tk,
        profile: Profile | None,
        on_save: Callable[[dict[str, str]], None],
    ) -> None:
        super().__init__(parent)
        self.profile = profile
        self.on_save = on_save
        self.title("编辑配置" if profile else "新建配置")
        dialog_height = min(720, max(520, self.winfo_screenheight() - 120))
        self.geometry(f"520x{dialog_height}")
        self.minsize(460, 480)
        self.resizable(False, True)
        self.configure(bg=COLORS["panel"])
        self.transient(parent)
        self.grab_set()

        self.name_var = tk.StringVar(value=profile.name if profile else "")
        self.kind_var = tk.StringVar(value=profile.kind.value if profile else ProfileKind.ACCOUNT.value)
        self.provider_var = tk.StringVar(value=profile.provider_name if profile else "")
        self.base_url_var = tk.StringVar(value=profile.base_url if profile else "")
        self.model_var = tk.StringVar(value=profile.model if profile else "")
        color_name = next((name for name, value in PROFILE_COLORS.items() if profile and value == profile.color), "海湾蓝")
        self.color_var = tk.StringVar(value=color_name)

        self._build()
        self.kind_var.trace_add("write", lambda *_: self._toggle_provider_fields())
        self._toggle_provider_fields()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Control-Return>", lambda _event: self._save())

    def _build(self) -> None:
        actions = ttk.Frame(self, style="Panel.TFrame")
        actions.pack(side="bottom", fill="x", padx=36, pady=(16, 24))
        ttk.Button(actions, text="取消", style="Secondary.TButton", command=self.destroy).pack(side="right")
        ttk.Button(actions, text="保存配置", style="Primary.TButton", command=self._save).pack(
            side="right", padx=(0, 10)
        )

        tk.Frame(self, bg=COLORS["line"], height=1).pack(side="bottom", fill="x")

        scroll_area = tk.Frame(self, bg=COLORS["panel"])
        scroll_area.pack(side="top", fill="both", expand=True)
        canvas = tk.Canvas(scroll_area, bg=COLORS["panel"], highlightthickness=0, borderwidth=0)
        self.form_canvas = canvas
        scrollbar = ttk.Scrollbar(scroll_area, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        body = ttk.Frame(canvas, style="Panel.TFrame")
        self.form_body = body
        body_window = canvas.create_window((24, 24), window=body, anchor="nw")
        body.grid_columnconfigure(0, weight=1)
        body.bind(
            "<Configure>",
            lambda _event: self._update_scroll_region(),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(body_window, width=max(1, event.width - 48)),
        )
        self.bind(
            "<MouseWheel>",
            self._on_mousewheel,
        )
        ttk.Label(body, text="编辑配置" if self.profile else "新建配置", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            body,
            text="每个账户都有独立的登录状态；项目目录仍由 Codex 窗口自行打开。",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(6, 20))

        self._field(body, 2, "名称", ttk.Entry(body, textvariable=self.name_var))

        ttk.Label(body, text="登录方式", style="Muted.TLabel").grid(row=4, column=0, sticky="w", pady=(12, 7))
        kind_row = ttk.Frame(body, style="Panel.TFrame")
        kind_row.grid(row=5, column=0, sticky="ew", pady=(0, 10))
        account = ttk.Radiobutton(
            kind_row,
            text="ChatGPT 账号",
            variable=self.kind_var,
            value=ProfileKind.ACCOUNT.value,
        )
        provider = ttk.Radiobutton(
            kind_row,
            text="自定义 Provider",
            variable=self.kind_var,
            value=ProfileKind.PROVIDER.value,
        )
        account.pack(side="left")
        provider.pack(side="left", padx=(24, 0))
        if self.profile:
            account.configure(state="disabled")
            provider.configure(state="disabled")

        self.provider_frame = ttk.Frame(body, style="Panel.TFrame")
        self.provider_frame.grid(row=6, column=0, sticky="ew")
        self.provider_frame.grid_columnconfigure(0, weight=1)
        self.provider_entry = ttk.Entry(self.provider_frame, textvariable=self.provider_var)
        self.base_url_entry = ttk.Entry(self.provider_frame, textvariable=self.base_url_var)
        self.model_entry = ttk.Entry(self.provider_frame, textvariable=self.model_var)
        self._field(self.provider_frame, 0, "Provider 名称", self.provider_entry)
        self._field(self.provider_frame, 2, "Base URL", self.base_url_entry)
        self._field(self.provider_frame, 4, "默认模型（可选）", self.model_entry)

        ttk.Label(body, text="账户颜色", style="Muted.TLabel").grid(row=7, column=0, sticky="w", pady=(14, 7))
        ttk.Combobox(body, textvariable=self.color_var, values=list(PROFILE_COLORS), state="readonly").grid(
            row=8, column=0, sticky="ew"
        )

        note = tk.Label(
            body,
            text="启动器不会保存 API Key。Provider 配置只包含模型与 Base URL。",
            bg=COLORS["accent_soft"],
            fg="#1F4F7A",
            font=(FONT_FAMILY, 9),
            justify="left",
            anchor="w",
            padx=14,
            pady=12,
        )
        note.grid(row=9, column=0, sticky="ew", pady=(16, 18))

        ttk.Frame(body, style="Panel.TFrame", height=28).grid(row=10, column=0)

    @staticmethod
    def _field(parent: ttk.Frame, row: int, label: str, widget: ttk.Widget) -> None:
        ttk.Label(parent, text=label, style="Muted.TLabel").grid(
            row=row, column=0, sticky="w", pady=(8, 6)
        )
        widget.grid(row=row + 1, column=0, sticky="ew", pady=(0, 6))

    def _toggle_provider_fields(self) -> None:
        if self.kind_var.get() == ProfileKind.PROVIDER.value:
            self.provider_frame.grid()
        else:
            self.provider_frame.grid_remove()
        self.after_idle(self._update_scroll_region)

    def _update_scroll_region(self) -> None:
        bounds = self.form_canvas.bbox("all")
        if bounds:
            self.form_canvas.configure(scrollregion=bounds)

    def _on_mousewheel(self, event: tk.Event) -> str:
        direction = -1 if event.delta > 0 else 1
        self.form_canvas.yview_scroll(direction * 3, "units")
        return "break"

    def _save(self) -> None:
        values = {
            "name": self.name_var.get(),
            "kind": self.kind_var.get(),
            "provider_name": self.provider_var.get(),
            "base_url": self.base_url_var.get(),
            "model": self.model_var.get(),
            "color": PROFILE_COLORS[self.color_var.get()],
        }
        if not values["name"].strip():
            messagebox.showwarning("缺少名称", "请输入配置名称。", parent=self)
            return
        if values["kind"] == ProfileKind.PROVIDER.value and not values["base_url"].strip():
            messagebox.showwarning("缺少 Base URL", "Provider 配置需要填写 Base URL。", parent=self)
            return
        self.on_save(values)
        self.destroy()
