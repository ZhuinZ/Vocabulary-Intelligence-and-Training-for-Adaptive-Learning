from __future__ import annotations

import json
import re
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import colorchooser, messagebox, ttk
from typing import Any, Callable

DEFAULT_ARTICLE_PROMPT = (
    "你是一个英文文章写作器。用户会提供本轮需要着重出现的英文词语。"
    "请撰写一篇结构严谨的英文文章，确保所有目标词都至少以原形完整出现一次，"
    "并尽可能自然地展示不同语义和用法。文章可以是应用文、议论文、说明文或记叙文，"
    "语气可兼顾学术严谨与自然表达。只输出英文文章正文，不要输出词汇表、解释或中文。"
)
LEGACY_DEFAULT_ARTICLE_PROMPTS = {
    (
        "你是一个英文文章写作器，以上为这次写作需要着重出现的词语。"
        "请撰写一篇文章，要求**一定**出现上述**所有**词语，并且尽可能地出现同一个词的所有不同用法，"
        "以达到用户学习词汇的目的。文章类型可以考虑应用文、议论文、说明文或记叙文。"
        "语气可以考虑学术严谨兼备口语习语。最终输出**一整篇**词汇数量300词的结构严谨的文章。"
    ),
    (
        "你是一个英文文章写作器，以上为这次写作需要着重出现的词语。"
        "请撰写一篇文章，要求一定出现上述所有词语，并且尽可能地出现同一个词的所有不同用法，"
        "以达到用户学习词汇的目的。文章类型可以考虑应用文、议论文、说明文或记叙文。"
        "语气可以考虑学术严谨兼备口语习语。只输出结构严谨的英文文章正文。"
    ),
}

CONFIG_VERSION = 2
DEFAULT_CONFIG: dict[str, Any] = {
    "config_version": CONFIG_VERSION,
    "words_per_round": 20,
    "new_words_per_round": 3,
    "new_word_mode": "fixed",
    "text_color": "#172033",
    "background_color": "#f5f7fb",
    "button_color": "#ffffff",
    "border_color": "#24324a",
    "api_key": "",
    "base_url": "https://api.openai.com/v1",
    "model": "",
    "article_prompt": DEFAULT_ARTICLE_PROMPT,
    "first_run_guide_shown": False,
}

_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
_CJK_FONT_CANDIDATES = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "PingFang SC",
    "Noto Sans CJK SC",
    "Noto Sans SC",
    "Source Han Sans SC",
    "WenQuanYi Micro Hei",
    "SimHei",
)


def get_cjk_font_family(widget: tk.Misc) -> str:
    cached = getattr(widget.winfo_toplevel(), "_vital_cjk_font_family", None)
    if cached:
        return str(cached)
    available = {family.casefold(): family for family in tkfont.families(widget)}
    for candidate in _CJK_FONT_CANDIDATES:
        installed = available.get(candidate.casefold())
        if installed:
            family = installed
            break
    else:
        family = str(tkfont.nametofont("TkDefaultFont", root=widget).actual("family"))
    setattr(widget.winfo_toplevel(), "_vital_cjk_font_family", family)
    return family


def configure_ui_fonts(widget: tk.Misc) -> str:
    family = get_cjk_font_family(widget)
    for name in (
        "TkDefaultFont",
        "TkTextFont",
        "TkMenuFont",
        "TkHeadingFont",
        "TkCaptionFont",
        "TkSmallCaptionFont",
        "TkIconFont",
        "TkTooltipFont",
    ):
        try:
            tkfont.nametofont(name, root=widget).configure(family=family)
        except tk.TclError:
            continue
    return family


def get_missing_ai_settings(config: dict[str, Any]) -> list[str]:
    required = (
        ("api_key", "API_KEY"),
        ("base_url", "BASE_URL"),
        ("model", "MODEL"),
        ("article_prompt", "AI 写作提示词"),
    )
    return [label for key, label in required if not str(config.get(key, "")).strip()]


