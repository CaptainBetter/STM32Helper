"""STM32 极速翻译：复制代码，按 Alt+Q，在悬浮窗中查看解释。"""

from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path

import keyboard
import pyperclip
from dotenv import dotenv_values, load_dotenv
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

APP_DIR = Path(__file__).resolve().parent
ENV_PATH = APP_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=False)
ENV_FILE_VALUES = dotenv_values(ENV_PATH)

HOTKEY = "alt+q"
MODEL = "deepseek-chat"
BASE_URL = "https://api.deepseek.com"
SYSTEM_PROMPT = """你是一个拥有10年经验的资深 STM32 嵌入式开发工程师。
我正在阅读 STM32 标准库/HAL库的源码或头文件。下面是我复制的一段代码、宏、结构体或函数定义：

【{code_text}】

请严格按照以下格式回答（字数控制在150字以内，直接说重点）：
1. **作用**：一句话说明它是干什么用的（例如：配置定时器PWM输出通道）。
2. **英文拆解**：如果是缩写或宏，拆解它的英文全称并翻译。
3. **参数解析**：如果包含括号和变量（如 uint16_t TIM_Channel），请解释里面填的变量分别是什么意思。
4. **场景举例**：给我一句在 C 语言里怎么调用它/怎么用它的示例。
"""

MAX_CODE_CHARS = 12_000
MAX_OUTPUT_TOKENS = 512
REQUEST_TIMEOUT_SECONDS = 40.0
HOTKEY_DEBOUNCE_SECONDS = 0.7

WINDOW_WIDTH = 620
WINDOW_MAX_HEIGHT = 480
BG = "#000000"
FG = "#00ff66"
DIM = "#00b34a"
BORDER = "#00ff66"
FONT_BODY = ("Microsoft YaHei UI", 12)
FONT_SMALL = ("Consolas", 9, "bold")

PLACEHOLDER_KEYS = {
    "",
    "your_api_key_here",
    "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "sk-请替换成你的key",
}


# ---------------------------------------------------------------------------
# 数据处理
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TranslationResult:
    request_id: int
    text: str


def build_system_prompt(code_text: str) -> str:
    return SYSTEM_PROMPT.replace("{code_text}", code_text, 1)


def get_api_key() -> str:
    """优先使用项目 .env 中的非空 Key，缺失时再回退到系统环境变量。"""
    for raw in (
        ENV_FILE_VALUES.get("DEEPSEEK_API_KEY"),
        os.getenv("DEEPSEEK_API_KEY"),
    ):
        key = (raw or "").strip()
        if key and key.lower() not in PLACEHOLDER_KEYS:
            return key
    return ""


def friendly_api_error(exc: Exception) -> str:
    """把 SDK 异常转换成适合悬浮窗展示的短提示。"""
    if isinstance(exc, AuthenticationError):
        return "API Key 无效或已失效。\n请检查 .env 中的 DEEPSEEK_API_KEY，保存后重启程序。"
    if isinstance(exc, APITimeoutError):
        return "请求 DeepSeek 超时。\n请检查网络，稍后按 Alt+Q 重试。"
    if isinstance(exc, APIConnectionError):
        return "无法连接 DeepSeek。\n请检查网络或代理设置，稍后按 Alt+Q 重试。"
    if isinstance(exc, RateLimitError):
        return "请求过于频繁或账户额度不足。\n请稍后再试，并检查 DeepSeek 账户余额。"
    if isinstance(exc, APIStatusError):
        return f"DeepSeek 返回错误（HTTP {exc.status_code}）。\n请稍后按 Alt+Q 重试。"
    return f"翻译失败：{type(exc).__name__}\n{str(exc)[:180]}"


# ---------------------------------------------------------------------------
# 悬浮窗
# ---------------------------------------------------------------------------


class TranslatorApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("STM32 Quick Translate")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        try:
            self.root.attributes("-alpha", 0.97)
        except tk.TclError:
            pass

        self.frame = tk.Frame(
            self.root,
            bg=BG,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        self.frame.pack(fill="both", expand=True)

        self.content = tk.Frame(self.frame, bg=BG)
        self.content.pack(fill="both", expand=True, padx=20, pady=16)

        self.header = tk.Label(
            self.content,
            text="STM32 QUICK DECODE  //  ALT+Q",
            font=FONT_SMALL,
            bg=BG,
            fg=DIM,
            anchor="w",
            justify="left",
        )
        self.header.pack(fill="x")

        self.body = tk.Label(
            self.content,
            text="",
            font=FONT_BODY,
            bg=BG,
            fg=FG,
            anchor="w",
            justify="left",
            wraplength=WINDOW_WIDTH - 50,
        )
        self.body.pack(fill="x", pady=(12, 10))

        self.footer = tk.Label(
            self.content,
            text="点击关闭",
            font=FONT_SMALL,
            bg=BG,
            fg=DIM,
            anchor="w",
            justify="left",
        )
        self.footer.pack(fill="x")

        self.events: queue.Queue[str] = queue.Queue()
        self.results: queue.Queue[TranslationResult] = queue.Queue()
        self.request_seq = 0
        self.active_request_id: int | None = None
        self.last_hotkey_at = 0.0
        self.demo_mode = False
        self.hotkey_ready = False
        self._hotkey_handle: int | None = None
        self._poll_job: str | None = None

        for widget in (
            self.root,
            self.frame,
            self.content,
            self.header,
            self.body,
            self.footer,
        ):
            widget.configure(cursor="hand2")
            widget.bind("<Button-1>", self.hide_overlay)
        self.root.bind("<Escape>", self.hide_overlay)

        self._poll_job = self.root.after(80, self._poll_queues)

    # -- 窗口显示 ---------------------------------------------------------

    def _fit_and_place(self) -> None:
        """根据内容计算尺寸，并居中显示，避免高 DPI 下被屏幕边缘裁切。"""
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = max(360, min(WINDOW_WIDTH, screen_w - 80))
        self.body.configure(wraplength=width - 50)

        self.root.update_idletasks()
        height = self.root.winfo_reqheight()
        height = max(132, min(height, WINDOW_MAX_HEIGHT))

        x = max(12, (screen_w - width) // 2)
        y = max(12, (screen_h - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def show_text(self, text: str, *, loading: bool = False) -> None:
        self.body.configure(text=text, fg=FG)
        self.footer.configure(text="请求中 · 点击关闭" if loading else "点击关闭")
        self._fit_and_place()
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.lift()

    def show_demo(self) -> None:
        self.demo_mode = True
        self.show_text(
            "HAL_GPIO_TogglePin：切换指定 GPIO 引脚电平。\n"
            "HAL = Hardware Abstraction Layer（硬件抽象层）；\n"
            "GPIO = General Purpose Input/Output（通用输入输出）；\n"
            "Pin = 引脚。常用于 LED 闪烁。"
        )

    def hide_overlay(self, _event: tk.Event | None = None) -> None:
        # 使仍在途的请求结果失效，避免关闭后又突然弹出。
        self.active_request_id = None
        self.root.withdraw()
        if self.demo_mode or not self.hotkey_ready:
            self._shutdown()

    def _shutdown(self) -> None:
        if self._poll_job is not None:
            try:
                self.root.after_cancel(self._poll_job)
            except tk.TclError:
                pass
            self._poll_job = None
        self.root.destroy()

    # -- 快捷键与主循环 ---------------------------------------------------

    def register_hotkey(self) -> None:
        try:
            self._hotkey_handle = keyboard.add_hotkey(
                HOTKEY,
                lambda: self.events.put("hotkey"),
                suppress=False,
            )
            self.hotkey_ready = True
        except Exception as exc:  # keyboard 在部分系统上需要额外权限
            self.show_text(
                "快捷键注册失败。\n"
                "请尝试以管理员身份运行，或检查安全软件是否拦截键盘监听。\n"
                f"{type(exc).__name__}: {exc}"
            )

    def _poll_queues(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event == "hotkey":
                    self._handle_hotkey()
        except queue.Empty:
            pass

        try:
            while True:
                result = self.results.get_nowait()
                if result.request_id != self.active_request_id:
                    continue
                self.active_request_id = None
                self.show_text(result.text)
        except queue.Empty:
            pass

        self._poll_job = self.root.after(80, self._poll_queues)

    def _handle_hotkey(self) -> None:
        if not self.hotkey_ready:
            return

        now = time.monotonic()
        if now - self.last_hotkey_at < HOTKEY_DEBOUNCE_SECONDS:
            return
        self.last_hotkey_at = now

        try:
            code = pyperclip.paste()
        except Exception as exc:
            self.active_request_id = None
            self.show_text(f"读取剪贴板失败：{type(exc).__name__}\n{exc}")
            return

        code = str(code).replace("\x00", " ").strip()
        if not code:
            self.active_request_id = None
            self.show_text("剪贴板为空。\n请先复制一段 STM32 代码，再按 Alt+Q。")
            return

        api_key = get_api_key()
        if not api_key:
            self.active_request_id = None
            self.show_text(
                "未配置 DeepSeek API Key。\n"
                f"请编辑：{ENV_PATH}\n"
                "填写 DEEPSEEK_API_KEY=sk-... 后重启程序。"
            )
            return

        if len(code) > MAX_CODE_CHARS:
            code = code[:MAX_CODE_CHARS]

        self.request_seq += 1
        request_id = self.request_seq
        self.active_request_id = request_id
        self.show_text("正在翻译剪贴板中的代码…", loading=True)

        threading.Thread(
            target=self._translate_worker,
            args=(request_id, code, api_key),
            name=f"deepseek-{request_id}",
            daemon=True,
        ).start()

    # -- DeepSeek 请求（后台线程） ---------------------------------------

    def _translate_worker(self, request_id: int, code: str, api_key: str) -> None:
        try:
            client = OpenAI(
                api_key=api_key,
                base_url=BASE_URL,
                timeout=REQUEST_TIMEOUT_SECONDS,
                max_retries=1,
            )
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": build_system_prompt(code)},
                    {"role": "user", "content": "请按照上述格式回答。"},
                ],
                temperature=0.2,
                max_tokens=MAX_OUTPUT_TOKENS,
                stream=False,
            )
            content = response.choices[0].message.content
            text = content.strip() if content else ""
            if not text:
                text = "模型没有返回内容，请按 Alt+Q 重试。"
            self.results.put(TranslationResult(request_id, text))
        except Exception as exc:
            self.results.put(TranslationResult(request_id, friendly_api_error(exc)))

    def run(self) -> None:
        self.root.mainloop()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="STM32 极速翻译：复制代码后按 Alt+Q，使用 DeepSeek 生成简短解释。"
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="只预览悬浮窗效果，不监听快捷键、不调用 API；点击窗口退出。",
    )
    args = parser.parse_args()

    if sys.platform != "win32":
        print("提示：本工具主要面向 Windows；其他平台请自行确认 keyboard 权限。")

    app = TranslatorApp()
    if args.demo:
        app.show_demo()
        print("预览模式：点击悬浮窗退出。")
    else:
        app.register_hotkey()
        if app.hotkey_ready:
            print(f"已启动，正在监听 {HOTKEY.upper()}。按 Ctrl+C 退出。")
        else:
            print("快捷键注册失败，请查看屏幕上的提示。", file=sys.stderr)

    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
