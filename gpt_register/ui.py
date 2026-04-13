from __future__ import annotations

import json
import threading
from typing import Any

from rich.console import Console, RenderableType
from rich.json import JSON
from rich.panel import Panel
from rich.text import Text

from . import context as ctx


console = Console(highlight=False, soft_wrap=True)
_print_state = threading.local()


def _style_for_text(text: str) -> str | None:
    lowered = text.lower()
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith("[error]") or " 本次注册失败" in text or "失败" in text and "成功" not in text:
        return "bold red"
    if stripped.startswith("[warning]") or "warning" in lowered:
        return "yellow"
    if "抓到啦" in text or "注册成功" in text or "预检通过" in text or "验证通过" in text:
        return "bold green"
    if stripped.startswith("[graph调试]") or stripped.startswith("[debug]") or "[debug][" in lowered:
        return "magenta"
    if "开始注册" in text or stripped.startswith("[*]"):
        return "cyan"
    if stripped.startswith("[状态]") or stripped.startswith("● 实时状态"):
        return "bold blue"
    return None


def _maybe_json_renderable(text: str) -> RenderableType | None:
    stripped = text.strip()
    if not stripped.startswith("{"):
        return None
    try:
        payload = json.loads(stripped)
    except Exception:
        return None
    return Panel(
        JSON.from_data(payload),
        title="响应 JSON",
        border_style="red",
        padding=(0, 1),
    )


def _is_line_start() -> bool:
    return bool(getattr(_print_state, "line_start", True))


def _set_line_start(value: bool) -> None:
    _print_state.line_start = bool(value)


def _thread_prefix() -> tuple[str, str | None]:
    thread_id = ctx.get_log_thread_id()
    if not thread_id:
        return "", None
    return f"[{thread_id}] ", f"bold {ctx.get_log_thread_color(thread_id)}"


def _build_text_renderable(text: str, style: str | None) -> Text:
    renderable = Text()
    prefix, prefix_style = _thread_prefix()
    line_start = _is_line_start()
    segments = text.splitlines(keepends=True)
    if not segments:
        segments = [text]

    for segment in segments:
        newline = ""
        body = segment
        if segment.endswith("\r\n"):
            body = segment[:-2]
            newline = "\r\n"
        elif segment.endswith("\n") or segment.endswith("\r"):
            body = segment[:-1]
            newline = segment[-1]

        if body:
            if line_start and prefix:
                renderable.append(prefix, style=prefix_style)
            renderable.append(body, style=style)
            line_start = False

        if newline:
            renderable.append(newline)
            line_start = True

    _set_line_start(line_start)
    return renderable


def rich_print(*args: Any, sep: str = " ", end: str = "\n", flush: bool = False, **kwargs: Any) -> None:
    del flush, kwargs
    text = sep.join(str(arg) for arg in args)

    # 压制轮询中的 dot spam，避免终端被 "." 刷屏
    if text == "." and end == "":
        return

    json_renderable = _maybe_json_renderable(text)
    if json_renderable is not None and end == "\n":
        console.print(json_renderable)
        _set_line_start(True)
        return

    style = _style_for_text(text)
    renderable: RenderableType = _build_text_renderable(text, style)
    console.print(renderable, end=end, highlight=False, soft_wrap=True)
    if end:
        _set_line_start(end.endswith("\n"))
