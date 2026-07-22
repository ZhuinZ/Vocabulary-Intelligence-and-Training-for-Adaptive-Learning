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

BASE_DIR = Path(__file__).resolve().parent
AUTHOR_NAME = "ZhuinZ"
SYSTEM_NAME = "AI 辅助英文单词学习系统"
AUTHOR_URL = "https://github.com/ZhuinZ"
ECDICT_URL = "https://github.com/skywind3000/ECDICT"


class MainApplication:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.config_data = load_config(BASE_DIR)
        self.font_family = configure_ui_fonts(self.root)
        self.root.title(SYSTEM_NAME)
        self.root.geometry("760x550")
        self.root.minsize(650, 470)
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

        main = tk.Frame(self.root, bg=bg, padx=36, pady=28)
        main.pack(fill="both", expand=True)

        tk.Label(
            main,
            text=SYSTEM_NAME,
            bg=bg,
            fg=fg,
            font=(self.font_family, 24, "bold"),
            pady=16,
        ).pack()

        tk.Label(
            main,
            text=(
                f"每轮 {self.config_data['words_per_round']} 个词，其中新学习词 "
                f"{self.config_data['new_words_per_round']} 个"
            ),
            bg=bg,
            fg=fg,
            font=(self.font_family, 11),
            pady=6,
        ).pack()

        buttons = tk.Frame(main, bg=bg)
        buttons.pack(expand=True)

        self.learn_button = self._bordered_button(
            buttons,
            text="学习一轮单词",
            command=self._start_learning,
            width=24,
            bg=button_bg,
            fg=fg,
            border=border,
        )
        self.learn_button.master.pack(pady=8)

        manage_button = self._bordered_button(
            buttons,
            text="管理词库和学习历史",
            command=self._open_vocabulary_manager,
            width=24,
            bg=button_bg,
            fg=fg,
            border=border,
        )
        manage_button.master.pack(pady=8)

        settings_button = self._bordered_button(
            buttons,
            text="设置",
            command=self._open_settings,
            width=24,
            bg=button_bg,
            fg=fg,
            border=border,
        )
        settings_button.master.pack(pady=8)

        footer = tk.Frame(self.root, bg=bg, padx=14, pady=10)
        footer.place(relx=1.0, rely=1.0, anchor="se")
        author = tk.Label(
            footer,
            text=AUTHOR_NAME,
            bg=bg,
            fg=fg,
            font=(self.font_family, 9, "underline"),
            cursor="hand2",
        )
        author.pack(side="left")
        author.bind("<Button-1>", lambda _event: self._open_author_link())

        tk.Label(
            footer,
            text=" · ",
            bg=bg,
            fg=fg,
            font=(self.font_family, 9),
        ).pack(side="left")
        download = tk.Label(
            footer,
            text="点我下载词库",
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

    def _open_author_link(self) -> None:
        if not AUTHOR_URL:
            messagebox.showinfo("作者链接", "作者链接暂未设置。", parent=self.root)
            return
        webbrowser.open(AUTHOR_URL)

    def _show_ecdict_guide(self, *, first_run: bool) -> None:
        if first_run:
            self.config_data["first_run_guide_shown"] = True
            self.config_data = save_config(self.config_data, BASE_DIR)

        title = "首次使用：获取 ECDICT 词库" if first_run else "获取 ECDICT 词库"
        message = (
            "本程序不会自动下载大型词库。请按以下步骤获取 stardict.csv：\n\n"
            "1. 打开 ECDICT GitHub 项目。\n"
            "2. 下载项目中的 stardict.7z；也可以下载整个项目后找到该文件。\n"
            "3. 使用 7-Zip 等解压工具解压 stardict.7z，取得 stardict.csv。\n"
            "4. 回到主界面，打开“管理词库和学习历史”。\n"
            "5. 选择 stardict.csv，输入 gre、cet6、ielts 等一个或多个 tag，"
            "然后生成并切换 vocabulary.csv。\n\n"
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
        # Kept as a callback hook for future current-vocabulary summaries.
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

        self.learn_button.configure(state="disabled")
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
                    f"已完成 {result['word_count']} 个词，并更新 learningHistory.csv。\n\n"
                    f"最终熟练程度：\n{score_lines}",
                    parent=self.root,
                )
        finally:
            if self.learn_button.winfo_exists():
                self.learn_button.configure(state="normal")


def main() -> None:
    root = tk.Tk()
    MainApplication(root)
    root.mainloop()


if __name__ == "__main__":
    main()
