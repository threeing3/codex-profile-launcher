from __future__ import annotations

import time
import tkinter as tk
from tkinter import messagebox, ttk

from .models import Profile
from .skill_catalog import is_junction
from .skill_models import MigrationPreview, SkillPlan, SkillState
from .skill_service import RunningProfilesError, SensitiveSkillError, SkillService


FONT_FAMILY = "Microsoft YaHei UI"
PANEL = "#F2F2F7"
SURFACE = "#FFFFFF"
LINE = "#D1D1D6"
TEXT = "#1D1D1F"
MUTED = "#6E6E73"
ACCENT = "#007AFF"
ACCENT_SOFT = "#E6F1FF"
WARNING_SOFT = "#FFF7E6"
SUCCESS_SOFT = "#EAF6EC"

STATE_TEXT = {
    SkillState.SHARED: "已共享",
    SkillState.IDENTICAL: "内容相同，可合并",
    SkillState.UNIQUE: "独有技能，可加入",
    SkillState.CONFLICT: "需要选择版本",
    SkillState.INVALID: "不会迁移",
    SkillState.BROKEN: "入口异常",
}


class SkillManagerDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk, service: SkillService, profiles: list[Profile]) -> None:
        super().__init__(parent)
        self.service = service
        self.profiles = profiles
        self.preview_data: MigrationPreview | None = None
        self.plans: dict[str, SkillPlan] = {}
        self.selections: dict[str, str] = {}
        self.source_display_to_id: dict[str, str] = {}
        self.shared_skill_names: list[str] = []
        self._compact_dialog = False

        self.status_var = tk.StringVar(value="正在扫描技能目录…")
        self.summary_var = tk.StringVar(value="准备扫描默认窗口和独立账户。")
        self.next_action_var = tk.StringVar(value="扫描完成后，这里会告诉你下一步。")
        self.conflict_var = tk.StringVar()
        self.conflict_help_var = tk.StringVar(value="先在上方列表选择一个冲突技能。")
        self.account_skill_var = tk.StringVar()
        self.account_help_var = tk.StringVar(value="选择账户后，可以控制整个账户或单个技能。")
        self.maintenance_skill_var = tk.StringVar()
        self.maintenance_help_var = tk.StringVar(value="完成首次共享后，可以在这里恢复或全局移除技能。")

        self.title("共享技能")
        width = min(1080, max(820, self.winfo_screenwidth() - 120))
        height = min(780, max(600, self.winfo_screenheight() - 120))
        self.geometry(f"{width}x{height}")
        self.minsize(780, 560)
        self.configure(bg=PANEL)
        self.transient(parent)
        self._build()
        self.bind("<Configure>", self._sync_dialog_layout, add="+")
        self.after_idle(self.refresh)

    def _build(self) -> None:
        container = ttk.Frame(self, padding=(26, 22, 26, 18))
        container.pack(fill="both", expand=True)
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(1, weight=1)

        header = ttk.Frame(container)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        header.grid_columnconfigure(0, weight=1)
        ttk.Label(header, text="共享技能", font=(FONT_FAMILY, 20, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="让默认 Codex 和多个独立窗口使用同一份用户技能；系统技能、登录与聊天仍保持隔离。",
            foreground=MUTED,
            font=(FONT_FAMILY, 9),
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Button(header, text="重新扫描", command=self.refresh).grid(
            row=0, column=1, rowspan=2, sticky="e"
        )

        self.notebook = ttk.Notebook(container)
        self.notebook.grid(row=1, column=0, sticky="nsew")
        self._build_migration_tab()
        self._build_account_tab()
        self._build_maintenance_tab()

        footer = ttk.Frame(container)
        footer.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        footer.grid_columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var, foreground=MUTED).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(footer, text="关闭", command=self.destroy).grid(row=0, column=1, sticky="e")

    def _build_migration_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=18)
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(3, weight=1, minsize=120)
        self.migration_tab = tab
        self.notebook.add(tab, text="  迁移向导  ")

        steps = tk.Frame(tab, bg=PANEL)
        self.steps_frame = steps
        steps.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        for column in range(3):
            steps.grid_columnconfigure(column, weight=1, uniform="step")
        self._step_card(steps, 0, "1", "查看扫描结果", "确认哪些技能会进入共享库")
        self._step_card(steps, 1, "2", "处理版本冲突", "同名不同内容时选择保留版本")
        self._step_card(steps, 2, "3", "确认并开始共享", "备份后为每个账户建立入口")

        summary = tk.Frame(
            tab,
            bg=ACCENT_SOFT,
            highlightbackground="#B8D8FF",
            highlightthickness=1,
        )
        summary.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        summary.grid_columnconfigure(0, weight=1)
        tk.Label(
            summary,
            textvariable=self.summary_var,
            bg=ACCENT_SOFT,
            fg="#174A75",
            font=(FONT_FAMILY, 10, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=14, pady=(11, 2))
        tk.Label(
            summary,
            textvariable=self.next_action_var,
            bg=ACCENT_SOFT,
            fg="#315D7D",
            font=(FONT_FAMILY, 9),
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 11))

        ttk.Label(tab, text="技能扫描结果", font=(FONT_FAMILY, 11, "bold")).grid(
            row=2, column=0, sticky="w", pady=(0, 7)
        )
        tree_frame = ttk.Frame(tab)
        tree_frame.grid(row=3, column=0, sticky="nsew")
        tree_frame.grid_columnconfigure(0, weight=1)
        tree_frame.grid_rowconfigure(0, weight=1)
        self.migration_tree = ttk.Treeview(
            tree_frame,
            columns=("state", "source", "locations"),
            show="tree headings",
            selectmode="browse",
        )
        self.migration_tree.heading("#0", text="技能")
        self.migration_tree.heading("state", text="需要做什么")
        self.migration_tree.heading("source", text="采用的版本")
        self.migration_tree.heading("locations", text="发现位置")
        self.migration_tree.column("#0", width=240)
        self.migration_tree.column("state", width=170)
        self.migration_tree.column("source", width=210)
        self.migration_tree.column("locations", width=90, anchor="center")
        self.migration_tree.grid(row=0, column=0, sticky="nsew")
        migration_scroll = ttk.Scrollbar(
            tree_frame, orient="vertical", command=self.migration_tree.yview
        )
        migration_scroll.grid(row=0, column=1, sticky="ns")
        self.migration_tree.configure(yscrollcommand=migration_scroll.set)
        self.migration_tree.tag_configure("conflict", background=WARNING_SOFT)
        self.migration_tree.tag_configure("invalid", foreground=MUTED)
        self.migration_tree.bind("<<TreeviewSelect>>", self._on_migration_skill_selected)

        conflict = ttk.LabelFrame(tab, text="第 2 步：选择冲突版本", padding=12)
        conflict.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        conflict.grid_columnconfigure(1, weight=1)
        ttk.Label(conflict, textvariable=self.conflict_help_var, foreground=MUTED).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )
        ttk.Label(conflict, text="保留版本").grid(row=1, column=0, sticky="w", padx=(0, 10))
        self.conflict_combo = ttk.Combobox(
            conflict,
            textvariable=self.conflict_var,
            state="disabled",
        )
        self.conflict_combo.grid(row=1, column=1, sticky="ew")
        self.conflict_combo.bind("<<ComboboxSelected>>", self._on_conflict_choice)

        migration_actions = ttk.Frame(tab)
        migration_actions.grid(row=5, column=0, sticky="ew", pady=(14, 0))
        migration_actions.grid_columnconfigure(0, weight=1)
        ttk.Label(
            migration_actions,
            text="执行前会显示最终确认，并要求受影响的 Codex 窗口正常关闭。",
            foreground=MUTED,
        ).grid(row=0, column=0, sticky="w")
        self.apply_button = ttk.Button(
            migration_actions,
            text="确认方案并开始共享",
            style="Primary.TButton",
            command=self.apply_migration,
            state="disabled",
        )
        self.apply_button.grid(row=0, column=1, sticky="e", padx=(14, 0))

    def _sync_dialog_layout(self, event: tk.Event | None = None) -> None:
        if event is not None and event.widget is not self:
            return
        compact = self.winfo_height() < 680
        if compact == self._compact_dialog:
            return
        self._compact_dialog = compact
        if compact:
            self.steps_frame.grid_remove()
            self.migration_tab.configure(padding=12)
        else:
            self.steps_frame.grid()
            self.migration_tab.configure(padding=18)

    def _build_account_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=18)
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)
        self.notebook.add(tab, text="  账户与技能  ")

        ttk.Label(tab, text="控制哪些账户使用共享技能", font=(FONT_FAMILY, 15, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            tab,
            text="先选择账户，再选择技能。按钮会直接说明操作结果，不会删除技能内容。",
            foreground=MUTED,
        ).grid(row=1, column=0, sticky="w", pady=(5, 12))

        self.profile_tree = ttk.Treeview(
            tab,
            columns=("enabled", "bindings", "issues"),
            show="tree headings",
            selectmode="browse",
            height=7,
        )
        self.profile_tree.heading("#0", text="账户")
        self.profile_tree.heading("enabled", text="账户共享状态")
        self.profile_tree.heading("bindings", text="共享技能数")
        self.profile_tree.heading("issues", text="异常")
        self.profile_tree.column("#0", width=300)
        self.profile_tree.column("enabled", width=160)
        self.profile_tree.column("bindings", width=120, anchor="center")
        self.profile_tree.column("issues", width=90, anchor="center")
        self.profile_tree.grid(row=2, column=0, sticky="nsew")
        self.profile_tree.bind("<<TreeviewSelect>>", self._update_account_controls)

        account_card = ttk.LabelFrame(tab, text="所选账户的操作", padding=14)
        account_card.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        account_card.grid_columnconfigure(1, weight=1)
        ttk.Label(account_card, textvariable=self.account_help_var, foreground=MUTED).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 10)
        )
        ttk.Label(account_card, text="技能").grid(row=1, column=0, sticky="w", padx=(0, 10))
        self.account_skill_combo = ttk.Combobox(
            account_card,
            textvariable=self.account_skill_var,
            state="disabled",
        )
        self.account_skill_combo.grid(row=1, column=1, sticky="ew")
        self.account_skill_combo.bind("<<ComboboxSelected>>", self._update_account_controls)
        self.profile_toggle_button = ttk.Button(
            account_card,
            text="为账户开启共享",
            command=self.toggle_profile,
            state="disabled",
        )
        self.profile_toggle_button.grid(row=1, column=2, padx=(10, 0))

        skill_actions = ttk.Frame(account_card)
        skill_actions.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        self.enable_skill_button = ttk.Button(
            skill_actions,
            text="让此账户使用共享版",
            command=self.enable_selected_skill,
            state="disabled",
        )
        self.enable_skill_button.pack(side="left")
        self.detach_skill_button = ttk.Button(
            skill_actions,
            text="保留为此账户的独立副本",
            command=self.detach_selected_skill,
            state="disabled",
        )
        self.detach_skill_button.pack(side="left", padx=(8, 0))

    def _build_maintenance_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=18)
        tab.grid_columnconfigure(0, weight=1)
        self.notebook.add(tab, text="  恢复与维护  ")

        ttk.Label(tab, text="恢复与维护", font=(FONT_FAMILY, 15, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            tab,
            text="这些操作会影响所有正在使用该共享技能的账户，因此会再次确认并要求关闭相关窗口。",
            foreground=MUTED,
        ).grid(row=1, column=0, sticky="w", pady=(5, 16))

        card = ttk.LabelFrame(tab, text="选择共享技能", padding=16)
        card.grid(row=2, column=0, sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        self.maintenance_skill_combo = ttk.Combobox(
            card,
            textvariable=self.maintenance_skill_var,
            state="disabled",
        )
        self.maintenance_skill_combo.grid(row=0, column=0, sticky="ew")
        self.maintenance_skill_combo.bind("<<ComboboxSelected>>", self._update_maintenance_controls)
        ttk.Label(card, textvariable=self.maintenance_help_var, foreground=MUTED).grid(
            row=1, column=0, sticky="w", pady=(10, 0)
        )

        actions = ttk.Frame(tab)
        actions.grid(row=3, column=0, sticky="w", pady=(16, 0))
        self.restore_button = ttk.Button(
            actions,
            text="从最近快照恢复所选技能",
            command=self.restore_snapshot,
            state="disabled",
        )
        self.restore_button.pack(side="left")
        self.remove_button = ttk.Button(
            actions,
            text="从所有账户移除所选技能",
            command=self.remove_shared_skill,
            state="disabled",
        )
        self.remove_button.pack(side="left", padx=(10, 0))

        notice = tk.Frame(tab, bg=SUCCESS_SOFT, highlightbackground="#B9DDBF", highlightthickness=1)
        notice.grid(row=4, column=0, sticky="ew", pady=(26, 0))
        tk.Label(
            notice,
            text="安全说明",
            bg=SUCCESS_SOFT,
            fg="#246B35",
            font=(FONT_FAMILY, 10, "bold"),
        ).pack(anchor="w", padx=14, pady=(12, 3))
        tk.Label(
            notice,
            text="解除共享会保留独立副本；全局移除会保留最后快照；历史快照不会自动清理。",
            bg=SUCCESS_SOFT,
            fg="#356C40",
            font=(FONT_FAMILY, 9),
        ).pack(anchor="w", padx=14, pady=(0, 12))

    @staticmethod
    def _step_card(parent: tk.Frame, column: int, number: str, title: str, detail: str) -> None:
        card = tk.Frame(parent, bg=SURFACE, highlightbackground=LINE, highlightthickness=1)
        card.grid(
            row=0,
            column=column,
            sticky="ew",
            padx=(0 if column == 0 else 5, 0 if column == 2 else 5),
        )
        badge = tk.Label(
            card,
            text=number,
            bg=ACCENT,
            fg="#FFFFFF",
            width=2,
            font=(FONT_FAMILY, 9, "bold"),
        )
        badge.grid(row=0, column=0, rowspan=2, padx=(12, 9), pady=12)
        tk.Label(card, text=title, bg=SURFACE, fg=TEXT, font=(FONT_FAMILY, 9, "bold")).grid(
            row=0, column=1, sticky="w", pady=(10, 1), padx=(0, 10)
        )
        tk.Label(card, text=detail, bg=SURFACE, fg=MUTED, font=(FONT_FAMILY, 8)).grid(
            row=1, column=1, sticky="w", pady=(0, 10), padx=(0, 10)
        )

    def refresh(self) -> None:
        try:
            preview = self.service.preview(self.profiles)
        except Exception as error:
            self.status_var.set("扫描失败")
            messagebox.showerror("无法扫描技能", str(error), parent=self)
            return
        self.preview_data = preview
        self.plans = {plan.name: plan for plan in preview.plans}
        self.selections.clear()
        self.migration_tree.delete(*self.migration_tree.get_children())
        first_conflict: str | None = None
        for plan in preview.plans:
            recommended = next(
                (source for source in plan.sources if source.profile_id == plan.recommended_profile_id),
                None,
            )
            if recommended and not plan.requires_choice:
                self.selections[plan.name] = recommended.profile_id
            if plan.requires_choice and first_conflict is None:
                first_conflict = plan.name
            tags = (
                ("conflict",)
                if plan.requires_choice
                else ("invalid",)
                if plan.state is SkillState.INVALID
                else ()
            )
            self.migration_tree.insert(
                "",
                "end",
                iid=plan.name,
                text=plan.name,
                values=(
                    STATE_TEXT[plan.state],
                    (
                        f"建议：{recommended.profile_name}"
                        if recommended and plan.requires_choice
                        else recommended.profile_name
                        if recommended
                        else "—"
                    ),
                    len(plan.sources),
                ),
                tags=tags,
            )

        conflicts = len(preview.conflicts)
        invalid = sum(1 for plan in preview.plans if plan.state is SkillState.INVALID)
        shared_count = sum(1 for plan in preview.plans if plan.state is SkillState.SHARED)
        pending_count = sum(
            1
            for plan in preview.plans
            if plan.state not in {SkillState.SHARED, SkillState.INVALID}
        )
        self.summary_var.set(
            f"扫描完成：{shared_count} 个已共享，{pending_count} 个等待处理，"
            f"{conflicts} 个版本冲突，{invalid} 个目录不会迁移。"
        )
        if conflicts:
            self.next_action_var.set("下一步：选择黄色冲突项，并在下方选择要保留的版本。")
        elif pending_count:
            self.next_action_var.set("方案已就绪。检查列表后，点击“确认方案并开始共享”。")
        elif shared_count:
            self.next_action_var.set("共享库已是最新状态；日常开关请使用“账户与技能”页。")
        else:
            self.next_action_var.set("当前没有可以迁移的用户技能。")

        if first_conflict:
            self.migration_tree.selection_set(first_conflict)
            self.migration_tree.focus(first_conflict)
            self.migration_tree.see(first_conflict)
            self._on_migration_skill_selected()
        elif preview.plans:
            self.migration_tree.selection_set(preview.plans[0].name)
            self._on_migration_skill_selected()
        self._refresh_profiles()
        self._refresh_shared_skill_choices()
        self._update_apply_state()
        self.status_var.set(
            f"已扫描 {len(self.profiles)} 个账户 · {len(preview.plans)} 个目录 · "
            f"{self.service.snapshot_count()} 个历史快照"
        )

    def _refresh_profiles(self) -> None:
        self.profile_tree.delete(*self.profile_tree.get_children())
        library_ready = any(
            item.is_dir() and item.name != ".system"
            for item in self.service.paths.shared_skills.iterdir()
        ) if self.service.paths.shared_skills.exists() else False
        for profile in self.profiles:
            enabled, bindings, issues = self.service.status_for_profile(profile)
            self.profile_tree.insert(
                "",
                "end",
                iid=profile.id,
                text=profile.name,
                values=(
                    "等待首次迁移"
                    if not library_ready
                    else ("已开启" if enabled else "已关闭"),
                    bindings,
                    issues,
                ),
            )
        if self.profiles:
            self.profile_tree.selection_set(self.profiles[0].id)
            self.profile_tree.focus(self.profiles[0].id)
        self._update_account_controls()

    def _refresh_shared_skill_choices(self) -> None:
        shared_root = self.service.paths.shared_skills
        self.shared_skill_names = (
            sorted(
                [
                    item.name
                    for item in shared_root.iterdir()
                    if item.is_dir() and item.name != ".system"
                ],
                key=str.casefold,
            )
            if shared_root.exists()
            else []
        )
        state = "readonly" if self.shared_skill_names else "disabled"
        for combo in (self.account_skill_combo, self.maintenance_skill_combo):
            combo.configure(values=self.shared_skill_names, state=state)
        if self.shared_skill_names:
            if self.account_skill_var.get() not in self.shared_skill_names:
                self.account_skill_var.set(self.shared_skill_names[0])
            if self.maintenance_skill_var.get() not in self.shared_skill_names:
                self.maintenance_skill_var.set(self.shared_skill_names[0])
        else:
            self.account_skill_var.set("")
            self.maintenance_skill_var.set("")
        self._update_account_controls()
        self._update_maintenance_controls()

    def _on_migration_skill_selected(self, _event: object = None) -> None:
        selection = self.migration_tree.selection()
        if not selection:
            return
        plan = self.plans[selection[0]]
        if not plan.requires_choice:
            self.conflict_combo.configure(state="disabled", values=())
            self.conflict_var.set("")
            if plan.state is SkillState.INVALID:
                self.conflict_help_var.set(f"“{plan.name}”缺少有效 SKILL.md，因此不会迁移。")
            else:
                self.conflict_help_var.set(f"“{plan.name}”无需选择版本。")
            return
        self.source_display_to_id = {}
        values: list[str] = []
        selected_display = ""
        for source in plan.sources:
            display = f"{source.profile_name} · {source.digest[:10]}"
            self.source_display_to_id[display] = source.profile_id
            values.append(display)
            if source.profile_id == self.selections.get(plan.name):
                selected_display = display
        self.conflict_combo.configure(state="readonly", values=values)
        self.conflict_var.set(selected_display)
        self.conflict_help_var.set(f"“{plan.name}”在多个账户中的内容不同，请明确选择一个版本。")

    def _on_conflict_choice(self, _event: object = None) -> None:
        selection = self.migration_tree.selection()
        if not selection:
            return
        plan = self.plans[selection[0]]
        profile_id = self.source_display_to_id.get(self.conflict_var.get())
        if profile_id:
            self.selections[plan.name] = profile_id
            source = next(item for item in plan.sources if item.profile_id == profile_id)
            values = list(self.migration_tree.item(plan.name, "values"))
            values[1] = source.profile_name
            self.migration_tree.item(plan.name, values=values, tags=())
            self.conflict_help_var.set(f"已选择 {source.profile_name} 的版本。")
            self._update_apply_state()

    def _update_apply_state(self) -> None:
        if self.preview_data is None:
            self.apply_button.configure(state="disabled")
            return
        unresolved = [
            plan.name for plan in self.preview_data.conflicts if plan.name not in self.selections
        ]
        pending = [
            plan
            for plan in self.preview_data.plans
            if plan.state not in {SkillState.SHARED, SkillState.INVALID}
        ]
        state = "normal" if pending and not unresolved else "disabled"
        self.apply_button.configure(state=state)
        if unresolved:
            self.apply_button.configure(text=f"还需处理 {len(unresolved)} 个冲突")
        elif not pending:
            self.apply_button.configure(text="共享库已是最新")
        else:
            self.apply_button.configure(text="确认方案并开始共享")

    def _update_account_controls(self, _event: object = None) -> None:
        profile = self._selected_profile(show_warning=False)
        if profile is None:
            self.account_help_var.set("先从上方选择一个账户。")
            self.profile_toggle_button.configure(state="disabled")
            self.enable_skill_button.configure(state="disabled")
            self.detach_skill_button.configure(state="disabled")
            return
        if not self.shared_skill_names:
            self.account_help_var.set(
                f"当前账户：{profile.name}。共享库尚未建立，请先在“迁移向导”完成首次共享。"
            )
            self.profile_toggle_button.configure(state="disabled", text="等待首次迁移")
            self.enable_skill_button.configure(state="disabled")
            self.detach_skill_button.configure(state="disabled")
            return
        enabled, bindings, issues = self.service.status_for_profile(profile)
        status = "已开启" if enabled else "已关闭"
        issue_text = f"，有 {issues} 个异常" if issues else ""
        self.account_help_var.set(
            f"当前账户：{profile.name}；共享状态：{status}；正在使用 {bindings} 个共享技能{issue_text}。"
        )
        self.profile_toggle_button.configure(
            state="normal",
            text="关闭账户共享并保留副本" if enabled else "为账户开启全部共享",
        )
        skill_name = self.account_skill_var.get()
        if not skill_name:
            self.enable_skill_button.configure(state="disabled")
            self.detach_skill_button.configure(state="disabled")
            return
        target = profile.codex_home / "skills" / skill_name
        linked = is_junction(target)
        self.enable_skill_button.configure(state="disabled" if linked else "normal")
        self.detach_skill_button.configure(state="normal" if linked else "disabled")

    def _update_maintenance_controls(self, _event: object = None) -> None:
        skill_name = self.maintenance_skill_var.get()
        state = "normal" if skill_name else "disabled"
        self.restore_button.configure(state=state)
        self.remove_button.configure(state=state)
        if skill_name:
            self.maintenance_help_var.set(
                f"当前选择：{skill_name}。恢复会影响所有使用者；全局移除会永久保留最后快照。"
            )
        else:
            self.maintenance_help_var.set("共享库还是空的，请先在“迁移向导”完成首次共享。")

    def apply_migration(self) -> None:
        if self.preview_data is None:
            return
        unresolved = [
            plan.name for plan in self.preview_data.conflicts if plan.name not in self.selections
        ]
        if unresolved:
            first = unresolved[0]
            self.migration_tree.selection_set(first)
            self.migration_tree.see(first)
            self._on_migration_skill_selected()
            messagebox.showwarning(
                "还不能开始",
                "请先为以下冲突技能选择版本：\n" + "\n".join(unresolved),
                parent=self,
            )
            return
        if not messagebox.askyesno(
            "确认开始共享",
            f"将把 {len(self.preview_data.valid_plans)} 个用户技能迁入中央共享库，"
            "并为所有账户建立共享入口。\n\n操作前会完整备份，失败会回滚。是否继续？",
            parent=self,
        ):
            return
        try:
            operation_id = self._apply_with_close_handling(False)
        except SensitiveSkillError as error:
            if not messagebox.askyesno(
                "发现疑似敏感内容",
                f"{error}\n\n仍然强制加入共享库吗？",
                parent=self,
            ):
                return
            operation_id = self._apply_with_close_handling(True)
        except Exception as error:
            messagebox.showerror("迁移失败", str(error), parent=self)
            return
        messagebox.showinfo(
            "共享已建立",
            f"共享技能迁移已完成。\n操作编号：{operation_id}\n相关 Codex 窗口重新启动后生效。",
            parent=self,
        )
        self.refresh()
        self.notebook.select(1)

    def _apply_with_close_handling(self, allow_sensitive: bool) -> str:
        assert self.preview_data is not None
        try:
            return self.service.apply_initial_migration(
                self.preview_data,
                self.profiles,
                self.selections,
                allow_sensitive=allow_sensitive,
            )
        except RunningProfilesError as error:
            if not messagebox.askyesno(
                "需要关闭 Codex 窗口",
                f"{error}\n\n是否请求这些窗口正常关闭，然后重试？",
                parent=self,
            ):
                raise
            for profile in self.profiles:
                if profile.name in error.profile_names:
                    self.service.launcher.request_close_profile(profile)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if not any(
                    self.service.launcher.is_profile_process_running(profile)
                    for profile in self.profiles
                    if profile.name in error.profile_names
                ):
                    break
                time.sleep(0.5)
            return self.service.apply_initial_migration(
                self.preview_data,
                self.profiles,
                self.selections,
                allow_sensitive=allow_sensitive,
            )

    def toggle_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        enabled, _, _ = self.service.status_for_profile(profile)
        description = (
            "所有共享技能会复制为该账户的独立副本，不会删除内容。"
            if enabled
            else "将为该账户接入全部共享技能；内容冲突会阻止操作。"
        )
        if not messagebox.askyesno(
            "关闭账户共享" if enabled else "开启账户共享",
            f"账户：{profile.name}\n\n{description}\n\n是否继续？",
            parent=self,
        ):
            return
        try:
            self.service.set_profile_sharing(profile, not enabled)
        except Exception as error:
            messagebox.showerror("操作失败", str(error), parent=self)
            return
        self.refresh()

    def enable_selected_skill(self) -> None:
        self._set_selected_skill_binding(True)

    def detach_selected_skill(self) -> None:
        self._set_selected_skill_binding(False)

    def _set_selected_skill_binding(self, enabled: bool) -> None:
        profile = self._selected_profile()
        skill_name = self.account_skill_var.get()
        if profile is None or not skill_name:
            return
        action = "使用共享版" if enabled else "保留为账户独立副本"
        if not messagebox.askyesno(
            action,
            f"账户：{profile.name}\n技能：{skill_name}\n操作：{action}\n\n是否继续？",
            parent=self,
        ):
            return
        try:
            self.service.set_skill_binding(profile, skill_name, enabled)
        except Exception as error:
            messagebox.showerror("操作失败", str(error), parent=self)
            return
        self.refresh()

    def restore_snapshot(self) -> None:
        skill_name = self.maintenance_skill_var.get()
        if not skill_name:
            return
        affected = "、".join(profile.name for profile in self.profiles)
        if not messagebox.askyesno(
            "全局恢复共享技能",
            f"将把“{skill_name}”恢复到最近快照。\n受影响账户：{affected}\n\n是否继续？",
            parent=self,
        ):
            return
        try:
            self.service.restore_latest_snapshot(skill_name, self.profiles)
        except Exception as error:
            messagebox.showerror("恢复失败", str(error), parent=self)
            return
        messagebox.showinfo("恢复完成", "已恢复最近快照，请重启相关 Codex 窗口。", parent=self)
        self.refresh()

    def remove_shared_skill(self) -> None:
        skill_name = self.maintenance_skill_var.get()
        if not skill_name:
            return
        affected = "、".join(profile.name for profile in self.profiles)
        if not messagebox.askyesno(
            "从所有账户移除共享技能",
            f"将从所有账户移除“{skill_name}”。\n受影响账户：{affected}\n\n最后快照会永久保留。是否继续？",
            parent=self,
        ):
            return
        if not messagebox.askyesno(
            "再次确认",
            f"确认从所有账户移除“{skill_name}”？同名入口会被移动到备份。",
            parent=self,
        ):
            return
        try:
            operation_id = self.service.remove_shared_skill(skill_name, self.profiles)
        except Exception as error:
            messagebox.showerror("移除失败", str(error), parent=self)
            return
        messagebox.showinfo(
            "已全局移除",
            f"技能已移至备份，最后快照已保留。\n操作编号：{operation_id}",
            parent=self,
        )
        self.refresh()

    def _selected_profile(self, *, show_warning: bool = True) -> Profile | None:
        selection = self.profile_tree.selection()
        if not selection:
            if show_warning:
                messagebox.showwarning("请选择账户", "请先在账户列表选择一个账户。", parent=self)
            return None
        return next((profile for profile in self.profiles if profile.id == selection[0]), None)
