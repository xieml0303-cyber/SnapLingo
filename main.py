"""入口脚本。

两种启动方式都支持：
    py -3 main.py      （带控制台，调试用）
    pyw -3 main.py     （无控制台，日常用）

⚠️ 绝不要用裸 `pythonw.exe main.py`：本机 PATH 里 hermes-agent 的 venv 抢先
劫持了 `pythonw`，那个 venv 没装 mss，会静默失败（pythonw 无控制台，错误看不见）。
用 py launcher（py/pyw）按注册表挑解释器才可靠。

这里兜住所有启动异常：写日志 + 弹窗，避免再次出现"双击没反应、不知道为啥"。
"""

from __future__ import annotations

import sys
import traceback


def _crash_log_path() -> str:
    import os
    from pathlib import Path

    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    directory = Path(base) / "ScreenshotTranslator"
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory / "app.log")


def _log_only(text: str) -> None:
    """只写日志，**不弹窗**。

    ⚠️ 安装器/卸载器调用 `--set-autostart` 时必须走这条路径：那种场景下弹一个
    模态框会把安装流程**卡死**（用户正在装软件，不该看到我们的报错框）。
    """
    try:
        with open(_crash_log_path(), "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except OSError:
        pass


def _report_crash(text: str) -> None:
    _log_only(text)

    # pythonw 下没有控制台，必须弹窗，否则用户什么也看不到
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        # 崩溃弹窗也带上图标。⚠️ 整段包 try：崩的原因很可能就是 sctool 导不进来。
        try:
            from sctool import icons

            icons.apply_tk_icon(root)
        except Exception:  # noqa: BLE001
            pass
        # 软件名在这里写死，不 import sctool.APP_TITLE —— 同上，本函数必须自包含
        messagebox.showerror(
            "SnapLingo —— 启动失败",
            f"{text[-900:]}\n\n完整日志：{_crash_log_path()}",
        )
        root.destroy()
    except Exception:  # noqa: BLE001 - 连弹窗都失败就只能靠日志
        pass


def _selftest() -> int:
    """自检：验证**打包产物**里各功能模块能否真正加载并工作。

    ⚠️⚠️ 为什么需要这条命令（2026-10-10 加的，起因是一次事故）：
      本项目大量使用**函数体内惰性导入**（见 sctool/ocr_engine.py、translator.py），
      目的是让"不用 OCR / 翻译"的启动路径不必加载 40~60 MB 的原生库。
      后果是：「程序能启动」**完全不能证明** OCR 与翻译可用。
      而正常验证要么按全局热键（自动化里**禁止注入全局按键**）、要么点 GUI
      （没法自动点），于是打包后真正该验的东西反而没人验 —— 曾经因此把
      「`_tkinter` 的 DLL 没打包进去」这种致命缺陷放了过去。

    加这条命令后，打包产物可以**自己证明自己**：

        SnapLingo.exe --selftest      # 结果写 app.log；退出码 0 = 全过，1 = 有失败

    每一项都跑**真实工作负载**（真抓一屏、真识别一张造出来的图、真翻一句话），
    不是 import 一下就放行。
    """
    import time

    lines: list[str] = []

    def run(name: str, func) -> bool:
        start = time.time()
        try:
            detail = func()
            lines.append("  [OK]   %-12s %6.2fs  %s" % (name, time.time() - start, detail))
            return True
        except Exception:  # noqa: BLE001 - 自检要的是"继续跑完剩下几项"
            lines.append("  [FAIL] %-12s %6.2fs\n%s"
                         % (name, time.time() - start, traceback.format_exc(limit=4)))
            return False

    def check_tk() -> str:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        try:
            version = root.tk.call("info", "patchlevel")
        finally:
            root.destroy()
        return "Tcl/Tk %s" % version

    def check_capture() -> str:
        import mss
        from PIL import Image

        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[0])
            image = Image.frombytes("RGB", shot.size, shot.rgb)
        return "抓屏 %dx%d" % image.size

    def check_ocr() -> str:
        from PIL import Image, ImageDraw, ImageFont

        from sctool import ocr_engine

        # 造一张有字的图，跑**真实识别**（比 import 一下有意义得多）
        image = Image.new("RGB", (380, 90), "white")
        draw = ImageDraw.Draw(image)
        try:
            font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 44)
        except OSError:
            font = ImageFont.load_default()
        draw.text((12, 16), "HELLO 123", font=font, fill="black")

        engine = ocr_engine.create_engine("rapidocr")
        text = ocr_engine.lines_to_text(engine.recognize(image)).strip()
        if not text:
            raise RuntimeError("识别结果为空 —— 引擎能加载但没出结果")
        return "识别到 %r" % text[:40]

    def check_translate() -> str:
        from sctool import models, paths, translator

        pairs = models.installed_pairs()
        if not pairs:
            raise RuntimeError("没装任何离线模型（%s 为空）" % paths.models_dir())
        pair = "en_zh" if "en_zh" in pairs else pairs[0]
        engine = translator.get_offline_translator(pair)
        result = str(engine.translate("Hello, how are you?")).strip()
        if not result:
            raise RuntimeError("翻译结果为空")
        return "%s → %r" % (pair, result[:40])

    def check_tray() -> str:
        import pystray
        import pystray._win32  # noqa: F401 - 确认后端能加载

        return "pystray %s" % getattr(pystray, "__version__", "?")

    ok = True
    lines.append("=== SnapLingo 自检（--selftest）===")
    lines.append("  运行方式: %s" % ("打包版 (frozen)" if getattr(sys, "frozen", False) else "源码版"))
    for name, func in (("tkinter", check_tk), ("截屏", check_capture), ("OCR", check_ocr),
                       ("离线翻译", check_translate), ("托盘", check_tray)):
        ok = run(name, func) and ok
    lines.append("=== %s ===" % ("全部通过" if ok else "有失败项"))

    report = "\n".join(lines)
    _log_only(report)
    try:
        print(report)
    except Exception:  # noqa: BLE001 - 打包版 console=False，没有 stdout
        pass
    return 0 if ok else 1


