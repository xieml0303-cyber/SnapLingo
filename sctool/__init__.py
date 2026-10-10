"""截屏工具（ScreenshotTranslator）。

功能：框选截屏 → OCR 取字 → 中英翻译（离线/在线）→ 保存与历史。

模块划分：
    paths       路径策略（所有数据强制 ASCII 路径）
    config      配置读写
    capture     截屏与全屏框选（含 DPI 适配）
    ocr_engine  OCR 引擎（RapidOCR / Windows 内置）
    translator  翻译（轻量离线 CT2 + 在线 API）
    models      离线模型下载管理
    storage     保存与历史记录
    hotkey      全局热键
    icons       应用图标资源（托盘 / 窗口）
    ui          tkinter 界面（操作菜单 / 结果窗口 / 控制面板）
    app         主程序编排
"""

__version__ = "0.1.0"

#: 对外显示的软件名：托盘悬停提示、主窗口标题、启动失败弹窗都用它。
#: ⚠️ 别和 `paths.APP_NAME` 搞混 —— 那是**数据目录名**（`ScreenshotTranslator`），
#: 改了会让配置和已下载的模型全部失联，所以那个永远不动。
APP_TITLE = "SnapLingo"
