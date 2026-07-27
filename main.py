from __future__ import annotations

import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox
from typing import Any

from config_manager import (
    configure_ui_fonts,
    get_missing_ai_settings,
    load_config,
    open_settings,
    save_config,
)
from learning_flow import LearningDataError, run_learning_round
from vocabulary_manager import open_vocabulary_manager
from vocabulary_store import active_profile_summary, ensure_registry

BASE_DIR = Path(__file__).resolve().parent
AUTHOR_NAME = "ZhuinZ"
AUTHOR_URL = "https://github.com/ZhuinZ"
ECDICT_URL = "https://github.com/skywind3000/ECDICT"
SYSTEM_NAME = "VITAL"
SYSTEM_FULL_NAME = "Vocabulary-Intelligence-and-Training-for-Adaptive-Learning"
SYSTEM_CHINESE_NAME = "词汇智能与自适应训练系统"
VERSION = "Desktop v1.4.2"


class MainApplication:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.config_data = load_config(BASE_DIR)
        ensure_registry(BASE_DIR)
        self.font_family = configure_ui_fonts(self.root)
        self.root.title(f"{SYSTEM_NAME} · {SYSTEM_CHINESE_NAME}")
        self.root.geometry("850x650")
        self.root.minsize(720, 560)
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)
        self._build_ui()
        if not bool(self.config_data.get("first_run_guide_shown", False)):
            self.root.after(350, lambda: self._show_ecdict_guide(first_run=True))

    def _build_ui(self) -> None:
        for child in self.root.winfo_children():
            child.destroy()

        bg = self.config_data["background_color"]
        fg = self.config_data["text_color"]
        button_bg = self.config_data["button_color"]
        border = self.config_data["border_color"]
        self.root.configure(bg=bg)

        main = tk.Frame(self.root, bg=bg, padx=38, pady=28)
        main.pack(fill="both", expand=True)

        tk.Label(
            main,
            text=SYSTEM_NAME,
            bg=bg,
            fg=fg,
            font=(self.font_family, 34, "bold"),
        ).pack(pady=(4, 0))
        tk.Label(
            main,
            text=SYSTEM_FULL_NAME,
            bg=bg,
            fg=fg,
            font=(self.font_family, 11),
        ).pack(pady=(2, 0))
        tk.Label(
            main,
            text=SYSTEM_CHINESE_NAME,
            bg=bg,
            fg=fg,
            font=(self.font_family, 15, "bold"),
        ).pack(pady=(2, 12))

        banner = tk.Frame(main, bg="#e8eef9", padx=16, pady=12)
        banner.pack(fill="x", pady=(0, 14))
        tk.Label(
            banner,
            text="AI 辅助阅读 · 个体化遗忘建模 · 自适应新词配额",
            bg="#e8eef9",
            fg="#172033",
            font=(self.font_family, 12, "bold"),
        ).pack()
        tk.Label(
            banner,
            text=(
                "系统会严格区分绝对新词与低分旧词，并优先安排容易遗忘、需要巩固、"
                "难度合适且跨考试范围更通用的词。"
            ),
            bg="#e8eef9",
            fg="#3d4b63",
            wraplength=720,
            justify="center",
        ).pack(pady=(4, 0))

        mode = "智能调节" if self.config_data.get("new_word_mode") == "adaptive" else "固定数量"
        summary = (
            f"每轮 {self.config_data['words_per_round']} 个词 · 新词基准 "
            f"{self.config_data['new_words_per_round']} 个 · {mode}"
        )
        tk.Label(
            main,
            text=summary,
            bg=bg,
            fg=fg,
            font=(self.font_family, 11),
        ).pack(pady=(0, 6))
        self.vocabulary_status = tk.StringVar(value=active_profile_summary(BASE_DIR))
        tk.Label(
            main,
            textvariable=self.vocabulary_status,
            bg=bg,
            fg="#596579",
            font=(self.font_family, 10),
            wraplength=720,
            justify="center",
        ).pack(pady=(0, 12))

        buttons = tk.Frame(main, bg=bg)
        buttons.pack(expand=True)
        self.learn_button = self._bordered_button(
            buttons,
            text="开始一轮自适应学习",
            command=self._start_learning,
            width=26,
            bg=button_bg,
            fg=fg,
            border=border,
        )
        self.learn_button.master.pack(pady=7)
        manage_button = self._bordered_button(
            buttons,
            text="管理词库与学习历史",
            command=self._open_vocabulary_manager,
            width=26,
            bg=button_bg,
            fg=fg,
            border=border,
        )
        manage_button.master.pack(pady=7)
        settings_button = self._bordered_button(
            buttons,
            text="学习与 AI 设置",
            command=self._open_settings,
            width=26,
            bg=button_bg,
            fg=fg,
            border=border,
        )
        settings_button.master.pack(pady=7)

        footer = tk.Frame(self.root, bg=bg, padx=14, pady=10)
        footer.place(relx=1.0, rely=1.0, anchor="se")
        tk.Label(
            footer,
            text=VERSION + " · Developer ",
            bg=bg,
            fg=fg,
            font=(self.font_family, 9),
        ).pack(side="left")
        author = tk.Label(
            footer,
            text=AUTHOR_NAME,
            bg=bg,
            fg=fg,
            font=(self.font_family, 9, "underline"),
            cursor="hand2",
        )
        author.pack(side="left")
        author.bind("<Button-1>", lambda _event: webbrowser.open(AUTHOR_URL))
        tk.Label(footer, text=" · ", bg=bg, fg=fg).pack(side="left")
        download = tk.Label(
            footer,
            text="获取 ECDICT 词库",
            bg=bg,
            fg=fg,
            font=(self.font_family, 9, "underline"),
            cursor="hand2",
        )
        download.pack(side="left")
        download.bind(
            "<Button-1>", lambda _event: self._show_ecdict_guide(first_run=False)
        )

    def _bordered_button(
        self,
        parent: tk.Misc,
        *,
        text: str,
        command: Any,
        width: int,
        bg: str,
        fg: str,
        border: str,
    ) -> tk.Button:
        border_frame = tk.Frame(parent, bg=border, padx=1, pady=1)
        button = tk.Button(
            border_frame,
            text=text,
            command=command,
            width=width,
            bg=bg,
            fg=fg,
            activebackground=bg,
            activeforeground=fg,
            relief="flat",
            padx=12,
            pady=10,
            font=(self.font_family, 12),
        )
        button.pack()
        return button

    def _show_ecdict_guide(self, *, first_run: bool) -> None:
        if first_run:
            self.config_data["first_run_guide_shown"] = True
            self.config_data = save_config(self.config_data, BASE_DIR)
        title = "首次使用：获取 ECDICT" if first_run else "获取 ECDICT"
        message = (
            "VITAL 不会自动下载大型词典。请按以下步骤准备 stardict.csv：\n\n"
            "1. 打开 ECDICT GitHub 项目。\n"
            "2. 下载 stardict.7z，或下载整个项目后找到该文件。\n"
            "3. 使用 7-Zip 等工具解压，取得 stardict.csv。\n"
            "4. 回到 VITAL，打开“管理词库与学习历史”。\n"
            "5. 填写词库名称，选择中考/高考/四六级/考研/雅思/托福/GRE 范围。\n"
            "6. 选择任一范围或全部范围，然后创建并启用词库。\n\n"
            "是否现在打开 ECDICT GitHub 项目？"
        )
        if messagebox.askyesno(title, message, parent=self.root):
            webbrowser.open(ECDICT_URL)

    def _open_settings(self) -> None:
        open_settings(self.root, BASE_DIR, self._settings_saved)

    def _settings_saved(self, config: dict[str, Any]) -> None:
        self.config_data = config
        self._build_ui()

    def _open_vocabulary_manager(self) -> None:
        open_vocabulary_manager(self.root, BASE_DIR, self._vocabulary_changed)

    def _vocabulary_changed(self) -> None:
        if hasattr(self, "vocabulary_status"):
            self.vocabulary_status.set(active_profile_summary(BASE_DIR))
        self.root.update_idletasks()

    def _start_learning(self) -> None:
        self.config_data = load_config(BASE_DIR)
        missing_ai = get_missing_ai_settings(self.config_data)
        if missing_ai:
            messagebox.showwarning(
                "AI 设置未完成",
                "开始学习前，请先填写：" + "、".join(missing_ai) + "。",
                parent=self.root,
            )
            self._open_settings()
            return

        self.learn_button.configure(state="disabled", text="本轮学习进行中……")
        self.root.update_idletasks()
        try:
            result = run_learning_round(self.root, BASE_DIR)
        except LearningDataError as exc:
            messagebox.showerror("数据错误", str(exc), parent=self.root)
        except Exception as exc:
            messagebox.showerror(
                "运行错误",
                f"本轮学习未完成，学习历史未更新。\n\n{type(exc).__name__}: {exc}",
                parent=self.root,
            )
        else:
            if result is not None:
                score_lines = "\n".join(
                    f"{word}: {score}"
                    for word, score in result["updated_scores"].items()
                )
                messagebox.showinfo(
                    "本轮学习完成",
                    (
                        f"已完成 {result['word_count']} 个词："
                        f"{result['new_word_count']} 个绝对新词、"
                        f"{result['review_word_count']} 个复习词。\n"
                        f"文章目标长度约 {result['article_target_word_count']} 词。\n\n"
                        f"最终熟练程度：\n{score_lines}"
                    ),
                    parent=self.root,
                )
                self._vocabulary_changed()
        finally:
            if self.learn_button.winfo_exists():
                self.learn_button.configure(
                    state="normal", text="开始一轮自适应学习"
                )


def main() -> None:
    root = tk.Tk()
    MainApplication(root)
    root.mainloop()


if __name__ == "__main__":
    main()
