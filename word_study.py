from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import Any

from config_manager import configure_ui_fonts

RATING_TEXT = {
    1: "完全不认识",
    2: "见过，但不知道意思",
    3: "需要思考较久才能想起",
    4: "知道含义，并能联想到同类词",
    5: "一下子就知道意思",
}


def _display_value(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("\\n", "\n").strip() or "—"


class WordStudyDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        words: list[dict[str, str]],
        config: dict[str, Any],
        pass_name: str,
    ) -> None:
        super().__init__(parent)
        self.words = words
        self.config_data = config
        self.font_family = configure_ui_fonts(self)
        self.pass_name = pass_name
        self.index = 0
        self.phase = "pre"
        self.pre_score: int | None = None
        self.scores: dict[str, int] = {}
        self.completed = False

        self.title(f"词义学习｜{pass_name}")
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        width = min(920, max(740, screen_width - 140))
        height = min(720, max(560, screen_height - 150))
        self.geometry(f"{width}x{height}")
        self.minsize(720, 520)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._try_abort)

        self._build_ui()
        self._bind_shortcuts()
        self._load_current_word()
        self.after_idle(self.focus_force)

    def _build_ui(self) -> None:
        bg = self.config_data["background_color"]
        fg = self.config_data["text_color"]
        button_bg = self.config_data["button_color"]
        border = self.config_data["border_color"]

        self.configure(bg=bg)
        top = tk.Frame(self, bg=bg, padx=22, pady=14)
        top.pack(fill="x")

        self.progress_label = tk.Label(top, bg=bg, fg=fg, font=(self.font_family, 11))
        self.progress_label.pack(anchor="w")
        self.word_label = tk.Label(
            top, bg=bg, fg=fg, font=(self.font_family, 28, "bold"), pady=6
        )
        self.word_label.pack()
        self.pos_label = tk.Label(top, bg=bg, fg=fg, font=(self.font_family, 13))
        self.pos_label.pack()
        self.instruction_label = tk.Label(
            top,
            bg=bg,
            fg=fg,
            font=(self.font_family, 12),
            justify="center",
            wraplength=820,
            pady=7,
        )
        self.instruction_label.pack()

        rating_border = tk.Frame(self, bg=border, padx=1, pady=1)
        rating_border.pack(fill="x", padx=22, pady=(0, 10))
        self.rating_frame = tk.Frame(rating_border, bg=bg, padx=10, pady=8)
        self.rating_frame.pack(fill="x")
        self.rating_var = tk.IntVar(value=0)
        for score in range(1, 6):
            radio = tk.Radiobutton(
                self.rating_frame,
                text=f"{score}：{RATING_TEXT[score]}",
                variable=self.rating_var,
                value=score,
                bg=bg,
                fg=fg,
                activebackground=bg,
                activeforeground=fg,
                selectcolor=button_bg,
                anchor="w",
                takefocus=False,
            )
            radio.pack(fill="x", anchor="w")

        detail_border = tk.Frame(self, bg=border, padx=1, pady=1)
        detail_border.pack(fill="both", expand=True, padx=22, pady=(0, 10))
        self.detail_container = tk.Frame(detail_border, bg=bg)
        self.detail_container.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(
            self.detail_container, bg=bg, highlightthickness=0, borderwidth=0
        )
        self.scrollbar = tk.Scrollbar(
            self.detail_container, orient="vertical", command=self.canvas.yview
        )
        self.detail_frame = tk.Frame(self.canvas, bg=bg)
        self.detail_window = self.canvas.create_window(
            (0, 0), window=self.detail_frame, anchor="nw"
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.detail_frame.bind("<Configure>", self._update_scroll_region)
        self.canvas.bind("<Configure>", self._resize_detail_window)

        button_border = tk.Frame(self, bg=border, padx=1, pady=1)
        button_border.pack(pady=(3, 14))
        self.action_button = tk.Button(
            button_border,
            text="我已评分，查看词义（空格）",
            command=self._on_action,
            bg=button_bg,
            fg=fg,
            activebackground=button_bg,
            activeforeground=fg,
            relief="flat",
            padx=24,
            pady=9,
            takefocus=False,
            font=(self.font_family, 11),
        )
        self.action_button.pack()

    def _bind_shortcuts(self) -> None:
        for score in range(1, 6):
            self.bind(
                f"<KeyPress-{score}>",
                lambda _event, value=score: self._select_score(value),
            )
            self.bind(
                f"<KeyPress-KP_{score}>",
                lambda _event, value=score: self._select_score(value),
            )
        self.bind("<KeyPress-space>", self._press_primary_button)

    def _select_score(self, score: int) -> str:
        self.rating_var.set(score)
        return "break"

    def _press_primary_button(self, event: tk.Event) -> str | None:
        # A focused Tk button already handles Space itself; avoid a double invoke.
        if event.widget is self.action_button:
            return None
        if str(self.action_button.cget("state")) != "disabled":
            self.action_button.invoke()
        return "break"

    def _update_scroll_region(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize_detail_window(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.detail_window, width=event.width)

    def _clear_details(self) -> None:
        for child in self.detail_frame.winfo_children():
            child.destroy()
        self.canvas.yview_moveto(0)

    def _load_current_word(self) -> None:
        self.phase = "pre"
        self.pre_score = None
        self.rating_var.set(0)
        self._clear_details()

        item = self.words[self.index]
        word = item.get("word", "")
        pos = _display_value(item.get("pos", ""))
        self.progress_label.configure(
            text=f"{self.pass_name}｜第 {self.index + 1} / {len(self.words)} 个词"
        )
        self.word_label.configure(text=word)
        self.pos_label.configure(text=f"词性：{pos}")
        self.instruction_label.configure(
            text="按数字键 1～5 或点击选项评分，然后按空格确认。"
        )
        self.action_button.configure(text="我已评分，查看词义（空格）")

        placeholder = tk.Label(
            self.detail_frame,
            text="第一次评分确认后，这里会展示该词的全部 CSV 信息。",
            bg=self.config_data["background_color"],
            fg=self.config_data["text_color"],
            font=(self.font_family, 11),
            pady=26,
        )
        placeholder.pack(fill="x")
        self.after_idle(self.focus_force)

    def _show_details(self) -> None:
        self._clear_details()
        bg = self.config_data["background_color"]
        fg = self.config_data["text_color"]
        border = self.config_data["border_color"]
        item = self.words[self.index]

        for row_index, (field, value) in enumerate(item.items()):
            row = tk.Frame(self.detail_frame, bg=border)
            row.pack(fill="x", padx=8, pady=(8 if row_index == 0 else 0, 1))

            field_label = tk.Label(
                row,
                text=field,
                width=15,
                anchor="nw",
                justify="left",
                bg=bg,
                fg=fg,
                font=(self.font_family, 10, "bold"),
                padx=8,
                pady=7,
            )
            field_label.pack(side="left", fill="y", padx=(1, 0), pady=1)

            value_label = tk.Label(
                row,
                text=_display_value(value),
                anchor="nw",
                justify="left",
                wraplength=650,
                bg=bg,
                fg=fg,
                padx=10,
                pady=7,
            )
            value_label.pack(side="left", fill="both", expand=True, padx=1, pady=1)

    def _on_action(self) -> None:
        if self.rating_var.get() not in range(1, 6):
            messagebox.showwarning(
                "请选择评分",
                "请先按数字键 1 至 5，或点击一个熟练程度。",
                parent=self,
            )
            return

        if self.phase == "pre":
            self.pre_score = self.rating_var.get()
            self._show_details()
            self.rating_var.set(0)
            self.phase = "post"
            self.instruction_label.configure(
                text="阅读全部信息后再次按 1～5 评分，再按空格确认。"
            )
            final_word = self.index == len(self.words) - 1
            self.action_button.configure(
                text=(
                    "我已评分，完成（空格）"
                    if final_word
                    else "我已评分，下一词（空格）"
                )
            )
            self.after_idle(self.focus_force)
            return

        score = self.rating_var.get()
        word = self.words[self.index].get("word", "")
        self.scores[word] = score

        if self.index == len(self.words) - 1:
            self.completed = True
            self.destroy()
        else:
            self.index += 1
            self._load_current_word()

    def _try_abort(self) -> None:
        if messagebox.askyesno(
            "中止本轮学习",
            "关闭窗口会中止本轮学习，并且不会更新学习历史。确定关闭吗？",
            parent=self,
        ):
            self.completed = False
            self.destroy()


def run_word_study(
    parent: tk.Misc,
    words: list[dict[str, str]],
    config: dict[str, Any],
    pass_name: str,
) -> dict[str, int] | None:
    dialog = WordStudyDialog(parent, words, config, pass_name)
    parent.wait_window(dialog)
    return dialog.scores if dialog.completed else None
