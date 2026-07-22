from __future__ import annotations

import csv
import queue
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

from config_manager import configure_ui_fonts
from retrieve import export_vocabulary_by_tags, parse_tags

HISTORY_HEADERS = ["单词", "熟练程度"]


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
        self.vocabulary_path = self.base_dir / "vocabulary.csv"
        self.history_path = self.base_dir / "learningHistory.csv"
        self.on_vocabulary_changed = on_vocabulary_changed
        self.font_family = configure_ui_fonts(self)
        self._closed = False
        self._busy = False

        self.title("管理词库和学习历史")
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        width = min(800, max(680, screen_width - 180))
        height = min(590, max(520, screen_height - 180))
        self.geometry(f"{width}x{height}")
        self.minsize(660, 500)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._close)

        default_source = self.base_dir / "stardict.csv"
        self.source_var = tk.StringVar(
            value=str(default_source) if default_source.exists() else ""
        )
        self.tags_var = tk.StringVar(value="gre")
        self.match_mode_var = tk.StringVar(value="any")
        self.status_var = tk.StringVar()

        self._build_ui()
        self._refresh_status()

    def _build_ui(self) -> None:
        frame = tk.Frame(self, padx=22, pady=20)
        frame.pack(fill="both", expand=True)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        tk.Label(
            frame,
            text="管理词库和学习历史",
            font=(self.font_family, 21, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 14))

        source_box = tk.LabelFrame(
            frame,
            text="从 ECDICT 的 stardict.csv 按 tag 生成并切换词库",
            padx=14,
            pady=12,
        )
        source_box.grid(row=1, column=0, sticky="nsew")
        source_box.grid_columnconfigure(1, weight=1)

        tk.Label(source_box, text="stardict.csv").grid(
            row=0, column=0, sticky="w", padx=(0, 10), pady=7
        )
        tk.Entry(source_box, textvariable=self.source_var).grid(
            row=0, column=1, sticky="ew", pady=7
        )
        tk.Button(source_box, text="浏览…", command=self._browse_source).grid(
            row=0, column=2, padx=(8, 0), pady=7
        )

        tk.Label(source_box, text="tag").grid(
            row=1, column=0, sticky="w", padx=(0, 10), pady=7
        )
        tag_entry = tk.Entry(source_box, textvariable=self.tags_var)
        tag_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=7)

        tk.Label(
            source_box,
            text="多个 tag 可用空格、逗号或分号分隔，例如：gre ielts toefl",
            fg="#555555",
            anchor="w",
        ).grid(row=2, column=1, columnspan=2, sticky="ew", pady=(0, 7))

        mode_frame = tk.Frame(source_box)
        mode_frame.grid(row=3, column=1, columnspan=2, sticky="w", pady=5)
        tk.Radiobutton(
            mode_frame,
            text="匹配任意一个 tag（推荐）",
            variable=self.match_mode_var,
            value="any",
        ).pack(side="left", padx=(0, 18))
        tk.Radiobutton(
            mode_frame,
            text="必须同时具有全部 tag",
            variable=self.match_mode_var,
            value="all",
        ).pack(side="left")

        self.switch_button = tk.Button(
            source_box,
            text="按标签生成并切换词库",
            command=self._switch_vocabulary,
            padx=18,
            pady=8,
        )
        self.switch_button.grid(row=4, column=1, sticky="w", pady=(13, 7))

        tk.Label(
            source_box,
            text=(
                "切换时会把当前 vocabulary.csv 备份为 vocabulary.previous.csv。"
                "学习历史不会自动删除；历史中不属于新词库的单词不会参与抽取。"
            ),
            fg="#555555",
            justify="left",
            anchor="w",
            wraplength=690,
        ).grid(row=5, column=0, columnspan=3, sticky="ew", pady=(8, 0))

        history_box = tk.LabelFrame(frame, text="学习历史", padx=14, pady=12)
        history_box.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        history_box.grid_columnconfigure(0, weight=1)
        tk.Label(
            history_box,
            text="删除后，所有单词都会重新按照未学习状态开始。",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        self.delete_button = tk.Button(
            history_box,
            text="删除学习历史",
            command=self._delete_history,
            padx=16,
            pady=6,
        )
        self.delete_button.grid(row=0, column=1, padx=(12, 0))

        status_frame = tk.Frame(frame)
        status_frame.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        status_frame.grid_columnconfigure(0, weight=1)
        tk.Label(
            status_frame,
            textvariable=self.status_var,
            justify="left",
            anchor="w",
            wraplength=700,
        ).grid(row=0, column=0, sticky="ew")
        tk.Button(status_frame, text="关闭", command=self._close).grid(
            row=0, column=1, padx=(12, 0)
        )

        tag_entry.focus_set()

    def _browse_source(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self,
            title="选择 ECDICT 的 stardict.csv",
            initialdir=str(self.base_dir),
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")],
        )
        if selected:
            self.source_var.set(selected)

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.switch_button.configure(state=state)
        self.delete_button.configure(state=state)
        if message:
            self.status_var.set(message)

    def _switch_vocabulary(self) -> None:
        if self._busy:
            return
        source_text = self.source_var.get().strip()
        tags = parse_tags(self.tags_var.get())
        if not source_text:
            messagebox.showwarning(
                "未选择源文件",
                "请先选择从 stardict.7z 解压得到的 stardict.csv。",
                parent=self,
            )
            return
        if not tags:
            messagebox.showwarning(
                "未填写 tag",
                "请至少输入一个 tag，例如 gre。",
                parent=self,
            )
            return

        source_path = Path(source_text).expanduser()
        match_all = self.match_mode_var.get() == "all"
        staging_path = self.base_dir / ".vocabulary.generated.csv"
        self._set_busy(True, "正在扫描大型词库并生成 vocabulary.csv，请勿关闭窗口……")

        result_queue: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)

        def worker() -> None:
            try:
                result = export_vocabulary_by_tags(
                    source_path,
                    staging_path,
                    tags,
                    match_all=match_all,
                )
                backup_path = self.base_dir / "vocabulary.previous.csv"
                if self.vocabulary_path.exists():
                    shutil.copy2(self.vocabulary_path, backup_path)
                staging_path.replace(self.vocabulary_path)
            except Exception as exc:
                try:
                    staging_path.unlink(missing_ok=True)
                except OSError:
                    pass
                result_queue.put(("failure", exc))
            else:
                result_queue.put(("success", result))

        def poll_result() -> None:
            if self._closed or not self.winfo_exists():
                return
            try:
                status, value = result_queue.get_nowait()
            except queue.Empty:
                self.after(50, poll_result)
                return
            if status == "success":
                self._switch_succeeded(value)
            else:
                self._switch_failed(value)

        threading.Thread(target=worker, daemon=True).start()
        self.after(50, poll_result)

    def _switch_succeeded(self, result: dict[str, object]) -> None:
        self._set_busy(False)
        count = int(result.get("exported_rows", 0))
        tags = ", ".join(str(tag) for tag in result.get("tags", []))
        mode = "全部标签" if result.get("match_mode") == "all" else "任一标签"
        self.status_var.set(
            f"当前词库：vocabulary.csv，共 {count} 个词；tag：{tags}；模式：{mode}。"
        )
        messagebox.showinfo(
            "词库切换完成",
            f"已生成并切换到新词库，共 {count} 个不重复词条。\n\n"
            "原词库已备份为 vocabulary.previous.csv。",
            parent=self,
        )
        if self.on_vocabulary_changed:
            self.on_vocabulary_changed()

    def _switch_failed(self, exc: Exception) -> None:
        self._set_busy(False, "词库切换失败。")
        messagebox.showerror(
            "词库切换失败",
            f"{type(exc).__name__}: {exc}",
            parent=self,
        )

    def _delete_history(self) -> None:
        if self._busy:
            return
        confirmed = messagebox.askyesno(
            "删除学习历史",
            "确定删除全部学习历史吗？此操作无法撤销。",
            parent=self,
        )
        if not confirmed:
            return

        temp_path = self.history_path.with_name(self.history_path.name + ".tmp")
        try:
            with temp_path.open("w", encoding="utf-8-sig", newline="") as file:
                csv.DictWriter(file, fieldnames=HISTORY_HEADERS).writeheader()
            temp_path.replace(self.history_path)
        except OSError as exc:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            messagebox.showerror(
                "删除失败",
                f"无法重置 learningHistory.csv：{exc}",
                parent=self,
            )
            return

        self._refresh_status()
        messagebox.showinfo("学习历史", "学习历史已删除。", parent=self)

    def _refresh_status(self) -> None:
        vocabulary_status = (
            "已存在" if self.vocabulary_path.is_file() else "尚未生成"
        )
        history_status = "已存在" if self.history_path.is_file() else "尚未创建"
        self.status_var.set(
            f"vocabulary.csv：{vocabulary_status}｜learningHistory.csv：{history_status}"
        )

    def _close(self) -> None:
        if self._busy:
            messagebox.showwarning(
                "正在生成词库",
                "词库仍在生成中，请完成后再关闭窗口。",
                parent=self,
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