def _handle_cli(argv: list[str]) -> int | None:
    """处理安装器 / 卸载器调用的命令行开关。

    返回 `None` = 继续正常启动；返回 `int` = **立即以该退出码结束**。

    ⚠️ 为什么必须"设置完立刻退出、不建任何窗口"：安装脚本里这条命令带着
       `Flags: waituntilterminated`，安装器会一直等这个进程结束 —— 要是它顺手
       把 GUI 拉起来，安装流程会**永久卡在"配置开机自启…"**。
    ⚠️ 失败时不弹窗（同上），只写日志 + 返回非 0；安装器据此可判断成败。
    """
    if "--selftest" in argv:
        return _selftest()

    if "--set-autostart" not in argv:
        return None

    index = argv.index("--set-autostart")
    value = argv[index + 1].strip().lower() if index + 1 < len(argv) else ""
    if value not in ("on", "off"):
        _log_only("--set-autostart 需要 on 或 off 参数")
        return 2

    try:
        from sctool import autostart, config

        actual = autostart.set_enabled(value == "on")
        # 注册表是权威来源，但配置里也留一份"用户最后一次意图"，
        # 否则设置窗口里的开关会与实际情况对不上（见 config.DEFAULTS 的注释）。
        cfg = config.load()
        cfg["autostart"] = actual
        config.save(cfg)
    except Exception:  # noqa: BLE001
        _log_only(traceback.format_exc())
        return 1
    return 0


def main() -> None:
    # 安装器/卸载器调用（--set-autostart）：设置完立即退出，不建任何窗口。
    # ⚠️ 必须在单实例逻辑**之前**处理 —— 否则会去强杀正在运行的程序，
    #    而安装/卸载期的进程生命周期由安装脚本自己负责（[Run] / [UninstallRun]）。
    code = _handle_cli(sys.argv[1:])
    if code is not None:
        raise SystemExit(code)

    # 单实例保护单独兜异常：它只是锦上添花，**绝不该挡住程序启动**。
    # 曾经因为 tasklist 输出解析（result.stdout 为 None）崩在这里，表现是
    # "双击 启动.bat 没反应"，而旧实例还在跑旧代码 —— 看起来就是"改了没生效"。
    try:
        from sctool import single_instance

        # 先结束上一个实例：否则旧实例占着热键，按热键触发的还是旧代码
        single_instance.replace_previous()
        single_instance.claim()
    except Exception:  # noqa: BLE001
        pass

    try:
        from sctool.app import App

        App().run()
    except BaseException:  # noqa: BLE001 - 兜住一切，包括 SystemExit
        _report_crash(traceback.format_exc())
        raise
    finally:
        try:
            from sctool import single_instance

            single_instance.release()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    main()
