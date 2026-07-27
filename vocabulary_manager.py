from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable
from uuid import uuid4

from config_manager import configure_ui_fonts
from learning_history import clear_learning_history, load_learning_state
from retrieve import export_vocabulary_by_tags
from vocabulary_store import (
    activate_profile,
    create_profile,
    delete_profile,
    ensure_registry,
    get_active_profile,
)
from vocabulary_tags import (
    ALLOWED_VOCABULARY_TAGS,
    VOCABULARY_TAG_LABELS,
    vocabulary_tag_label,
)


class VocabularyManagerDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        base_dir: Path | str,
        on_vocabulary_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.parent = parent
        self.base_dir = Path(base_dir)
        self.on_vocabulary_changed = on_vocabulary_changed
        self.font_family = configure_ui_fonts(self)
        self._closed = False
        self._busy = False
        self.profile_rows: dict[str, dict[str, object]] = {}

        self.title("管理词库与学习历史")
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        width = min(1040, max(820, screen_width - 120))
        height = min(760, max(620, screen_height - 140))
        self.geometry(f"{width}x{height}")
        self.minsize(800, 600)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._close)

        registry = ensure_registry(self.base_dir)
        default_source = Path(str(registry.get("last_source_file") or ""))
        if not default_source.is_file():
            fallback = self.base_dir / "stardict.csv"
            default_source = fallback if fallback.is_file() else Path()
        self.source_var = tk.StringVar(
            value=str(default_source) if str(default_source) not in {"", "."} else ""
        )
        self.name_var = tk.StringVar(value="")
        self.match_mode_var = tk.StringVar(value="any")
        self.status_var = tk.StringVar()
        self.tag_vars = {
            tag: tk.BooleanVar(value=tag == "gre") for tag in ALLOWED_VOCABULARY_TAGS
        }
        self.history_query_var = tk.StringVar()
        self.history_mastery_var = tk.StringVar(value="全部")

        self._build_ui()
        self._refresh_all()

    def _build_ui(self) -> None:
        outer = tk.Frame(self, padx=18, pady=16)
        outer.pack(fill="both", expand=True)
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(1, weight=1)

        header = tk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.grid_columnconfigure(0, weight=1)
        tk.Label(
            header,
            text="管理词库与学习历史",
            font=(self.font_family, 20, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            header,
            textvariable=self.status_var,
            fg="#596579",
            anchor="e",
        ).grid(row=0, column=1, sticky="e")

        notebook = ttk.Notebook(outer)
        notebook.grid(row=1, column=0, sticky="nsew")
        vocabulary_tab = tk.Frame(notebook, padx=12, pady=12)
        history_tab = tk.Frame(notebook, padx=12, pady=12)
        notebook.add(vocabulary_tab, text="词库")
        notebook.add(history_tab, text="学习历史")
        self._build_vocabulary_tab(vocabulary_tab)
        self._build_history_tab(history_tab)

        tk.Button(outer, text="关闭", command=self._close, width=10).grid(
            row=2, column=0, sticky="e", pady=(10, 0)
        )

    def _build_vocabulary_tab(self, tab: tk.Frame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        create_box = tk.LabelFrame(tab, text="新建词库", padx=12, pady=10)
        create_box.grid(row=0, column=0, sticky="ew")
        create_box.grid_columnconfigure(1, weight=1)

        tk.Label(create_box, text="词库名称").grid(
            row=0, column=0, sticky="w", padx=(0, 10), pady=5
        )
        tk.Entry(create_box, textvariable=self.name_var).grid(
            row=0, column=1, columnspan=3, sticky="ew", pady=5
        )
        tk.Label(create_box, text="stardict.csv").grid(
            row=1, column=0, sticky="w", padx=(0, 10), pady=5
        )
        tk.Entry(create_box, textvariable=self.source_var).grid(
            row=1, column=1, columnspan=2, sticky="ew", pady=5
        )
        tk.Button(create_box, text="浏览…", command=self._browse_source).grid(
            row=1, column=3, padx=(8, 0), pady=5
        )

        tk.Label(create_box, text="考试范围").grid(
            row=2, column=0, sticky="nw", padx=(0, 10), pady=(8, 5)
        )
        tags_frame = tk.Frame(create_box)
        tags_frame.grid(row=2, column=1, columnspan=3, sticky="ew", pady=(8, 5))
        for index, tag in enumerate(ALLOWED_VOCABULARY_TAGS):
            label = f"{VOCABULARY_TAG_LABELS[tag]} ({tag})"
            tk.Checkbutton(
                tags_frame,
                text=label,
                variable=self.tag_vars[tag],
                anchor="w",
            ).grid(row=index // 4, column=index % 4, sticky="w", padx=(0, 14), pady=3)

        tk.Label(create_box, text="组合方式").grid(
            row=3, column=0, sticky="w", padx=(0, 10), pady=5
        )
        mode_frame = tk.Frame(create_box)
        mode_frame.grid(row=3, column=1, columnspan=3, sticky="w", pady=5)
        tk.Radiobutton(
            mode_frame,
            text="包含任一所选范围",
            variable=self.match_mode_var,
            value="any",
        ).pack(side="left")
        tk.Radiobutton(
            mode_frame,
            text="同时属于全部所选范围",
            variable=self.match_mode_var,
            value="all",
        ).pack(side="left", padx=(14, 0))

        self.create_button = tk.Button(
            create_box,
            text="创建并设为当前词库",
            command=self._create_vocabulary,
            padx=16,
            pady=7,
        )
        self.create_button.grid(row=4, column=1, sticky="w", pady=(8, 2))
        tk.Label(
            create_box,
            text=(
                "仅允许与网页版相同的 8 个考试 tag。生成文件保留 tag 列；"
                "当前词库仍同步为 vocabulary.csv，以兼容旧版。"
            ),
            fg="#596579",
            justify="left",
            anchor="w",
            wraplength=760,
        ).grid(row=5, column=0, columnspan=4, sticky="ew", pady=(8, 0))

        list_box = tk.LabelFrame(tab, text="我的词库", padx=10, pady=10)
        list_box.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        list_box.grid_columnconfigure(0, weight=1)
        list_box.grid_rowconfigure(0, weight=1)
        columns = ("name", "count", "tags", "mode", "state")
        self.profile_tree = ttk.Treeview(
            list_box, columns=columns, show="headings", selectmode="browse"
        )
        headings = {
            "name": "名称",
            "count": "词数",
            "tags": "考试范围",
            "mode": "组合方式",
            "state": "状态",
        }
        widths = {"name": 180, "count": 70, "tags": 360, "mode": 100, "state": 90}
        for column in columns:
            self.profile_tree.heading(column, text=headings[column])
            self.profile_tree.column(column, width=widths[column], anchor="w")
        scrollbar = ttk.Scrollbar(list_box, command=self.profile_tree.yview)
        self.profile_tree.configure(yscrollcommand=scrollbar.set)
        self.profile_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        actions = tk.Frame(list_box)
        actions.grid(row=1, column=0, columnspan=2, sticky="e", pady=(8, 0))
        self.activate_button = tk.Button(
            actions, text="设为当前词库", command=self._activate_selected
        )
        self.activate_button.pack(side="left", padx=5)
        self.delete_profile_button = tk.Button(
            actions, text="删除词库", command=self._delete_selected_profile
        )
        self.delete_profile_button.pack(side="left", padx=5)

    def _build_history_tab(self, tab: tk.Frame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        filters = tk.Frame(tab)
        filters.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        filters.grid_columnconfigure(1, weight=1)
        tk.Label(filters, text="搜索").grid(row=0, column=0, padx=(0, 6))
        search_entry = tk.Entry(filters, textvariable=self.history_query_var)
        search_entry.grid(row=0, column=1, sticky="ew")
        tk.Label(filters, text="熟练度").grid(row=0, column=2, padx=(12, 6))
        mastery = ttk.Combobox(
            filters,
            textvariable=self.history_mastery_var,
            state="readonly",
            width=9,
            values=("全部", "1", "2", "3", "4", "5"),
        )
        mastery.grid(row=0, column=3)
        tk.Button(filters, text="筛选", command=self._refresh_history).grid(
            row=0, column=4, padx=(8, 0)
        )
        search_entry.bind("<Return>", lambda _event: self._refresh_history())

        columns = ("word", "mastery", "count", "scores", "last")
        self.history_tree = ttk.Treeview(tab, columns=columns, show="headings")
        headings = {
            "word": "单词",
            "mastery": "熟练度",
            "count": "学习次数",
            "scores": "最近评分",
            "last": "最近学习（UTC）",
        }
        widths = {"word": 220, "mastery": 80, "count": 90, "scores": 110, "last": 240}
        for column in columns:
            self.history_tree.heading(column, text=headings[column])
            self.history_tree.column(column, width=widths[column], anchor="w")
        scrollbar = ttk.Scrollbar(tab, command=self.history_tree.yview)
        self.history_tree.configure(yscrollcommand=scrollbar.set)
        self.history_tree.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")

        bottom = tk.Frame(tab)
        bottom.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        bottom.grid_columnconfigure(0, weight=1)
        self.history_status_var = tk.StringVar()
        tk.Label(bottom, textvariable=self.history_status_var, anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        self.clear_history_button = tk.Button(
            bottom, text="清空全部学习历史", command=self._clear_history
        )
        self.clear_history_button.grid(row=0, column=1, sticky="e")

    def _browse_source(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self,
            title="选择 ECDICT 的 stardict.csv",
            initialdir=str(self.base_dir),
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")],
        )
        if selected:
            self.source_var.set(selected)

    def _selected_tags(self) -> list[str]:
        return [tag for tag in ALLOWED_VOCABULARY_TAGS if self.tag_vars[tag].get()]

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        for button in (
            self.create_button,
            self.activate_button,
            self.delete_profile_button,
            self.clear_history_button,
        ):
            button.configure(state=state)
        if message:
            self.status_var.set(message)

    def _create_vocabulary(self) -> None:
        if self._busy:
            return
        source_text = self.source_var.get().strip()
        name = self.name_var.get().strip()
        tags = self._selected_tags()
        if not name:
            messagebox.showwarning("缺少名称", "请填写词库名称。", parent=self)
            return
        if not source_text:
            messagebox.showwarning(
                "未选择源文件", "请先选择 stardict.csv。", parent=self
            )
            return
        if not tags:
            messagebox.showwarning(
                "未选择考试范围", "请至少选择一个考试范围。", parent=self
            )
            return
        source_path = Path(source_text).expanduser()
        match_mode = self.match_mode_var.get()
        staging = self.base_dir / f".vocabulary.generated.{uuid4().hex}.csv"
        self._set_busy(True, "正在扫描 ECDICT 并创建词库……")
        result_queue: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)

        def worker() -> None:
            try:
                result = export_vocabulary_by_tags(
                    source_path,
                    staging,
                    tags,
                    match_all=match_mode == "all",
                )
                profile = create_profile(
                    self.base_dir,
                    name=name,
                    tags=tags,
                    match_mode=match_mode,
                    generated_file=staging,
                    word_count=int(result["exported_rows"]),
                    source_file=str(source_path.resolve()),
                    activate=True,
                )
                result_queue.put(("success", profile))
            except Exception as exc:
                try:
                    staging.unlink(missing_ok=True)
                except OSError:
                    pass
                result_queue.put(("failure", exc))

        self._start_worker(worker, result_queue, self._create_finished)

    def _start_worker(
        self,
        worker: Callable[[], None],
        result_queue: queue.Queue[tuple[str, object]],
        callback: Callable[[str, object], None],
    ) -> None:
        def poll() -> None:
            if self._closed or not self.winfo_exists():
                return
            try:
                status, value = result_queue.get_nowait()
            except queue.Empty:
                self.after(60, poll)
                return
            callback(status, value)

        threading.Thread(target=worker, daemon=True).start()
        self.after(60, poll)

    def _create_finished(self, status: str, value: object) -> None:
        self._set_busy(False)
        if status == "failure":
            self.status_var.set("词库创建失败。")
            exc = value if isinstance(value, Exception) else RuntimeError(str(value))
            messagebox.showerror(
                "词库创建失败", f"{type(exc).__name__}: {exc}", parent=self
            )
            return
        profile = value if isinstance(value, dict) else {}
        self.name_var.set("")
        self._refresh_all()
        messagebox.showinfo(
            "词库创建完成",
            f"已创建并启用“{profile.get('name', '')}”，共 {profile.get('word_count', 0)} 个词。",
            parent=self,
        )
        if self.on_vocabulary_changed:
            self.on_vocabulary_changed()

    def _selected_profile_id(self) -> str | None:
        selection = self.profile_tree.selection()
        return selection[0] if selection else None

    def _activate_selected(self) -> None:
        profile_id = self._selected_profile_id()
        if not profile_id:
            messagebox.showwarning("未选择词库", "请先选择一个词库。", parent=self)
            return
        try:
            profile = activate_profile(self.base_dir, profile_id)
        except (ValueError, FileNotFoundError, OSError) as exc:
            messagebox.showerror("切换失败", str(exc), parent=self)
            return
        self._refresh_profiles()
        messagebox.showinfo(
            "词库已切换", f"当前词库：{profile['name']}。", parent=self
        )
        if self.on_vocabulary_changed:
            self.on_vocabulary_changed()

    def _delete_selected_profile(self) -> None:
        profile_id = self._selected_profile_id()
        if not profile_id:
            messagebox.showwarning("未选择词库", "请先选择一个词库。", parent=self)
            return
        profile = self.profile_rows.get(profile_id, {})
        if not messagebox.askyesno(
            "删除词库",
            f"确定删除“{profile.get('name', '')}”吗？已有学习记录使用的词库不能删除。",
            parent=self,
        ):
            return
        try:
            delete_profile(self.base_dir, profile_id)
        except (ValueError, OSError) as exc:
            messagebox.showerror("删除失败", str(exc), parent=self)
            return
        self._refresh_all()
        if self.on_vocabulary_changed:
            self.on_vocabulary_changed()

    def _clear_history(self) -> None:
        if not messagebox.askyesno(
            "清空学习历史",
            "确定清空 learningHistory.csv 和 learningEvents.csv 吗？此操作无法撤销。",
            parent=self,
        ):
            return
        try:
            clear_learning_history(self.base_dir)
        except OSError as exc:
            messagebox.showerror("清空失败", str(exc), parent=self)
            return
        self._refresh_all()
        messagebox.showinfo("学习历史", "全部学习历史已清空。", parent=self)

    def _refresh_profiles(self) -> None:
        registry = ensure_registry(self.base_dir)
        active_id = registry.get("active_id")
        self.profile_rows = {
            str(profile["id"]): profile for profile in registry.get("profiles", [])
        }
        for item in self.profile_tree.get_children():
            self.profile_tree.delete(item)
        for profile in registry.get("profiles", []):
            tags = profile.get("tags") or []
            tag_text = "、".join(vocabulary_tag_label(tag) for tag in tags) or "旧版/自定义"
            mode = {
                "any": "任一范围",
                "all": "全部范围",
                "legacy": "旧版导入",
            }.get(str(profile.get("match_mode")), str(profile.get("match_mode")))
            state = "当前使用" if profile.get("id") == active_id else ""
            self.profile_tree.insert(
                "",
                "end",
                iid=str(profile["id"]),
                values=(
                    profile.get("name", ""),
                    profile.get("word_count", 0),
                    tag_text,
                    mode,
                    state,
                ),
            )
        active = get_active_profile(self.base_dir)
        if active:
            self.status_var.set(
                f"当前词库：{active['name']}（{active['word_count']} 词）"
            )
        else:
            self.status_var.set("尚未选择当前词库")

    def _refresh_history(self) -> None:
        records, _events, _dates = load_learning_state(self.base_dir)
        query = self.history_query_var.get().strip().casefold()
        mastery_text = self.history_mastery_var.get()
        mastery_filter = int(mastery_text) if mastery_text.isdigit() else None
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        filtered = []
        for record in records.values():
            if query and query not in record.word.casefold():
                continue
            if mastery_filter is not None and record.mastery_level != mastery_filter:
                continue
            filtered.append(record)
        filtered.sort(
            key=lambda record: (
                record.last_studied_at.timestamp() if record.last_studied_at else 0,
                record.word.casefold(),
            ),
            reverse=True,
        )
        for index, record in enumerate(filtered):
            scores = f"{record.last_first_score or '—'} → {record.last_second_score or '—'}"
            last = record.last_studied_at.isoformat(timespec="seconds") if record.last_studied_at else "—"
            self.history_tree.insert(
                "",
                "end",
                iid=f"history-{index}",
                values=(
                    record.word,
                    record.mastery_level,
                    record.study_count,
                    scores,
                    last,
                ),
            )
        self.history_status_var.set(
            f"显示 {len(filtered)} / {len(records)} 个已学习单词。"
        )

    def _refresh_all(self) -> None:
        self._refresh_profiles()
        self._refresh_history()

    def _close(self) -> None:
        if self._busy:
            messagebox.showwarning(
                "正在创建词库", "词库仍在生成中，请完成后再关闭窗口。", parent=self
            )
            return
        self._closed = True
        self.destroy()


def open_vocabulary_manager(
    parent: tk.Misc,
    base_dir: Path | str,
    on_vocabulary_changed: Callable[[], None] | None = None,
) -> VocabularyManagerDialog:
    return VocabularyManagerDialog(parent, base_dir, on_vocabulary_changed)
