from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .models import Profile
from .skill_catalog import is_junction
from .skill_models import MigrationPreview, SkillPlan, SkillState
from .skill_service import (
    RunningProfilesError,
    SensitiveSkillError,
    SkillConflictError,
    SkillService,
    SkillSharingError,
)


FONT_FAMILY = "Microsoft YaHei UI"
STATE_TEXT = {
    SkillState.SHARED: "已共享",
    SkillState.IDENTICAL: "内容相同，可合并",
    SkillState.UNIQUE: "独有技能，可导入",
    SkillState.CONFLICT: "版本冲突",
    SkillState.INVALID: "无效技能目录",
    SkillState.BROKEN: "入口损坏",
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
        self.status_var = tk.StringVar(value="正在扫描技能目录…")
        self.conflict_var = tk.StringVar()

        self.title("共享技能")
        self.geometry("980x700")
        self.minsize(780, 560)
        self.transient(parent)
        self._build()
        self.after_idle(self.refresh)

    def _build(self) -> None:
        container = ttk.Frame(self, padding=24)
        container.pack(fill="both", expand=True)
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(2, weight=3)
        container.grid_rowconfigure(5, weight=2)

        title = ttk.Frame(container)
        title.grid(row=0, column=0, sticky="ew")
        title.grid_columnconfigure(0, weight=1)
        ttk.Label(title, text="共享技能库", font=(FONT_FAMILY, 20, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(title, text="刷新扫描", command=self.refresh).grid(row=0, column=1)
        ttk.Label(
            container,
            textvariable=self.status_var,
            foreground="#6E6E73",
            font=(FONT_FAMILY, 9),
        ).grid(row=1, column=0, sticky="w", pady=(5, 12))

        self.skill_tree = ttk.Treeview(
            container,
            columns=("state", "source", "locations"),
            show="tree headings",
            selectmode="browse",
        )
        self.skill_tree.heading("#0", text="技能")
        self.skill_tree.heading("state", text="状态")
        self.skill_tree.heading("source", text="拟采用版本")
        self.skill_tree.heading("locations", text="发现位置")
        self.skill_tree.column("#0", width=230)
        self.skill_tree.column("state", width=145)
        self.skill_tree.column("source", width=170)
        self.skill_tree.column("locations", width=110, anchor="center")
        self.skill_tree.grid(row=2, column=0, sticky="nsew")
        self.skill_tree.bind("<<TreeviewSelect>>", self._on_skill_selected)

        conflict_row = ttk.Frame(container)
        conflict_row.grid(row=3, column=0, sticky="ew", pady=(10, 16))
        conflict_row.grid_columnconfigure(1, weight=1)
        ttk.Label(conflict_row, text="冲突版本：").grid(row=0, column=0, sticky="w")
        self.conflict_combo = ttk.Combobox(
            conflict_row,
            textvariable=self.conflict_var,
            state="disabled",
        )
        self.conflict_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.conflict_combo.bind("<<ComboboxSelected>>", self._on_conflict_choice)

        ttk.Label(container, text="账户共享状态", font=(FONT_FAMILY, 11, "bold")).grid(
            row=4, column=0, sticky="w", pady=(0, 8)
        )
        self.profile_tree = ttk.Treeview(
            container,
            columns=("enabled", "bindings", "issues"),
            show="tree headings",
            selectmode="browse",
            height=6,
        )
        self.profile_tree.heading("#0", text="账户")
        self.profile_tree.heading("enabled", text="共享策略")
        self.profile_tree.heading("bindings", text="共享技能数")
        self.profile_tree.heading("issues", text="异常")
        self.profile_tree.column("#0", width=260)
        self.profile_tree.column("enabled", width=130)
        self.profile_tree.column("bindings", width=110, anchor="center")
        self.profile_tree.column("issues", width=80, anchor="center")
        self.profile_tree.grid(row=5, column=0, sticky="nsew")

        actions = ttk.Frame(container)
        actions.grid(row=6, column=0, sticky="ew", pady=(16, 0))
        ttk.Button(actions, text="执行首次迁移", command=self.apply_migration).pack(side="left")
        ttk.Button(actions, text="切换账户共享", command=self.toggle_profile).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(actions, text="切换所选技能", command=self.toggle_skill).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(actions, text="恢复最近快照", command=self.restore_snapshot).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(actions, text="全局移除", command=self.remove_shared_skill).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(actions, text="关闭", command=self.destroy).pack(side="right")

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
        self.skill_tree.delete(*self.skill_tree.get_children())
        for plan in preview.plans:
            recommended = next(
                (
                    source
                    for source in plan.sources
                    if source.profile_id == plan.recommended_profile_id
                ),
                None,
            )
            if recommended and not plan.requires_choice:
                self.selections[plan.name] = recommended.profile_id
            self.skill_tree.insert(
                "",
                "end",
                iid=plan.name,
                text=plan.name,
                values=(
                    STATE_TEXT[plan.state],
                    (
                        f"建议：{recommended.profile_name}（仍需选择）"
                        if recommended and plan.requires_choice
                        else recommended.profile_name
                        if recommended
                        else "需要选择"
                    ),
                    len(plan.sources),
                ),
            )
        self._refresh_profiles()
        conflicts = len(preview.conflicts)
        invalid = sum(1 for plan in preview.plans if plan.state is SkillState.INVALID)
        self.status_var.set(
            f"发现 {len(preview.plans)} 个技能 · {conflicts} 个冲突 · "
            f"{invalid} 个无效目录 · {self.service.snapshot_count()} 个历史快照"
        )

    def _refresh_profiles(self) -> None:
        self.profile_tree.delete(*self.profile_tree.get_children())
        for profile in self.profiles:
            enabled, bindings, issues = self.service.status_for_profile(profile)
            self.profile_tree.insert(
                "",
                "end",
                iid=profile.id,
                text=profile.name,
                values=("已开启" if enabled else "已关闭", bindings, issues),
            )

    def _on_skill_selected(self, _event: object = None) -> None:
        selection = self.skill_tree.selection()
        if not selection:
            return
        plan = self.plans[selection[0]]
        if not plan.requires_choice:
            self.conflict_combo.configure(state="disabled", values=())
            self.conflict_var.set("")
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

    def _on_conflict_choice(self, _event: object = None) -> None:
        selection = self.skill_tree.selection()
        if not selection:
            return
        plan = self.plans[selection[0]]
        profile_id = self.source_display_to_id.get(self.conflict_var.get())
        if profile_id:
            self.selections[plan.name] = profile_id
            source = next(item for item in plan.sources if item.profile_id == profile_id)
            values = list(self.skill_tree.item(plan.name, "values"))
            values[1] = source.profile_name
            self.skill_tree.item(plan.name, values=values)

    def apply_migration(self) -> None:
        if self.preview_data is None:
            return
        unresolved = [
            plan.name
            for plan in self.preview_data.conflicts
            if plan.name not in self.selections
        ]
        if unresolved:
            messagebox.showwarning(
                "仍有冲突",
                "请先为以下技能选择版本：\n" + "\n".join(unresolved),
                parent=self,
            )
            return
        if not messagebox.askyesno(
            "确认首次迁移",
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
            "迁移完成",
            f"共享技能迁移已完成。\n操作编号：{operation_id}\n相关 Codex 窗口重新启动后生效。",
            parent=self,
        )
        self.refresh()

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
        action = "关闭" if enabled else "开启"
        if not messagebox.askyesno(
            f"{action}账户共享",
            (
                f"为“{profile.name}”{action}共享技能？\n\n"
                + ("所有共享技能会复制为独立副本，不会删除内容。" if enabled else "账户中的冲突技能会阻止操作。")
            ),
            parent=self,
        ):
            return
        try:
            self.service.set_profile_sharing(profile, not enabled)
        except Exception as error:
            messagebox.showerror("操作失败", str(error), parent=self)
            return
        self.refresh()

    def toggle_skill(self) -> None:
        profile = self._selected_profile()
        skill_name = self._selected_skill_name()
        if profile is None or skill_name is None:
            return
        target = profile.codex_home / "skills" / skill_name
        enabled = is_junction(target)
        action = "解除共享并保留副本" if enabled else "启用共享"
        if not messagebox.askyesno(
            "切换技能共享",
            f"账户：{profile.name}\n技能：{skill_name}\n操作：{action}\n\n是否继续？",
            parent=self,
        ):
            return
        try:
            self.service.set_skill_binding(profile, skill_name, not enabled)
        except Exception as error:
            messagebox.showerror("操作失败", str(error), parent=self)
            return
        self.refresh()

    def restore_snapshot(self) -> None:
        skill_name = self._selected_skill_name()
        if skill_name is None:
            return
        if not (self.service.paths.shared_skills / skill_name).is_dir():
            messagebox.showwarning("尚未共享", "所选技能还不在中央共享库中。", parent=self)
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
        skill_name = self._selected_skill_name()
        if skill_name is None:
            return
        if not (self.service.paths.shared_skills / skill_name).is_dir():
            messagebox.showwarning("尚未共享", "所选技能还不在中央共享库中。", parent=self)
            return
        affected = "、".join(profile.name for profile in self.profiles)
        first = messagebox.askyesno(
            "全局移除共享技能",
            f"将从所有账户移除“{skill_name}”。\n受影响账户：{affected}\n\n最后快照会永久保留。是否继续？",
            parent=self,
        )
        if not first:
            return
        if not messagebox.askyesno(
            "再次确认",
            f"确认全局移除“{skill_name}”？此操作会移动所有账户中的同名入口。",
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

    def _selected_profile(self) -> Profile | None:
        selection = self.profile_tree.selection()
        if not selection:
            messagebox.showwarning("请选择账户", "请先在账户列表选择一个账户。", parent=self)
            return None
        return next((profile for profile in self.profiles if profile.id == selection[0]), None)

    def _selected_skill_name(self) -> str | None:
        selection = self.skill_tree.selection()
        if not selection:
            messagebox.showwarning("请选择技能", "请先在技能列表选择一个技能。", parent=self)
            return None
        return selection[0]
