from __future__ import annotations

import json
import re
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import colorchooser, messagebox
from typing import Any, Callable

DEFAULT_ARTICLE_PROMPT = (
    "你是一个英文文章写作器，以上为这次写作需要着重出现的词语。"
    "请撰写一篇文章，要求**一定**出现上述**所有**词语，并且尽可能地出现同一个词的所有不同用法，"
    "以达到用户学习词汇的目的。文章类型可以考虑应用文、议论文、说明文或记叙文。"
    "语气可以考虑学术严谨兼备口语习语。最终输出**一整篇**词汇数量300词的结构严谨的文章。"
)

DEFAULT_CONFIG: dict[str, Any] = {
    "words_per_round": 20,
    "new_words_per_round": 10,
    "text_color": "#000000",
    "background_color": "#ffffff",
    "button_color": "#ffffff",
    "border_color": "#000000",
    "api_key": "",
    "base_url": "https://api.openai.com/v1",
    "model": "",
    "article_prompt": DEFAULT_ARTICLE_PROMPT,
    "first_run_guide_shown": False,
}

_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")

# There is no single CJK font guaranteed to exist on Windows, macOS and Linux.
# Select the first suitable Simplified-Chinese UI font installed on the current
# system, then fall back to Tk's own default family.
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
    """Apply one consistent installed CJK family to Tk's named UI fonts."""
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
            # Some Tk builds do not define every optional named font.
            continue
    return family


def get_missing_ai_settings(config: dict[str, Any]) -> list[str]:
    """Return user-facing names of AI settings that are still blank."""
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


def _normalized_config(raw: dict[str, Any]) -> dict[str, Any]:
    config = DEFAULT_CONFIG.copy()
    config.update({key: value for key, value in raw.items() if key in DEFAULT_CONFIG})

    try:
        config["words_per_round"] = max(1, int(config["words_per_round"]))
    except (TypeError, ValueError):
        config["words_per_round"] = DEFAULT_CONFIG["words_per_round"]

    try:
        config["new_words_per_round"] = max(0, int(config["new_words_per_round"]))
    except (TypeError, ValueError):
        config["new_words_per_round"] = DEFAULT_CONFIG["new_words_per_round"]

    config["new_words_per_round"] = min(
        config["new_words_per_round"], config["words_per_round"]
    )

    for key in ("text_color", "background_color", "button_color", "border_color"):
        value = str(config.get(key, ""))
        if not _COLOR_PATTERN.fullmatch(value):
            config[key] = DEFAULT_CONFIG[key]
        else:
            config[key] = value.lower()

    for key in ("api_key", "base_url", "model", "article_prompt"):
        config[key] = str(config.get(key, ""))

    guide_value = config.get("first_run_guide_shown", False)
    if isinstance(guide_value, bool):
        config["first_run_guide_shown"] = guide_value
    else:
        config["first_run_guide_shown"] = str(guide_value).strip().casefold() in {
            "1", "true", "yes", "on"
        }

    return config