def _config_path(base_dir: Path | str | None = None) -> Path:
    base = Path(base_dir) if base_dir is not None else Path(__file__).resolve().parent
    return base / "config.json"


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def _normalized_config(raw: dict[str, Any]) -> dict[str, Any]:
    config = DEFAULT_CONFIG.copy()
    config.update({key: value for key, value in raw.items() if key in DEFAULT_CONFIG})

    try:
        config["words_per_round"] = min(100, max(1, int(config["words_per_round"])))
    except (TypeError, ValueError):
        config["words_per_round"] = DEFAULT_CONFIG["words_per_round"]
    try:
        config["new_words_per_round"] = max(0, int(config["new_words_per_round"]))
    except (TypeError, ValueError):
        config["new_words_per_round"] = DEFAULT_CONFIG["new_words_per_round"]

    # Match the server migration: only installations still using the old exact
    # default 20/10 are moved to the new 20/3 default. User-customized values stay.
    def safe_int(value: object, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    raw_version = safe_int(raw.get("config_version", 0), 0)
    if (
        raw_version < 2
        and safe_int(raw.get("words_per_round", 20), 20) == 20
        and safe_int(raw.get("new_words_per_round", 10), 10) == 10
    ):
        config["new_words_per_round"] = 3
    config["new_words_per_round"] = min(
        config["new_words_per_round"], config["words_per_round"]
    )

    mode = str(config.get("new_word_mode", "fixed")).strip().casefold()
    config["new_word_mode"] = mode if mode in {"fixed", "adaptive"} else "fixed"

    for key in ("text_color", "background_color", "button_color", "border_color"):
        value = str(config.get(key, ""))
        config[key] = value.lower() if _COLOR_PATTERN.fullmatch(value) else DEFAULT_CONFIG[key]

    for key in ("api_key", "base_url", "model", "article_prompt"):
        config[key] = str(config.get(key, ""))
    if config["article_prompt"].strip() in LEGACY_DEFAULT_ARTICLE_PROMPTS:
        config["article_prompt"] = DEFAULT_ARTICLE_PROMPT

    config["first_run_guide_shown"] = _to_bool(
        config.get("first_run_guide_shown", False)
    )
    config["config_version"] = CONFIG_VERSION
    return config


def save_config(
    config: dict[str, Any], base_dir: Path | str | None = None
) -> dict[str, Any]:
    path = _config_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalized_config(config)
    temp_path = path.with_suffix(".json.tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(normalized, file, ensure_ascii=False, indent=2)
    temp_path.replace(path)
    return normalized


def load_config(base_dir: Path | str | None = None) -> dict[str, Any]:
    path = _config_path(base_dir)
    if not path.exists():
        return save_config(DEFAULT_CONFIG, base_dir)
    try:
        with path.open("r", encoding="utf-8") as file:
            raw = json.load(file)
        if not isinstance(raw, dict):
            raise ValueError("config.json 的根元素必须是对象")
    except (OSError, json.JSONDecodeError, ValueError):
        backup = path.with_suffix(".json.invalid")
        try:
            path.replace(backup)
        except OSError:
            pass
        return save_config(DEFAULT_CONFIG, base_dir)
    normalized = _normalized_config(raw)
    if normalized != raw:
        save_config(normalized, base_dir)
    return normalized


class SettingsDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        base_dir: Path | str | None = None,
        on_saved: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.parent = parent
        self.base_dir = base_dir
        self.on_saved = on_saved
        self.config_data = load_config(base_dir)
        self.font_family = configure_ui_fonts(self)
        self.title("VITAL 学习设置")
        self.geometry("820x760")
        self.minsize(720, 620)
        self.transient(parent)
        self.grab_set()

        self._vars: dict[str, tk.StringVar] = {
            "words_per_round": tk.StringVar(value=str(self.config_data["words_per_round"])),
            "new_words_per_round": tk.StringVar(value=str(self.config_data["new_words_per_round"])),
            "new_word_mode": tk.StringVar(value=self.config_data["new_word_mode"]),
            "text_color": tk.StringVar(value=self.config_data["text_color"]),
            "background_color": tk.StringVar(value=self.config_data["background_color"]),
            "button_color": tk.StringVar(value=self.config_data["button_color"]),
            "border_color": tk.StringVar(value=self.config_data["border_color"]),
            "api_key": tk.StringVar(value=self.config_data["api_key"]),
            "base_url": tk.StringVar(value=self.config_data["base_url"]),
            "model": tk.StringVar(value=self.config_data["model"]),
        }
        self.summary_var = tk.StringVar()
        self._build_ui()
        self._update_summary()
        for key in ("words_per_round", "new_words_per_round", "new_word_mode"):
            self._vars[key].trace_add("write", lambda *_args: self._update_summary())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build_ui(self) -> None:
        outer = tk.Frame(self, padx=18, pady=16)
        outer.pack(fill="both", expand=True)
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(2, weight=1)

        tk.Label(
            outer,
            text="学习设置",
            font=(self.font_family, 20, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 10))

        learning = tk.LabelFrame(outer, text="每轮学习与自适应安排", padx=14, pady=12)
        learning.grid(row=1, column=0, sticky="ew")
        learning.grid_columnconfigure(1, weight=1)
        labels = (
            ("每轮学习词数", "words_per_round", "包括绝对新词和复习词，默认 20。"),
            ("每轮新词基准数", "new_words_per_round", "仅指从未学习过的词，默认 3。"),
        )
        for row, (text, key, note) in enumerate(labels):
            tk.Label(learning, text=text, anchor="w").grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=6
            )
            tk.Entry(learning, textvariable=self._vars[key], width=12).grid(
                row=row, column=1, sticky="w", pady=6
            )
            tk.Label(learning, text=note, fg="#596579", anchor="w").grid(
                row=row, column=2, sticky="w", padx=(12, 0), pady=6
            )
        tk.Label(learning, text="新词安排方式", anchor="w").grid(
            row=2, column=0, sticky="w", padx=(0, 12), pady=6
        )
        mode_frame = tk.Frame(learning)
        mode_frame.grid(row=2, column=1, sticky="w", pady=6)
        tk.Radiobutton(
            mode_frame,
            text="固定新词基准数",
            variable=self._vars["new_word_mode"],
            value="fixed",
        ).pack(side="left")
        tk.Radiobutton(
            mode_frame,
            text="智能调节新词数",
            variable=self._vars["new_word_mode"],
            value="adaptive",
        ).pack(side="left", padx=(12, 0))
        tk.Label(
            learning,
            text="智能模式会结合学习间隔与近期保持率，在安全范围内调整新词数。",
            fg="#596579",
            anchor="w",
        ).grid(row=2, column=2, sticky="w", padx=(12, 0), pady=6)
        tk.Label(
            learning,
            textvariable=self.summary_var,
            bg="#e8eef9",
            fg="#172033",
            anchor="w",
            padx=10,
            pady=8,
        ).grid(row=3, column=0, columnspan=3, sticky="ew", pady=(8, 0))

        notebook = ttk.Notebook(outer)
        notebook.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        appearance_tab = tk.Frame(notebook, padx=14, pady=14)
        ai_tab = tk.Frame(notebook, padx=14, pady=14)
        notebook.add(appearance_tab, text="界面")
        notebook.add(ai_tab, text="AI 接口")

        appearance_tab.grid_columnconfigure(1, weight=1)
        for row, (label_text, key) in enumerate(
            (
                ("文字颜色", "text_color"),
                ("背景颜色", "background_color"),
                ("按钮颜色", "button_color"),
                ("边框颜色", "border_color"),
            )
        ):
            tk.Label(appearance_tab, text=label_text, anchor="w").grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=7
            )
            tk.Entry(appearance_tab, textvariable=self._vars[key]).grid(
                row=row, column=1, sticky="ew", pady=7
            )
            tk.Button(
                appearance_tab,
                text="选择",
                width=7,
                command=lambda current_key=key: self._choose_color(current_key),
            ).grid(row=row, column=2, padx=(8, 0), pady=7)
        tk.Label(
            appearance_tab,
            text="颜色使用 #RRGGBB 格式。",
            fg="#596579",
            anchor="w",
        ).grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 0))

        ai_tab.grid_columnconfigure(1, weight=1)
        ai_tab.grid_rowconfigure(3, weight=1)
        for row, (label_text, key, secret) in enumerate(
            (
                ("API_KEY", "api_key", True),
                ("BASE_URL", "base_url", False),
                ("MODEL", "model", False),
            )
        ):
            tk.Label(ai_tab, text=label_text, anchor="w").grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=6
            )
            tk.Entry(
                ai_tab,
                textvariable=self._vars[key],
                show="*" if secret else "",
            ).grid(row=row, column=1, sticky="ew", pady=6)
        tk.Label(ai_tab, text="AI 写作提示词", anchor="nw").grid(
            row=3, column=0, sticky="nw", padx=(0, 12), pady=(10, 6)
        )
        self.prompt_text = tk.Text(ai_tab, wrap="word", height=13)
        self.prompt_text.insert("1.0", self.config_data["article_prompt"])
        self.prompt_text.grid(row=3, column=1, sticky="nsew", pady=(10, 6))
        tk.Label(
            ai_tab,
            text=(
                "BASE_URL 可填写到 /v1，程序会自动追加 /chat/completions；"
                "也可直接填写完整接口地址。文章目标词数会由本轮新词/复习词数量动态附加。"
            ),
            fg="#596579",
            justify="left",
            anchor="w",
            wraplength=630,
        ).grid(row=4, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        buttons = tk.Frame(outer)
        buttons.grid(row=3, column=0, sticky="e", pady=(12, 0))
        tk.Button(buttons, text="恢复默认", command=self._restore_defaults).pack(
            side="left", padx=5
        )
        tk.Button(buttons, text="取消", command=self.destroy).pack(side="left", padx=5)
        tk.Button(buttons, text="保存", command=self._save).pack(side="left", padx=5)

    def _update_summary(self) -> None:
        try:
            total = max(0, int(self._vars["words_per_round"].get()))
            new = max(0, int(self._vars["new_words_per_round"].get()))
        except ValueError:
            self.summary_var.set("请输入有效整数。")
            return
        new = min(new, total)
        mode = self._vars["new_word_mode"].get()
        mode_text = "智能调节" if mode == "adaptive" else "固定数量"
        self.summary_var.set(
            f"预计每轮 {total} 个词：约 {new} 个绝对新词、{max(0, total-new)} 个复习词；{mode_text}。"
        )

    def _choose_color(self, key: str) -> None:
        _, selected = colorchooser.askcolor(color=self._vars[key].get(), parent=self)
        if selected:
            self._vars[key].set(selected.lower())

    def _restore_defaults(self) -> None:
        for key, value in DEFAULT_CONFIG.items():
            if key == "article_prompt":
                self.prompt_text.delete("1.0", "end")
                self.prompt_text.insert("1.0", value)
            elif key in self._vars:
                self._vars[key].set(str(value))

    def _save(self) -> None:
        try:
            total = int(self._vars["words_per_round"].get().strip())
            new = int(self._vars["new_words_per_round"].get().strip())
        except ValueError:
            messagebox.showerror("设置错误", "学习词数和新词基准数必须是整数。", parent=self)
            return
        if not 1 <= total <= 100:
            messagebox.showerror("设置错误", "每轮学习词数必须在 1～100 之间。", parent=self)
            return
        if new < 0 or new > total:
            messagebox.showerror("设置错误", "新词基准数必须满足 0 ≤ 新词数 ≤ 总词数。", parent=self)
            return
        mode = self._vars["new_word_mode"].get().strip()
        if mode not in {"fixed", "adaptive"}:
            messagebox.showerror("设置错误", "新词安排方式无效。", parent=self)
            return
        for key in ("text_color", "background_color", "button_color", "border_color"):
            if not _COLOR_PATTERN.fullmatch(self._vars[key].get().strip()):
                messagebox.showerror(
                    "设置错误", f"{key} 必须是 #RRGGBB 格式，例如 #ffffff。", parent=self
                )
                return
        data: dict[str, Any] = {
            "config_version": CONFIG_VERSION,
            "words_per_round": total,
            "new_words_per_round": new,
            "new_word_mode": mode,
            "text_color": self._vars["text_color"].get().strip(),
            "background_color": self._vars["background_color"].get().strip(),
            "button_color": self._vars["button_color"].get().strip(),
            "border_color": self._vars["border_color"].get().strip(),
            "api_key": self._vars["api_key"].get().strip(),
            "base_url": self._vars["base_url"].get().strip(),
            "model": self._vars["model"].get().strip(),
            "article_prompt": self.prompt_text.get("1.0", "end-1c").strip(),
            "first_run_guide_shown": bool(
                self.config_data.get("first_run_guide_shown", False)
            ),
        }
        if not data["article_prompt"]:
            messagebox.showerror("设置错误", "AI 写作提示词不能为空。", parent=self)
            return
        saved = save_config(data, self.base_dir)
        messagebox.showinfo("设置", "设置已保存。", parent=self)
        self.destroy()
        if self.on_saved:
            self.parent.after_idle(lambda: self.on_saved(saved))


def open_settings(
    parent: tk.Misc,
    base_dir: Path | str | None = None,
    on_saved: Callable[[dict[str, Any]], None] | None = None,
) -> SettingsDialog:
    return SettingsDialog(parent, base_dir=base_dir, on_saved=on_saved)
