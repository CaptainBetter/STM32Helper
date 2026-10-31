# STM32 极速翻译

复制一段 STM32 C 代码，按 `Alt+Q`，通过 DeepSeek 在无边框悬浮窗中查看 150 字以内的结构化解释（作用、英文拆解、参数解析、调用示例）。
*误区说明：要先ctrl+C，再ALT+Q
## 功能

- 全局快捷键 `Alt+Q`
- 自动读取剪贴板
- DeepSeek `deepseek-chat` 模型
- 黑底绿字、置顶、无边框悬浮窗
- 点击悬浮窗关闭；监听程序继续运行
- API Key 只从 `.env` 或系统环境变量读取

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `main.py` | 主程序 |
| `.env` | 本地 API Key（已被 Git 忽略，不要提交） |
| `.env.example` | API Key 配置模板 |
| `.gitignore` | 屏蔽 `.env`、虚拟环境和缓存 |
| `requirements.txt` | Python 依赖 |

## 首次运行

1. 打开 [DeepSeek 开放平台](https://platform.deepseek.com/api_keys) 创建 API Key。
2. 编辑 `.env`，填入 Key：

   ```env
   DEEPSEEK_API_KEY=sk-你的Key
   ```

3. 启动程序：

   ```powershell
   .\.venv\Scripts\python.exe .\main.py
   ```

看到“已启动，正在监听 ALT+Q”后：

1. 复制一段 STM32 代码；
2. 按 `Alt+Q`；
3. 查看悬浮窗，点击关闭。

## 预览界面

不调用 API、不监听快捷键，只预览悬浮窗样式：

```powershell
.\.venv\Scripts\python.exe .\main.py --demo
```

点击悬浮窗退出预览。

## 重新安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 退出与排查

- 点击悬浮窗只会关闭窗口，程序仍在后台监听。请在启动它的终端按 `Ctrl+C` 退出。
- 如果快捷键注册失败，尝试以管理员身份运行；部分安全软件会拦截全局键盘监听。
- 使用 `pythonw.exe` 启动可隐藏控制台，但退出时需要用任务管理器结束进程。
- `.env` 修改后需要重启程序才会生效。

## 安全

`.env` 已加入 `.gitignore`。上传 GitHub 前可用下面的命令确认它没有被跟踪：

```powershell
git status --short
```

如果 Key 曾经被提交过，请立即在 DeepSeek 控制台吊销并重新生成。