def save_config(config: dict[str, Any], base_dir: Path | str | None = None) -> dict[str, Any]:
    """Validate and atomically save config.json, then return the normalized data."""
    path = _config_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalized_config(config)
    temp_path = path.with_suffix(".json.tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(normalized, file, ensure_ascii=False, indent=2)
    temp_path.replace(path)
    return normalized


def load_config(base_dir: Path | str | None = None) -> dict[str, Any]:
    """Load config.json. Create it with defaults if it does not exist or is invalid."""
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
        self.title("设置")
        self.geometry("760x680")
        self.minsize(680, 580)
        self.transient(parent)
        self.grab_set()

        self._vars: dict[str, tk.StringVar] = {
            "words_per_round": tk.StringVar(value=str(self.config_data["words_per_round"])),
            "new_words_per_round": tk.StringVar(value=str(self.config_data["new_words_per_round"])),
            "text_color": tk.StringVar(value=self.config_data["text_color"]),
            "background_color": tk.StringVar(value=self.config_data["background_color"]),
            "button_color": tk.StringVar(value=self.config_data["button_color"]),
            "border_color": tk.StringVar(value=self.config_data["border_color"]),
            "api_key": tk.StringVar(value=self.config_data["api_key"]),
            "base_url": tk.StringVar(value=self.config_data["base_url"]),
            "model": tk.StringVar(value=self.config_data["model"]),
        }

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build_ui(self) -> None:
        outer = tk.Frame(self, padx=18, pady=18)
        outer.pack(fill="both", expand=True)
        outer.grid_columnconfigure(1, weight=1)
        outer.grid_rowconfigure(10, weight=1)

        labels = [
            ("每轮学习词汇数量 x", "words_per_round", False),
            ("每轮新词数量 y", "new_words_per_round", False),
            ("文字颜色", "text_color", True),
            ("背景颜色", "background_color", True),
            ("按钮颜色", "button_color", True),
            ("边框颜色", "border_color", True),
            ("API_KEY", "api_key", False),
            ("BASE_URL", "base_url", False),
            ("MODEL", "model", False),
        ]

        for row, (label_text, key, is_color) in enumerate(labels):
            tk.Label(outer, text=label_text, anchor="w").grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=6
            )
            entry = tk.Entry(
                outer,
                textvariable=self._vars[key],
                show="*" if key == "api_key" else "",
            )
            entry.grid(row=row, column=1, sticky="ew", pady=6)
            if is_color:
                tk.Button(
                    outer,
                    text="选择",
                    width=7,
                    command=lambda current_key=key: self._choose_color(current_key),
                ).grid(row=row, column=2, padx=(8, 0), pady=6)

        tk.Label(outer, text="AI 写作提示词", anchor="nw").grid(
            row=9, column=0, sticky="nw", padx=(0, 12), pady=(10, 6)
        )
        self.prompt_text = tk.Text(outer, wrap="word", height=12)
        self.prompt_text.insert("1.0", self.config_data["article_prompt"])
        self.prompt_text.grid(row=9, column=1, columnspan=2, sticky="nsew", pady=(10, 6))
        outer.grid_rowconfigure(9, weight=1)

        note = (
            "颜色必须使用 #RRGGBB 格式。BASE_URL 可填写到 /v1，程序会自动追加 "
            "/chat/completions；也可直接填写完整接口地址。"
        )
        tk.Label(outer, text=note, justify="left", anchor="w", fg="#555555").grid(
            row=10, column=0, columnspan=3, sticky="ew", pady=(6, 12)
        )

        buttons = tk.Frame(outer)
        buttons.grid(row=11, column=0, columnspan=3, sticky="e")
        tk.Button(buttons, text="恢复默认", command=self._restore_defaults).pack(
            side="left", padx=5
        )
        tk.Button(buttons, text="取消", command=self.destroy).pack(side="left", padx=5)
        tk.Button(buttons, text="保存", command=self._save).pack(side="left", padx=5)

    def _choose_color(self, key: str) -> None:
        _, selected = colorchooser.askcolor(
            color=self._vars[key].get(), parent=self, title="选择颜色"
        )
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
            x = int(self._vars["words_per_round"].get().strip())
            y = int(self._vars["new_words_per_round"].get().strip())
        except ValueError:
            messagebox.showerror("设置错误", "x 和 y 必须是整数。", parent=self)
            return

        if x < 1:
            messagebox.showerror("设置错误", "每轮学习词汇数量 x 必须至少为 1。", parent=self)
            return
        if y < 0 or y > x:
            messagebox.showerror("设置错误", "新词数量 y 必须满足 0 ≤ y ≤ x。", parent=self)
            return

        for key in ("text_color", "background_color", "button_color", "border_color"):
            if not _COLOR_PATTERN.fullmatch(self._vars[key].get().strip()):
                messagebox.showerror(
                    "设置错误", f"{key} 必须是 #RRGGBB 格式，例如 #ffffff。", parent=self
                )
                return

        data: dict[str, Any] = {
            "words_per_round": x,
            "new_words_per_round": y,
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

        # Keep this dialog alive while its child message box is shown.  The
        # callback rebuilds the main window and would otherwise destroy this
        # Toplevel before messagebox.showinfo can use it as the parent.
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
