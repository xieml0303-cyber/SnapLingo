"""生成安装向导所需的图片素材（可反复迭代）。

设计基准：主人 2026-10-09 提供的设计稿
    标题栏高 46（100% DPI）/ 左栏宽 196（约占窗口 33%）/ 左栏深绿 #0F6E56
    左栏：白底圆角图标容器（内含**真实彩色**图标）→ "SnapLingo" → "截图 · 识别 · 翻译"
          → 空一段 → "安装步骤" → 4 个步骤；**全部在左栏内水平居中**
    右栏：标题 + 版本胶囊 + 副标题 + 3 张功能卡片 + 步数

⚠️ 为什么欢迎页左右两栏是**整块一张图**，而不是一堆小控件拼出来：
   Inno 的 `TNewStaticText` 实测**不理会 `Font.Color`** —— 把字设成红色，屏幕上
   依然渲染成纯黑（字号、粗细倒是照做）。深绿底上的白字/浅绿字因此根本显示不出来。
   既然文字上色不可控，索性把整块版式交给 Pillow 渲染成图片 —— 颜色、居中、
   字重全部 100% 可控，还省掉十几个控件的定位代码。
   代价：文案写死在图里，不能随语言切换（本安装器只有中文，可以接受）。

⚠️ 全部按 **2 倍**尺寸输出，Inno 里用 Stretch 缩到控件尺寸，高 DPI（本机 207%）下依然锐利。
⚠️ `TBitmapImage` 不支持透明合成，所以圆角外的部分直接填**该元素的背景色**。

产出（写入 assets/installer/）：
    left-1..4.png       左栏整块（第 1..4 步高亮），切页时切换
    welcome-right.png   欢迎页右栏整块（标题/胶囊/副标题/卡片/步数）
    btn-primary.png     主按钮（深绿圆角 + "下一步"）
    btn-ghost.png       次按钮（白底描边圆角 + "取消"）
    line.png            标题栏下方 1px 浅灰分隔线
    btn-close.png       标题栏关闭按钮（圆角方框 + ✕）
    wizard-large.png    Inno 编译期用的大图（纯深绿兜底）
    wizard-small.png    右上角小图 —— 设计稿右栏没有小图，做成隐形占位
    uninstall-badge.png 卸载进度窗体右上角徽标

用法：py -3 packaging/make_assets.py
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "assets" / "installer"
OUT.mkdir(parents=True, exist_ok=True)

ICON_256 = REPO / "assets" / "icon_256.png"

# 版本号 / 应用名从 .iss 里读，避免图片上的文案和安装包版本对不上
_ISS = (REPO / "packaging" / "snaplingo.iss").read_text(encoding="utf-8")


def _iss_define(key: str, default: str) -> str:
    m = re.search(r'#define\s+%s\s+"([^"]+)"' % key, _ISS)
    return m.group(1) if m else default


APP_NAME = _iss_define("AppName", "SnapLingo")
APP_VERSION = _iss_define("AppVersion", "0.0.0")

# ---- 品牌色 ----
GREEN = (0x0F, 0x6E, 0x56)        # 主深绿
GREEN_PALE = (0xE1, 0xF5, 0xEE)   # 胶囊底 / 卡片图标底
GREEN_SOFT = (0x8F, 0xC7, 0xB4)   # 左栏次要文字（标语 / 未激活步骤）
INK = (0x24, 0x2A, 0x28)          # 主文字
MUTED = (0x98, 0xA2, 0x9E)        # 次要文字（主人要求"颜色变浅"）
CARD_BORDER = (0xE6, 0xEA, 0xE8)
WHITE = (0xFF, 0xFF, 0xFF)

S = 2  # 统一 2 倍超采样

# ⚠️ 主人要求**所有字体都不加粗** —— 所以这里只用常规体（msyh.ttc），不再引 msyhbd
FONT_REG = r"C:\Windows\Fonts\msyh.ttc"

# 左栏 / 右栏的设计尺寸（100% DPI 逻辑像素）
LEFT_W, LEFT_H = 196, 465
# ⚠️ 右栏内容图的高度**必须避开窗口底部的按钮区**，见 make_welcome_step 的说明
RIGHT_W, RIGHT_H = 399, 392
STEP_W, STEP_H = 124, 26



def _font(size: int):
    try:
        return ImageFont.truetype(FONT_REG, size)
    except OSError:
        return ImageFont.load_default()


def _truecolor_glyph(size: int):
    """真实图标的**彩色原样**版（黑灰取景框 + 亮绿折角，白底）。"""
    if not ICON_256.exists():
        return None
    return Image.open(ICON_256).convert("RGBA").resize((size, size), Image.LANCZOS)


def _card_icon(name: str, size: int):
    """功能卡片图标 —— 由主人提供的三个 SVG 渲染而来（见 render_card_icons.py）。

    ⚠️ 素材是 168x168 的位图（Chrome 矢量渲染后按品牌绿重上色），这里缩到卡片
       里的实际显示尺寸。返回 None 表示素材缺失 —— 此时卡片只剩浅绿底块，
       不中断出图（渲染脚本没跑过时也能编译安装包）。
    """
    p = OUT / name
    if not p.exists():
        return None
    return Image.open(p).convert("RGBA").resize((size, size), Image.LANCZOS)


# ==========================================================================
#  1) 左栏整块（4 个版本，区别只在哪一步高亮）
# ==========================================================================
def make_left_panel(active: int) -> None:
    """左栏：深绿底 + 居中图标/字标/步骤列表，第 active 步高亮（0 基）。"""
    W, H = LEFT_W * S, LEFT_H * S
    im = Image.new("RGB", (W, H), GREEN)
    d = ImageDraw.Draw(im)
    cx = W // 2

    # 图标容器：白色圆角方块 + 真实彩色图标，**在左栏内水平居中**
    box = 58 * S
    ix, iy = (W - box) // 2, 30 * S
    d.rounded_rectangle((ix, iy, ix + box - 1, iy + box - 1),
                        radius=int(box * 0.26), fill=WHITE)
    g = _truecolor_glyph(int(box * 0.60))
    if g is not None:
        im.paste(g, (ix + (box - g.width) // 2, iy + (box - g.height) // 2), g)

    # 字标 / 标语 —— 居中，且都不加粗
    d.text((cx, 119 * S), APP_NAME, font=_font(26 * S), fill=WHITE, anchor="mm")
    d.text((cx, 150 * S), "截图 · 识别 · 翻译", font=_font(13 * S),
           fill=GREEN_SOFT, anchor="mm")

    # 「安装步骤」这个标题按主人 2026-10-09 的要求去掉了，步骤列表直接上来
    # （原位置 d.text((cx, 240 * S), "安装步骤", ...) 已删除）

    # 步骤列表：先量出「圆点 + 间距 + 最长名字」的总宽，把**整块**在栏内居中，
    # 行内保持左对齐 —— 这样圆点列在同一条竖线上，看起来才齐。
    names = ["欢迎", "许可协议", "安装位置", "完成"]
    f_name = _font(15 * S)
    dot, gap = 22 * S, 10 * S
    text_w = max(d.textlength(n, font=f_name) for n in names)
    bx = (W - (dot + gap + text_w)) / 2
    f_num = _font(int(dot * 0.60))

    for i, name in enumerate(names):
        y = (270 + i * 34) * S
        on = (i == active)
        cbox = (bx, y, bx + dot - 1, y + dot - 1)
        if on:
            d.ellipse(cbox, fill=WHITE)
            num_c = GREEN
        else:
            d.ellipse(cbox, outline=GREEN_SOFT, width=max(1, int(dot * 0.07)))
            num_c = GREEN_SOFT
        d.text((bx + dot / 2, y + dot / 2), str(i + 1), font=f_num,
               fill=num_c, anchor="mm")
        d.text((bx + dot + gap, y + dot / 2), name, font=f_name,
               fill=WHITE if on else GREEN_SOFT, anchor="lm")

    im.save(OUT / f"left-{active + 1}.png")
    print(f"  left-{active + 1}.png        {W}x{H}  (第 {active + 1} 步高亮)")


# ==========================================================================
#  2) 欢迎页右栏整块
# ==========================================================================
def make_welcome_right() -> None:
    W, H = RIGHT_W * S, RIGHT_H * S
    PAD = 34 * S
    CW = W - 2 * PAD
    im = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(im)

    # 标题 + 版本胶囊（胶囊紧跟标题右侧）
    f_t = _font(19 * S)
    title = f"欢迎使用 {APP_NAME} 安装向导"
    d.text((PAD, 56 * S), title, font=f_t, fill=INK, anchor="lm")
    tw = d.textlength(title, font=f_t)
    px, pw, ph, py = PAD + tw + 12 * S, 62 * S, 26 * S, 56 * S
    d.rounded_rectangle((px, py - ph / 2, px + pw - 1, py + ph / 2 - 1),
                        radius=int(ph / 2), fill=GREEN_PALE)
    d.text((px + pw / 2, py), f"v{APP_VERSION}", font=_font(12 * S),
           fill=GREEN, anchor="mm")

    # 副标题：两行，颜色比正文浅（主人点名要"变浅"）
    f_sub = _font(13 * S)
    for i, line in enumerate([
            f"即将在您的计算机上安装 {APP_NAME} {APP_VERSION}。",
            "建议在继续前关闭其他应用程序。"]):
        d.text((PAD, (96 + i * 22) * S), line, font=f_sub, fill=MUTED, anchor="lm")

    # 三张功能卡片（图标 = 主人提供的 SVG，渲染件见 render_card_icons.py）
    cards = [("card-shot.png", "一键截图", "框选即取，毫秒级响应"),
             ("card-text.png", "文字识别", "高精度 OCR，中英混排无忧"),
             ("card-globe.png", "即时翻译", "识别结果一键互译")]
    ch, gap, top = 62, 10, 148
    f_ct, f_cd = _font(15 * S), _font(13 * S)
    for i, (icon, t, desc) in enumerate(cards):
        y = (top + i * (ch + gap)) * S
        d.rounded_rectangle((PAD, y, PAD + CW - 1, y + ch * S - 1),
                            radius=14 * S, fill=WHITE,
                            outline=CARD_BORDER, width=max(1, int(1.2 * S)))
        ibox = 40 * S
        ix, iy = PAD + 14 * S, y + (ch * S - ibox) // 2
        d.rounded_rectangle((ix, iy, ix + ibox - 1, iy + ibox - 1),
                            radius=int(ibox * 0.28), fill=GREEN_PALE)
        # 图标占底块 62%（0.62 是预览图里试出来的观感比例），居中贴
        g = _card_icon(icon, int(ibox * 0.62))
        if g is not None:
            im.paste(g, (ix + (ibox - g.width) // 2,
                         iy + (ibox - g.height) // 2), g)
        tx = ix + ibox + 14 * S
        d.text((tx, y + 21 * S), t, font=f_ct, fill=INK, anchor="lm")
        d.text((tx, y + 43 * S), desc, font=f_cd, fill=MUTED, anchor="lm")

    # 「第 N 步，共 4 步」不画在这里 —— 它拆成单独一张图，见 make_welcome_step

    im.save(OUT / "welcome-right.png")
    print(f"  welcome-right.png   {W}x{H}")


def make_welcome_step() -> None:
    """「第 1 步，共 4 步」单独一张小图，摆在按钮左侧。

    ⚠️ 为什么从右栏大图里拆出来：右栏大图如果一直铺到窗口底部，就会连底部两个
       按钮的点击区一起盖住。TBitmapImage 是**图形控件**（没有自己的窗口句柄），
       点击由父窗口按 z-order 分发 —— 谁在上面谁吃掉事件，下面的按钮就永远收不到
       Click（实测：按钮日志里一条标记都没有，而没被盖住的 ✕ 是正常的）。
       让大图**物理上不压住按钮**，才是彻底解法。
    """
    W, H = STEP_W * S, STEP_H * S
    im = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(im)
    d.text((0, H / 2), "第 1 步，共 4 步", font=_font(13 * S), fill=MUTED, anchor="lm")
    im.save(OUT / "welcome-step.png")
    print(f"  welcome-step.png    {W}x{H}")


# ==========================================================================
#  3) 按钮（底色 + 文字一起画进去，反正文字没法用控件上色）
# ==========================================================================
def make_button(name: str, w: int, h: int, fill, outline, text: str,
                text_color, radius: int = 8) -> None:
    size = (w * S, h * S)
    im = Image.new("RGB", size, WHITE)          # 圆角外 = 窗口白底
    d = ImageDraw.Draw(im)
    box = (0, 0, size[0] - 1, size[1] - 1)
    if outline is None:
        d.rounded_rectangle(box, radius=radius * S, fill=fill)
    else:
        d.rounded_rectangle(box, radius=radius * S, fill=fill, outline=outline,
                            width=max(1, int(1.2 * S)))
    d.text((size[0] / 2, size[1] / 2), text, font=_font(15 * S),
           fill=text_color, anchor="mm")
    im.save(OUT / f"{name}.png")
    print(f"  {name}.png{'':<{max(0, 19 - len(name))}} {size[0]}x{size[1]}  (显示 {w}x{h})")


# ==========================================================================
#  4) 标题栏分隔线 / 关闭按钮 / Inno 编译期图片 / 卸载徽标
# ==========================================================================
def make_line() -> None:
    Image.new("RGB", (16 * S, S), CARD_BORDER).save(OUT / "line.png")
    print(f"  line.png            {16 * S}x{S}  (浅灰分隔线)")
    # 许可页阅读框的顶边线：**颜色必须和框自带的边线一致**。
    # 实测采样（主人截图）：框的左 / 右 / 下三条边都是 RGB(160,160,160) 的中灰，
    # 之前我用 (0xC8,0xCC,0xCA) 太浅，主人一眼就看出「和其他边框样式完全不同」。
    Image.new("RGB", (16 * S, S), (0xA0, 0xA0, 0xA0)).save(OUT / "line-frame.png")
    print(f"  line-frame.png      {16 * S}x{S}  (阅读框顶边，与框线同色 #A0A0A0)")


def make_close_btn(display: int = 30) -> None:
    size = display * S
    im = Image.new("RGB", (size, size), WHITE)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=int(display * 0.28 * S),
                        fill=WHITE, outline=(0xDA, 0xDF, 0xDD),
                        width=max(1, int(1.2 * S)))
    m, lw = size * 0.32, max(2, int(size * 0.055))
    ink = (0x4A, 0x50, 0x4E)
    d.line((m, m, size - m, size - m), fill=ink, width=lw)
    d.line((size - m, m, m, size - m), fill=ink, width=lw)
    im.save(OUT / "btn-close.png")
    print(f"  btn-close.png       {size}x{size}  (显示 {display})")


def make_left_backdrop(display_w: int = 202, display_h: int = 386) -> None:
    Image.new("RGB", (display_w * S, display_h * S), GREEN).save(
        OUT / "wizard-large.png")
    print(f"  wizard-large.png    {display_w * S}x{display_h * S}  (纯深绿兜底)")


def make_blank_small(display: int = 58) -> None:
    Image.new("RGB", (display * S, display * S), WHITE).save(OUT / "wizard-small.png")
    print(f"  wizard-small.png    {display * S}x{display * S}  (隐形占位)")


def make_uninstall_badge(display: int = 96) -> None:
    size = display * S
    im = Image.new("RGB", (size, size), WHITE)
    if ICON_256.exists():
        g = Image.open(ICON_256).convert("RGBA").resize((size, size), Image.LANCZOS)
        im.paste(g, (0, 0), g)
    im.save(OUT / "uninstall-badge.png")
    print(f"  uninstall-badge.png {size}x{size}")


def export_bmp(stems) -> None:
    """把要交给 Inno 的素材另存一份 BMP。

    ⚠️ Inno 脚本里给 TBitmapImage 加载图片，走 `Bitmap.LoadFromFile` 最稳。
       BMP 无透明通道 —— 无妨：圆角外已经填了背景色。
    """
    for s in stems:
        src = OUT / f"{s}.png"
        if src.exists():
            Image.open(src).convert("RGB").save(OUT / f"{s}.bmp", "BMP")
            print(f"  {s}.bmp")


def main() -> None:
    print(f"输出目录: {OUT}")
    print(f"读取版本: {APP_NAME} {APP_VERSION}\n")
    for i in range(4):
        make_left_panel(i)
    make_welcome_right()
    make_welcome_step()
    # 按钮：欢迎页是 [取消] [下一步]；第二页起统一成 [上一步] [下一步]
    # （主人 2026-10-09：保留图2 的样式与位置，把「取消」那格换成「上一步」）；
    # 完成页只剩一个 [完成]。「下一步」另有灰态版本，供许可页未勾同意时使用。
    make_button("btn-primary", 92, 36, GREEN, None, "下一步", WHITE)
    make_button("btn-next-off", 92, 36, (0xE6, 0xEA, 0xE8), None, "下一步",
                (0xA8, 0xB0, 0xAC))
    make_button("btn-ghost", 92, 36, WHITE, (0xC8, 0xCF, 0xCB), "取消", INK)
    make_button("btn-prev", 92, 36, WHITE, (0xC8, 0xCF, 0xCB), "上一步", INK)
    make_button("btn-finish", 92, 36, GREEN, None, "完成", WHITE)
    make_line()
    make_close_btn()
    make_left_backdrop()
    make_blank_small()
    make_uninstall_badge()

    print()
    export_bmp([
        "left-1", "left-2", "left-3", "left-4", "welcome-right", "welcome-step",
        "btn-primary", "btn-next-off", "btn-ghost", "btn-prev", "btn-finish",
        "line", "line-frame", "btn-close",
    ])
    print("\n素材已生成 ✓")


if __name__ == "__main__":
    main()
