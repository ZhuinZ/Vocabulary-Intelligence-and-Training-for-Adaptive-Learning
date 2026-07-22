from __future__ import annotations

import json
import queue
import re
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
from tkinter import messagebox
from typing import Any, Callable

from config_manager import configure_ui_fonts


def _endpoint_from_base_url(base_url: str) -> str:
    url = base_url.strip().rstrip("/")
    if not url:
        raise ValueError("BASE_URL 不能为空。")
    if url.endswith("/chat/completions"):
        return url
    return f"{url}/chat/completions"


def _call_chat_api(
    config: dict[str, Any],
    messages: list[dict[str, str]],
    temperature: float = 0.7,
) -> str:
    model = str(config.get("model", "")).strip()
    if not model:
        raise ValueError("MODEL 不能为空，请先在设置中填写模型名称。")

    endpoint = _endpoint_from_base_url(str(config.get("base_url", "")))
    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    headers = {"Content-Type": "application/json"}
    api_key = str(config.get("api_key", "")).strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API 返回 HTTP {exc.code}：{detail[:800]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接 API：{exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("API 请求超时。") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("API 返回的内容不是有效 JSON。") from exc

    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"无法从 API 响应中读取文章内容：{payload}") from exc

    if isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(str(part.get("text", "")))
        content = "\n".join(text_parts)

    result = str(content).strip()
    if not result:
        raise RuntimeError("API 返回了空内容。")
    return result


def _word_is_present(article: str, word: str) -> bool:
    return (
        re.search(
            rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])",
            article,
            re.IGNORECASE,
        )
        is not None
    )


def generate_article(words: list[str], config: dict[str, Any]) -> tuple[str, list[str]]:
    prompt = str(config.get("article_prompt", "")).strip()
    if not prompt:
        raise ValueError("AI 写作提示词不能为空。")

    word_list = ", ".join(words)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": (
                "本轮必须着重使用以下英文词汇，并确保每个词都至少以其原形完整出现一次：\n"
                f"{word_list}\n\n只输出英文文章正文，不要输出词汇表、说明或中文。"
            ),
        },
    ]

    article = ""
    missing: list[str] = words[:]
    for _ in range(2):
        article = _call_chat_api(config, messages, temperature=0.8)
        missing = [word for word in words if not _word_is_present(article, word)]
        if not missing:
            break
        messages.extend(
            [
                {"role": "assistant", "content": article},
                {
                    "role": "user",
                    "content": (
                        "请重写整篇英文文章。当前文章没有完整出现这些词的原形："
                        + ", ".join(missing)
                        + "。请确保所有目标词均至少完整出现一次，文章约300个英文词，只输出正文。"
                    ),
                },
            ]
        )
    return article, missing


def generate_translation(article: str, config: dict[str, Any]) -> str:
    return _call_chat_api(
        config,
        [
            {
                "role": "system",
                "content": (
                    "你是专业的英汉翻译。请将用户提供的英文文章准确、自然地翻译为简体中文，"
                    "保留段落结构，只输出译文，不添加解释。"
                ),
            },
            {"role": "user", "content": article},
        ],
        temperature=0.2,
    )


def count_english_words(text: str) -> int:
    return len(re.findall(r"[A-Za-z]+(?:['’\-][A-Za-z]+)*", text))


