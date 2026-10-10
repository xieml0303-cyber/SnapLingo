# SnapLingo

Windows 上的**截图 → 文字识别 → 翻译**一条龙工具。按一次全局热键框选屏幕，
识别出的文字可直接复制，也可以立刻看译文。

> **所有识别与翻译都在本机完成，不上传任何服务器。**
> 离线翻译模型随程序一同安装，截图与识别结果只保存在本机数据目录里。

## 功能

- **全局热键唤出截图**（默认 `Ctrl+D`），框选即识别，无需切窗口
- **OCR**：RapidOCR（PaddleOCR 模型转 ONNX，CPU 推理，中文识别质量好）
- **离线翻译**：sentencepiece 分词 + CTranslate2 推理，断网可用
- **在线翻译**（可选）：有道智云，需自备 AppKey / AppSecret
- **截屏标注**：画笔、色卡、线宽、矩形、箭头，支持撤销
- **系统托盘常驻**：关闭主窗口收进托盘，热键随时可用
- **开机自启**：可在设置窗口里开关

## 运行

需要 Windows 与 Python 3.10+。

```bash
py -3 -m pip install -r requirements.txt
py -3 main.py
```

首次运行会提示下载离线翻译模型。

## 目录结构

```
main.py              入口（含 --selftest 自检）
sctool/              全部功能代码
  capture.py         截屏
  ocr.py             文字识别
  translator.py      翻译（离线 / 在线）
  overlay.py         截图遮罩与标注
  ui.py / widgets.py / theme.py   界面与主题
assets/              图标与安装器素材
packaging/           打包配置（PyInstaller spec + Inno Setup iss）
```

## 打包

`packaging/SnapLingo.spec`（PyInstaller）+ `packaging/snaplingo.iss`（Inno Setup）。

## 许可

源码采用 [MIT License](LICENSE)。

安装程序另附最终用户许可协议，见 [`assets/license.txt`](assets/license.txt)。
