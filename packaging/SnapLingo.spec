# -*- mode: python ; coding: utf-8 -*-
"""SnapLingo 正式打包 spec（PyInstaller onedir）。

用法（**必须在 packaging/ 目录下执行**，spec 里的相对路径是相对 CWD 的）：

    cd packaging
    py -3 -m PyInstaller --noconfirm --clean ^
        --distpath build/app --workpath build/appwork SnapLingo.spec

产物：`packaging/build/app/SnapLingo/`（`SnapLingo.exe` + `_internal/`）

⚠️ 与 `build/SnapLingo.spec`（**空壳版**）的区别：那份入口是
   `shell/snaplingo_shell.py`（只验安装器界面用），这份入口是项目根的
   `../main.py`（真实程序）。两份产物分别供「正式包」与「测试包」使用。

⚠️ 显式声明 `hiddenimports` 的原因：本项目大量使用**函数体内惰性导入**
   （见 `sctool/ocr_engine.py`、`translator.py`），目的是让"不用 OCR/翻译"
   的启动路径不必加载 40~60 MB 的原生库。PyInstaller 的字节码扫描能识别
   函数内 `import`，但对带原生 DLL 的包显式列出更稳妥。
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ==========================================================================
#  ⚠️⚠️ 绕过 PyInstaller 依赖预导入子进程的崩溃（2026-10-10 最终修正版）
#
#  `Analysis.assemble()` 调用 `find_binary_dependencies()`（build_main.py:134），
#  它在 Windows 上做两件事：
#    ① 开**隔离子进程**，把收集到的包**逐个 import**，记录各包动态注册的
#       DLL 搜索路径（`os.add_dll_directory` / 改 `PATH`）；
#    ② 调用 `binary_dependency_analysis(binaries, search_paths=...)`
#       —— **这才是真正分析依赖 DLL 的那一步**，返回值就是新的 binaries 列表。
#
#  ⚠️ 本机 ① 必然崩溃，而且是**多个包**都会触发（实测）：
#     · 第一轮崩在 `sentencepiece`（exit code 3221225477 = 0xC0000005）
#     · 只剔除 sentencepiece 后，第二轮崩在 `onnxruntime`
#     · 触发条件是「numpy 全家桶（OpenBLAS）已加载后再 import 这些原生库」
#     ⇒ 这是**隔离环境本身**的问题，逐个剔除包名治不了。
#     同样的 import 顺序在**主进程里完全正常**（已实测，19 个包全部 ok），
#     属构建期问题，与运行时无关。
#
#  ❌❌ 曾经两度写错，代价极大（装完一启动就弹 DLL load failed）：
#     · 写成 `lambda binaries, packages, symlink: []` —— 把 ① **和 ②** 一起跳过。
#       ② 一旦不跑，**所有**依赖分析都白做：`DLLs\` 下的
#       libffi-8.dll / libcrypto-3.dll / libssl-3.dll / sqlite3.dll / zlib1.dll /
#       tcl86t.dll / tk86t.dll **全部没被打包**。
#       症状：`_tkinter`、`_ctypes`、`cv2`、`mss`、`pystray`、`ctranslate2`
#       接连报「DLL load failed」，程序根本起不来。
#     · 只剔除 sentencepiece 一个包 —— 下一个包（onnxruntime）照样崩。
#
#  ✅ 最终做法：**复刻该函数，跳过 ①，保留 ②**，并把 ① 本该拿到的搜索路径
#     **手工补上**（这些路径已在本机实测得出，见下）。
# ==========================================================================
import PyInstaller.building.build_main as _pi_build_main
from PyInstaller import compat as _pi_compat
from PyInstaller.depend import bindepend as _pi_bindepend


def _find_binary_dependencies(binaries, import_packages, symlink_suppression_patterns):
    """跳过会崩的「逐包预导入」，其余照 PyInstaller 原逻辑执行。

    ⚠️⚠️ **最后那句 `binary_dependency_analysis()` 绝不能省** —— 它才是真正
    分析依赖 DLL 的一步（会在被分析二进制**所在目录**找依赖，所以与
    `_ctypes.pyd` 同在 `DLLs\` 的 `libffi-8.dll` 本来能被找到）。
    """
    import os
    import sys
    from pathlib import Path

    extra_libdirs = []
    if _pi_compat.is_win:
        # PyInstaller 原本就会加的两条（保证 python3X.dll / python3.dll 解析正确）
        extra_libdirs.append(_pi_compat.base_prefix)
        extra_libdirs.append(
            os.path.dirname(getattr(sys, "_base_executable", sys.executable))
        )
        # 下面这些是「跳过预导入」后手工补回来的（2026-10-10 在本机实测得出）：
        site_packages = Path(_pi_compat.base_prefix) / "Lib" / "site-packages"
        extra_libdirs += [
            # ⚠️ Python 自己的运行库目录。主进程靠默认搜索路径就能找到它们，
            #    但打包时的依赖分析**不会**，必须显式加：
            #    libffi-8.dll（_ctypes 依赖）/ libcrypto-3 / libssl-3（_ssl）/
            #    sqlite3.dll / zlib1.dll / tcl86t.dll + tk86t.dll（_tkinter）
            str(Path(_pi_compat.base_prefix) / "DLLs"),
            # 以下三条来自实测的 add_dll_directory 记录（numpy / ctranslate2 /
            # rapidocr_onnxruntime 各自注册的）
            str(site_packages / "numpy.libs"),
            str(site_packages / "ctranslate2"),
            str(site_packages / "_rocm_sdk_core" / "bin"),
            str(site_packages / "x64" / "vc17" / "bin"),
        ]

    # 去重但保序（PyInstaller 原实现也是这么处理的，顺序有意义）
    extra_libdirs = list(dict.fromkeys(p for p in extra_libdirs if p))

    return _pi_bindepend.binary_dependency_analysis(
        binaries,
        search_paths=extra_libdirs,
        symlink_suppression_patterns=symlink_suppression_patterns,
    )


_pi_build_main.find_binary_dependencies = _find_binary_dependencies

APP_NAME = "SnapLingo"

#: 惰性导入的包（缺一个就会在"用到该功能时"才崩，很难查）
hiddenimports = [
    "onnxruntime",
    "ctranslate2",
    "sentencepiece",
    "pystray",
    "pystray._win32",
    "pyperclip",
    # Windows 内置 OCR 备选引擎（主人要求保留；默认配置不用，但功能要能切）
    "winrt.windows.globalization",
    "winrt.windows.media.ocr",
    "winrt.windows.graphics.imaging",
    "winrt.windows.storage.streams",
    "winrt.windows.foundation",
    "winrt.windows.foundation.collections",
]

# ⚠️⚠️ rapidocr_onnxruntime 必须用 collect_submodules 收**全部子模块**，
#     只写顶层包名不够（2026-10-10 实测踩到）。
#     它的算子模块 `ch_ppocr_v3_det` / `ch_ppocr_v3_rec` / `ch_ppocr_v2_cls`
#     是**动态 import** 加载的，PyInstaller 的静态扫描只看得见顶层包名，
#     子模块一个都不进产物。
#     症状：程序能启动，一用 OCR 就报
#       AttributeError: module 'ch_ppocr_v3_det' has no attribute 'TextDetector'
#     —— 那个模块被当成**空壳**导入了（能找到名字，里面什么都没有）。
hiddenimports += collect_submodules("rapidocr_onnxruntime")

#: ⚠️ 这台机器的 site-packages 里躺着 871 MB 与本项目**无关**的包
#: （torch 501.7 / spacy 92.2 / pandas / matplotlib / sympy …，是早期试探
#: argostranslate 留下的污染）。它们不在任何 import 链上，PyInstaller 不会
#: 自动打包；这里显式排除是为了**万无一失** —— 一旦某个 hook 手滑把它们拉
#: 进来，包会从 300 MB 直接炸到 1 GB。
#:
#: ⚠️ **绝不能排除 `cv2`**：它是 `rapidocr_onnxruntime` 做图像预处理的必需
#: 传递依赖（虽然本项目代码零直接 import 它）。排掉它 OCR 会直接报错。
excludes = [
    "torch",
    "spacy",
    "stanza",
    "argostranslate",
    "pandas",
    "matplotlib",
    "scipy",
    "sympy",
    "IPython",
    "notebook",
    "tkinter.test",
    "test",
    "unittest",
]

#: 只带程序运行真正需要的图标，**不带** `assets/installer/`（那是安装器自绘
#: 素材，约 4.7 MB，属于安装包而非程序本体）。
#: ⚠️ dest 必须是 `assets`：`icons.asset_dir()` 找的是 `sys._MEIPASS/assets`。
_ICON_FILES = ["icon.ico", "icon.png"] + [
    f"icon_{n}.png" for n in (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
]
datas = [(f"../assets/{name}", "assets") for name in _ICON_FILES]
# rapidocr 包内的 3 个 ONNX 模型（det 2.32 + rec 10.20 + cls 0.56 MB）
datas += collect_data_files("rapidocr_onnxruntime")

a = Analysis(
    ["../main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # ⚠️ 不用 UPX：压过的原生 DLL（onnxruntime / ctranslate2）会显著抬高杀软
    #    误报率，而"截屏 + 全局键盘钩子"本来就是杀软的重点关照对象。
    upx=False,
    console=False,          # 无控制台；崩溃信息写 %LOCALAPPDATA%\...\app.log
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="../assets/icon.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