def format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class ArticleStudyDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        words: list[dict[str, str]],
        config: dict[str, Any],
    ) -> None:
        super().__init__(parent)
        self.config_data = config
        self.font_family = configure_ui_fonts(self)
        self.target_words = [
            item.get("word", "").strip()
            for item in words
            if item.get("word", "").strip()
        ]
        self.article = ""
        self.translation = ""
        self.reading_started_at: float | None = None
        self.completed = False
        self._closed = False

        self.title("文章学习")
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        width = min(1040, max(760, screen_width - 120))
        height = min(780, max(560, screen_height - 140))
        self.geometry(f"{width}x{height}")
        self.minsize(720, 520)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._try_abort)

        self._build_ui()
        self.bind("<KeyPress-space>", self._press_primary_button)
        self.after_idle(self.focus_force)
        self.after(100, self._start_article_generation)

    def _build_ui(self) -> None:
        bg = self.config_data["background_color"]
        fg = self.config_data["text_color"]
        border = self.config_data["border_color"]
        button_bg = self.config_data["button_color"]
        self.configure(bg=bg)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = tk.Frame(self, bg=bg, padx=18, pady=10)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        tk.Label(
            header,
            text="文章学习",
            font=(self.font_family, 22, "bold"),
            bg=bg,
            fg=fg,
        ).grid(row=0, column=0, sticky="w")
        self.status_label = tk.Label(
            header,
            text="正在生成文章……",
            bg=bg,
            fg=fg,
            anchor="e",
        )
        self.status_label.grid(row=0, column=1, sticky="e")

        target_frame = tk.Frame(self, bg=border, padx=1, pady=1)
        target_frame.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 9))
        tk.Label(
            target_frame,
            text="目标词汇：" + ", ".join(self.target_words),
            bg=bg,
            fg=fg,
            justify="left",
            anchor="w",
            wraplength=980,
            padx=10,
            pady=7,
        ).pack(fill="x")

        paned = tk.PanedWindow(
            self,
            orient="vertical",
            bg=bg,
            sashwidth=6,
            borderwidth=0,
        )
        paned.grid(row=2, column=0, sticky="nsew", padx=18)

        article_frame = tk.Frame(paned, bg=border, padx=1, pady=1)
        article_inner = tk.Frame(article_frame, bg=bg)
        article_inner.pack(fill="both", expand=True)
        tk.Label(
            article_inner,
            text="英文文章",
            bg=bg,
            fg=fg,
            font=(self.font_family, 12, "bold"),
            anchor="w",
            padx=8,
            pady=5,
        ).pack(fill="x")
        self.article_text = tk.Text(
            article_inner,
            wrap="word",
            bg=bg,
            fg=fg,
            insertbackground=fg,
            padx=10,
            pady=8,
            relief="flat",
            font=(self.font_family, 12),
        )
        article_scroll = tk.Scrollbar(article_inner, command=self.article_text.yview)
        self.article_text.configure(yscrollcommand=article_scroll.set)
        article_scroll.pack(side="right", fill="y")
        self.article_text.pack(side="left", fill="both", expand=True)
        self.article_text.configure(state="disabled")
        paned.add(article_frame, stretch="always", minsize=210)

        translation_frame = tk.Frame(paned, bg=border, padx=1, pady=1)
        translation_inner = tk.Frame(translation_frame, bg=bg)
        translation_inner.pack(fill="both", expand=True)
        tk.Label(
            translation_inner,
            text="中文译文（点击“我已读完”后生成）",
            bg=bg,
            fg=fg,
            font=(self.font_family, 12, "bold"),
            anchor="w",
            padx=8,
            pady=5,
        ).pack(fill="x")
        self.translation_text = tk.Text(
            translation_inner,
            wrap="word",
            bg=bg,
            fg=fg,
            insertbackground=fg,
            padx=10,
            pady=8,
            relief="flat",
            font=(self.font_family, 11),
        )
        translation_scroll = tk.Scrollbar(
            translation_inner, command=self.translation_text.yview
        )
        self.translation_text.configure(yscrollcommand=translation_scroll.set)
        translation_scroll.pack(side="right", fill="y")
        self.translation_text.pack(side="left", fill="both", expand=True)
        self.translation_text.configure(state="disabled")
        paned.add(translation_frame, stretch="always", minsize=120)

        # This action bar is in its own fixed grid row, so it cannot be pushed
        # below the visible window by the expanding article panes.
        bottom = tk.Frame(self, bg=bg, padx=18, pady=11)
        bottom.grid(row=3, column=0, sticky="ew")
        bottom.grid_columnconfigure(0, weight=1)
        self.stats_label = tk.Label(bottom, text="", bg=bg, fg=fg, anchor="w")
        self.stats_label.grid(row=0, column=0, sticky="ew")

        actions = tk.Frame(bottom, bg=bg)
        actions.grid(row=0, column=1, sticky="e")

        self.retry_border, self.retry_button = self._make_action_button(
            actions,
            "重试（空格）",
            self._retry,
            button_bg,
            fg,
            border,
        )
        self.read_border, self.read_button = self._make_action_button(
            actions,
            "我已读完（空格）",
            self._reading_finished,
            button_bg,
            fg,
            border,
            width=18,
        )
        self.finish_border, self.finish_button = self._make_action_button(
            actions,
            "完成并继续（空格）",
            self._finish,
            button_bg,
            fg,
            border,
            width=18,
        )
        self.retry_border.grid(row=0, column=0, padx=(0, 8))
        self.read_border.grid(row=0, column=1)
        self.finish_border.grid(row=0, column=2)
        self.retry_border.grid_remove()
        self.finish_border.grid_remove()
        self.read_button.configure(state="disabled")

    def _make_action_button(
        self,
        parent: tk.Misc,
        text: str,
        command: Callable[[], None],
        bg: str,
        fg: str,
        border: str,
        *,
        width: int = 12,
    ) -> tuple[tk.Frame, tk.Button]:
        border_frame = tk.Frame(parent, bg=border, padx=1, pady=1)
        button = tk.Button(
            border_frame,
            text=text,
            command=command,
            state="normal",
            bg=bg,
            fg=fg,
            activebackground=bg,
            activeforeground=fg,
            relief="flat",
            width=width,
            padx=12,
            pady=7,
            takefocus=False,
            font=(self.font_family, 10),
        )
        button.pack()
        return border_frame, button

    def _press_primary_button(self, event: tk.Event) -> str | None:
        for button, border_frame in (
            (self.read_button, self.read_border),
            (self.finish_button, self.finish_border),
            (self.retry_button, self.retry_border),
        ):
            if (
                border_frame.winfo_ismapped()
                and str(button.cget("state")) != "disabled"
            ):
                if event.widget is button:
                    return None
                button.invoke()
                return "break"
        return "break"

    def _set_text(self, widget: tk.Text, content: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")
        widget.yview_moveto(0)

    def _run_worker(self, function: Any, success: Any, failure: Any) -> None:
        result_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

        def worker() -> None:
            try:
                result_queue.put(("success", function()))
            except Exception as exc:
                result_queue.put(("failure", exc))

        def poll_result() -> None:
            if self._closed or not self.winfo_exists():
                return
            try:
                status, value = result_queue.get_nowait()
            except queue.Empty:
                self.after(40, poll_result)
                return
            if status == "success":
                success(value)
            else:
                failure(value)

        threading.Thread(target=worker, daemon=True).start()
        self.after(40, poll_result)

    def _start_article_generation(self) -> None:
        self.status_label.configure(text="正在生成文章……")
        self.read_button.configure(state="disabled", text="正在生成文章……")
        self.read_border.grid()
        self.finish_border.grid_remove()
        self.retry_border.grid_remove()
        self._set_text(self.article_text, "")
        self._set_text(self.translation_text, "")
        self.stats_label.configure(text="")
        self._run_worker(
            lambda: generate_article(self.target_words, self.config_data),
            self._article_ready,
            self._article_failed,
        )

    def _article_ready(self, result: tuple[str, list[str]]) -> None:
        self.article, missing = result
        self._set_text(self.article_text, self.article)
        self.reading_started_at = time.monotonic()
        self.read_button.configure(state="normal", text="我已读完（空格）")
        if missing:
            self.status_label.configure(
                text="文章已生成，但仍缺少原形：" + ", ".join(missing)
            )
        else:
            self.status_label.configure(text="文章已生成，阅读计时已开始")
        self.after_idle(self.focus_force)

    def _article_failed(self, exc: Exception) -> None:
        self.status_label.configure(text="文章生成失败")
        self._set_text(self.article_text, f"生成失败：\n{exc}")
        self.read_button.configure(state="disabled", text="我已读完（空格）")
        self.retry_button.configure(text="重试生成文章（空格）", command=self._retry)
        self.retry_border.grid()

    def _reading_finished(self) -> None:
        if not self.article or self.reading_started_at is None:
            return
        elapsed = time.monotonic() - self.reading_started_at
        word_count = count_english_words(self.article)
        self.stats_label.configure(
            text=f"文章词数：{word_count}｜阅读时间：{format_duration(elapsed)}"
        )
        self.read_button.configure(state="disabled", text="正在生成译文……")
        self.status_label.configure(text="阅读完成，正在生成中文译文……")
        self._run_worker(
            lambda: generate_translation(self.article, self.config_data),
            self._translation_ready,
            self._translation_failed,
        )

    def _translation_ready(self, translation: str) -> None:
        self.translation = translation
        self._set_text(self.translation_text, translation)
        self.status_label.configure(text="译文已生成")
        self.retry_border.grid_remove()
        self.read_border.grid_remove()
        self.finish_button.configure(state="normal")
        self.finish_border.grid()
        self.after_idle(self.focus_force)

    def _translation_failed(self, exc: Exception) -> None:
        self.status_label.configure(text="译文生成失败")
        self._set_text(self.translation_text, f"生成失败：\n{exc}")
        self.read_border.grid_remove()
        self.retry_button.configure(
            text="重试生成译文（空格）", command=self._retry_translation
        )
        self.retry_border.grid()

    def _retry(self) -> None:
        self.retry_button.configure(text="重试（空格）", command=self._retry)
        self._start_article_generation()

    def _retry_translation(self) -> None:
        self.retry_border.grid_remove()
        self.status_label.configure(text="正在重新生成中文译文……")
        self._run_worker(
            lambda: generate_translation(self.article, self.config_data),
            self._translation_ready,
            self._translation_failed,
        )

    def _finish(self) -> None:
        self.completed = True
        self._closed = True
        self.destroy()

    def _try_abort(self) -> None:
        if messagebox.askyesno(
            "中止本轮学习",
            "关闭窗口会中止本轮学习，并且不会更新学习历史。确定关闭吗？",
            parent=self,
        ):
            self.completed = False
            self._closed = True
            self.destroy()


def run_article_study(
    parent: tk.Misc,
    words: list[dict[str, str]],
    config: dict[str, Any],
) -> bool:
    dialog = ArticleStudyDialog(parent, words, config)
    parent.wait_window(dialog)
    return dialog.completed
