# -*- coding: utf-8 -*-
"""生成「卸载询问窗体」的素材（对照主人 2026-10-09 的设计稿）。

设计稿规格按 **1x 逻辑像素**写（540 x 476 等）；实际输出尺寸再乘 SX/SY
（卸载器自定义窗体的对话框字体缩放，实测 1.162963 / 1.214286，详见下方常量注释），
这样 Inno 把素材铺到 Bg 控件上时正好 1:1，不会被 Stretch 二次缩放而发虚。

    窗体 540x486，白底、圆角
    ├ 标题栏  高 40，底部 1px #D9D9D9
    │   ├ 真实图标 (16,13) 14x14
    │   ├ 标题 x=38 垂直居中，#1A1A1A 15px
    │   └ ✕   (500,7) 26x26 圆角7 描边 #D9D9D9
    ├ 图标    (24,56) 36x36 —— **真实 app 图标**（assets/icon_128.png）
    ├ 头部标题 x=72 y=58  16px #1A1A1A
    ├ 头部说明 x=72 y=82  13px #666666 两行
    ├ 4 张卡片 x=24 w=492 h=50 圆角8 边框 #D9D9D9
    │     y = 130 / 188 / 246 / 304（间距 8）
    │     ├ 勾选框 卡内 (14,18) 15x15 —— **单独出图**（要点击切换）
    │     ├ 主文字 卡内 x=40 y=9   15px #1A1A1A
    │     ├ 副文字 卡内 x=40 y=27  13px #666666
    │     └ 体积   右对齐（右边距 20）13px #999999
    │     卡片3 主文字右侧还有橙胶囊：底 #FAE8D0、字 #854F0B
    ├ 警示条  (24,368) 492x34 圆角8 底 #FCEBEB + 红三角 + 红字 #A32D2D
    ├ 分隔线  y=424  #D9D9D9
    ├ 底部小字 (24,444) 13px #999999
    └ 两个按钮 —— **单独出图**（要点击）
         取消     (358,438) 62x30 白底 描边 #545454 字 #1A1A1A
         继续卸载 (430,438) 86x30 底 #A32D2D 白字

⚠️ 为什么整窗一张背景图：Inno 的 `TNewStaticText` **不理会 Font.Color**
   （灰字/红字/橙字都渲染不出来），`TPanel` 的 Color **不会被绘制**。
   与其跟这两个限制缠斗，不如把静态部分整块交给 Pillow 渲染，
   只留真正需要交互的 4 个勾选框 + 2 个按钮 + ✕ 做独立图片叠上去。

⚠️ 为什么不用 rounded_rectangle 的 outline 画描边：Pillow 把圆角和直边分成两笔
   （4 个 pieslice + 4 条线）画，width=1 时衔接处容易留缝。统一改用 rr_stroke
   （两层实心填充）。
⚠️ rr() 里的 -1：Pillow 的 rounded_rectangle 端点 x1/y1 是**包含**在绘制范围内的。
   不减 1 的话，rr_stroke 的内圈会把外圈最右列 / 最下行压成底色 —— 实测就是
   「取消按钮右边框、底边框断开」（底边白段 46px、右边白段 14px）。
"""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "assets", "installer"))
ICON_SRC = os.path.normpath(os.path.join(HERE, "..", "assets", "icon_128.png"))
os.makedirs(OUT, exist_ok=True)

# ⚠️⚠️ 素材的最终像素尺寸必须**等于 Inno 最终显示的像素**，否则 TBitmapImage.Stretch
#     会再缩放一次，文字发虚。
#
#     SX / SY 从哪来 —— 卸载器自定义窗体的**对话框字体**缩放因子：
#       Inno 文档：ScaleX「按当前对话框字体缩放；用默认字体 + 100% DPI 时原样返回」。
#       本机实测（2026-10-09，computer-use 插件读屏，跑测试包的真实卸载器）：
#         窗体物理尺寸 628 x 578，设计尺寸 540 x 476
#         ⇒ SX = 628/540 = 1.162963，SY = 578/476 = 1.214286
#       ⚠️ 这**不是** DPI 缩放：本机屏幕 DPI 实测就是 96（100%）。它来自对话框字体
#          与 Inno 设计字体（Tahoma 8pt）的度量差，所以 X 与 Y 不相等。
#       ⚠️ 与**安装向导**的 ScaleX 不是一回事：探针 packaging/probe/scale_probe4.iss
#          在 WizardForm 上读到 ScaleX(1000)=1000（因子 1.000）。两个 exe
#          （Setup.exe 与 unins000.exe）的字体基准不同，别把一边的数搬到另一边。
#          同一份脚本里 CreateCustomForm 的注释也警告过「内部 DPI 倍率与 ScaleX 不一致」。
#       ⚠️ 换机器（改过系统字体 / 文本缩放）这两个值会变，需重测：
#          跑一次卸载器，量窗口的物理尺寸，除以 540 x 476 即可。
S = 2                            # 超采样倍率（只影响渲染精度，不影响输出尺寸）
SX, SY = 1.162963, 1.214286      # 卸载器自定义窗体的实测缩放倍率（见上）

# ---- 配色（取自设计稿实测）----
INK = (0x1A, 0x1A, 0x1A)        # 主文字
GRAY = (0x66, 0x66, 0x66)       # 次要文字
FAINT = (0x99, 0x99, 0x99)      # 体积 / 底部小字
LINE = (0xD9, 0xD9, 0xD9)       # 卡片边框 / 分隔线 / ✕ 描边
GREEN = (0x0F, 0x6E, 0x56)      # 品牌深绿（仅兜底，图标已换真图）
RED = (0xA3, 0x2D, 0x2D)        # 警示红（勾选框 / 按钮 / 警示字）
RED_BG = (0xFC, 0xEB, 0xEB)     # 警示条底
ORANGE_TX = (0x85, 0x4F, 0x0B)  # 橙胶囊文字
ORANGE_BG = (0xFA, 0xE8, 0xD0)  # 橙胶囊底
BTN_BORDER = (0x54, 0x54, 0x54)  # 取消按钮描边
CHK_BORDER = (0xBB, 0xBB, 0xBB)  # 未勾选时的框线
WHITE = (0xFF, 0xFF, 0xFF)

FONT = r"C:\Windows\Fonts\msyh.ttc"

# ---- 布局（逻辑像素 == 物理像素）----
W, H = 540, 476
PAD = 24
CARD_X, CARD_W, CARD_H = 24, 492, 50
CARD_Y = [130, 188, 246, 304]
TITLEBAR_H = 40
TB_ICON_X, TB_ICON_Y, TB_ICON_S = 16, 13, 14      # 标题栏小图标
ICON_X, ICON_Y, ICON_S = 24, 56, 36               # 头部大图标
HEAD_TITLE_Y = 58
HEAD_DESC_Y = 82
WARN_X, WARN_Y, WARN_W, WARN_H = 24, 368, 492, 34
SEP_Y = 424
FOOT_X, FOOT_Y = 24, 446
BTN_Y, BTN_H = 438, 30
CANCEL_X, CANCEL_W = 358, 62
OK_X, OK_W = 430, 86
CLOSE_X, CLOSE_Y, CLOSE_S = 500, 7, 26
CHK_X, CHK_Y, CHK_S = 14, 18, 15      # 卡内勾选框
TXT_X = 40                             # 卡内文字 x
VOL_RIGHT = 20                         # 卡内体积右边距

# ---- 4 个候选项的静态文案（与设计稿一致）----
# ⚠️⚠️ 2026-10-09 起**体积与动态数量一律留白**，由安装脚本在运行时用
#     TNewStaticText 画真实值（见 snaplingo.iss 的 RefreshUninstallTexts）。
#     当初把整块文字烘进图片，是因为误以为 TNewStaticText 不认 Font.Color；
#     探针 scale_probe5.iss 已证明**颜色/粗体都正常**（灰 #999、红 #A32D2D、
#     绿 #0CAF76 全部正确渲染，且各控件的 Font 互不影响），
#     所以动态部分改回控件绘制，素材只管静态部分。
#
#     ITEMS 的 4 个字段依次是：主文字 / 副文字 / 体积 / 橙胶囊。
#     副文字为空 = 该行整行由脚本画（历史截图的「N 张 PNG」数量会变）。
#     体积一律 None = 素材不画，运行时按真实磁盘占用画。
ITEMS = [
    ("配置文件", "热键 / 引擎 / 翻译模式", None, None),
    ("历史截图", "", None, None),
    ("离线翻译模型", "默认保留，重装后可直接使用", None, "重新下载较慢"),
    ("运行日志", "排查用日志文件", None, None),
]
MODEL_IDX = 2   # 哪一项是"离线翻译模型"（决定警示条里的体积）


def font(px_):
    try:
        return ImageFont.truetype(FONT, px_ * S)
    except OSError:
        return ImageFont.load_default()


def font_phys(px_):
    """按**最终像素**取字体 —— 只给 make_preview 用。

    make_bg 那些走的是 S 倍超采样画布，所以用 font()（字号也乘 S）；
    而预览图是把 finish() 缩过的素材拼起来的，已经是 1:1 最终像素，
    再乘 S 字就大一倍。
    """
    try:
        return ImageFont.truetype(FONT, px_)
    except OSError:
        return ImageFont.load_default()


def px(v):
    return int(round(v * S))


def finish(im, lw, lh):
    """把 S 倍超采样的图缩到「Inno 缩放后的物理尺寸」，让 Stretch 变成 1:1。

    ⚠️ 这是「字体糊」的解法：素材尺寸必须落在 Inno 最终显示的像素上，
       否则 TBitmapImage.Stretch 会把它再缩放一次，文字就发虚。
    """
    return im.resize((int(round(lw * SX)), int(round(lh * SY))), Image.LANCZOS)


def rr(d, box, r, fill=None, outline=None, width=1):
    """圆角矩形。box = (x0, y0, x1, y1) 的语义是「占 [x0,x1) x [y0,y1)」，即 x1/y1 是**尺寸**。

    ⚠️⚠️ Pillow 的 rounded_rectangle 端点 x1/y1 是**包含**在绘制范围内的，所以这里
       统一减 1，画出来才是「宽 = x1-x0」。
       不减的后果分两种：实心块会宽 1px（越界部分被裁，几乎看不出）；
       但 rr_stroke 的内圈会正好压掉外圈的最右列 / 最下行 —— 那就是主人报的
       「取消按钮右边框断开」的根因（实测：底边白段 46px、右边白段 14px）。
    """
    b = [px(box[0]), px(box[1]), px(box[2]) - 1, px(box[3]) - 1]
    d.rounded_rectangle(b, radius=px(r), fill=fill, outline=outline,
                        width=max(1, px(width)))


def rr_stroke(d, box, r, stroke, fill=WHITE, w=1):
    """1px 描边的圆角矩形 —— 外圈填描边色、内缩 w 再填底色。

    ⚠️ 不要图省事用 rr(..., outline=...)：Pillow 把圆角和直边分成两笔画
       （4 个 pieslice + 4 条线），width=1 时衔接处容易留缝。
       两层实心填充出来的描边一定连续。
    ⚠️ 内外圈的圆角中心是重合的（外圈 x0+r，内圈 x0+w+(r-w)），所以环宽恒为 w。
    """
    x0, y0, x1, y1 = box
    rr(d, (x0, y0, x1, y1), r, fill=stroke)
    rr(d, (x0 + w, y0 + w, x1 - w, y1 - w), max(1, r - w), fill=fill)


def text(d, xy, s, f, color, anchor="la"):
    d.text((px(xy[0]), px(xy[1])), s, font=f, fill=color, anchor=anchor)


def wrap_cjk(d, s, f, maxw):
    """按可用宽度折行。中文可以逐字断，不需要分词。"""
    out, cur = [], ""
    for ch in s:
        if cur and d.textlength(cur + ch, font=f) / S > maxw:
            out.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def load_icon(size):
    """真实 app 图标，缩放到目标边长（保留 alpha，用自身 alpha 作 mask 贴）。"""
    src = Image.open(ICON_SRC).convert("RGBA")
    return src.resize((px(size), px(size)), Image.LANCZOS)


def draw_warn_icon(d, x, y, s, color=RED):
    """红色三角警告图标。"""
    lw = max(1, int(1.5 * S))
    d.polygon([(px(x + s / 2), px(y)), (px(x + s), px(y + s * 0.92)),
               (px(x), px(y + s * 0.92))], outline=color, width=lw)
    # 感叹号
    d.line([px(x + s / 2), px(y + s * 0.34), px(x + s / 2), px(y + s * 0.62)],
           fill=color, width=max(1, int(1.6 * S)))
    d.ellipse([px(x + s / 2 - s * 0.05), px(y + s * 0.70),
               px(x + s / 2 + s * 0.05), px(y + s * 0.80)], fill=color)


# ==========================================================================
#  1) 背景大图：标题栏 + 图标 + 头部文字 + 4 张卡片 + 胶囊 + 警示条 + 分隔线 + 底部小字
#     （勾选框 / 按钮 / ✕ 的位置留白，由独立图片叠上去）
# ==========================================================================
def make_bg():
    im = Image.new("RGB", (px(W), px(H)), WHITE)
    d = ImageDraw.Draw(im)

    # ---- 标题栏 ----
    ic = load_icon(TB_ICON_S)
    im.paste(ic, (px(TB_ICON_X), px(TB_ICON_Y)), ic)                # 真实图标
    text(d, (38, TITLEBAR_H / 2), "卸载 SnapLingo", font(15), INK, "lm")
    d.line([px(0), px(TITLEBAR_H - 1), px(W), px(TITLEBAR_H - 1)],
           fill=LINE, width=max(1, S))                              # 底部 1px

    # ---- 图标 + 头部标题 + 说明 ----
    ic = load_icon(ICON_S)
    im.paste(ic, (px(ICON_X), px(ICON_Y)), ic)                      # 真实图标
    text(d, (ICON_X + ICON_S + 12, HEAD_TITLE_Y), "卸载前，选择要清理的数据",
         font(16), INK)
    # ⚠️ 说明文字必须**按宽度自动折行**：手写死两行时第一行超宽，右边整段被裁掉
    #    （实测踩过）。这里按内容区实际宽度折，行数随字号自然变化。
    # ⚠️ 2026-10-10 主人改定「默认全部不勾选」后，这段文案同步反转 ——
    #    原文写的是"默认随卸载一并删除；取消勾选即可保留"，与新的默认行为相反。
    desc = ("程序本体将被移除。以下数据不在程序目录内，默认全部保留；"
            "勾选后随卸载删除且不可恢复。")
    dx = ICON_X + ICON_S + 12
    dw = W - dx - PAD
    f_desc = font(13)
    lines = wrap_cjk(d, desc, f_desc, dw)
    if len(lines) > 2:                      # 放不下两行就缩一档
        f_desc = font(12)
        lines = wrap_cjk(d, desc, f_desc, dw)
    for k, ln in enumerate(lines[:2]):
        text(d, (dx, HEAD_DESC_Y + k * 18), ln, f_desc, GRAY)

    # ---- 4 张卡片 ----
    f_main, f_sub, f_vol = font(15), font(13), font(13)
    for i, (main, sub, vol, pill) in enumerate(ITEMS):
        y0 = CARD_Y[i]
        rr_stroke(d, (CARD_X, y0, CARD_X + CARD_W, y0 + CARD_H), 8, LINE)
        text(d, (CARD_X + TXT_X, y0 + 9), main, f_main, INK)
        if sub:      # 空 = 该行整行交给安装脚本运行时画（见 ITEMS 注释）
            text(d, (CARD_X + TXT_X, y0 + 27), sub, f_sub, GRAY)
        if vol:
            text(d, (CARD_X + CARD_W - VOL_RIGHT, y0 + CARD_H / 2), vol, f_vol,
                 FAINT, "rm")
        if pill:
            # 橙胶囊：紧跟主文字右侧
            tw = d.textlength(main, font=f_main) / S
            px0 = CARD_X + TXT_X + tw + 8
            pw = d.textlength(pill, font=f_sub) / S + 14
            rr(d, (px0, y0 + 10, px0 + pw, y0 + 26), 7, fill=ORANGE_BG)
            text(d, (px0 + pw / 2, y0 + 18), pill, f_sub, ORANGE_TX, "mm")

    # ---- 分隔线 ----
    d.line([px(0), px(SEP_Y), px(W), px(SEP_Y)], fill=LINE, width=max(1, S))

    # ---- 底部小字 ----
    text(d, (FOOT_X, FOOT_Y), "SnapLingo 0.1.0", font(13), FAINT)

    im = finish(im, W, H)
    im.save(os.path.join(OUT, "un-bg.png"))
    print("  un-bg.png            %dx%d (逻辑 %dx%d)" % (im.width, im.height, W, H))


# ==========================================================================
#  2) 勾选框（两种状态，单独出图；含点击热区）
# ==========================================================================
def make_checkbox():
    box = CHK_S + 8   # 15 + 8 = 23 的热区，四周各留 4px
    for name, on in (("un-check.png", True), ("un-check-off.png", False)):
        im = Image.new("RGB", (px(box), px(box)), WHITE)
        d = ImageDraw.Draw(im)
        x0, y0 = (box - CHK_S) / 2, (box - CHK_S) / 2
        if on:
            rr(d, (x0, y0, x0 + CHK_S, y0 + CHK_S), 4, fill=RED)
            # 白色对勾
            d.line([px(x0 + 3.4), px(y0 + 7.8), px(x0 + 6.2), px(y0 + 10.6),
                    px(x0 + 11.8), px(y0 + 4.4)],
                   fill=WHITE, width=max(1, int(1.9 * S)), joint="curve")
        else:
            rr_stroke(d, (x0, y0, x0 + CHK_S, y0 + CHK_S), 4, CHK_BORDER)
        im = finish(im, box, box)
        im.save(os.path.join(OUT, name))
        print("  %-19s %dx%d" % (name, im.width, im.height))


# ==========================================================================
#  3) 两个按钮
# ==========================================================================
def make_buttons():
    # 取消：白底 + 深灰描边 + 深色字
    im = Image.new("RGB", (px(CANCEL_W), px(BTN_H)), WHITE)
    d = ImageDraw.Draw(im)
    rr_stroke(d, (0, 0, CANCEL_W, BTN_H), 8, BTN_BORDER)
    text(d, (CANCEL_W / 2, BTN_H / 2), "取消", font(14), INK, "mm")
    im = finish(im, CANCEL_W, BTN_H)
    im.save(os.path.join(OUT, "un-btn-cancel.png"))
    print("  un-btn-cancel.png    %dx%d" % (im.width, im.height))

    # 继续卸载：红底 + 白字
    im = Image.new("RGB", (px(OK_W), px(BTN_H)), WHITE)
    d = ImageDraw.Draw(im)
    rr(d, (0, 0, OK_W, BTN_H), 8, fill=RED)
    text(d, (OK_W / 2, BTN_H / 2), "继续卸载", font(14), WHITE, "mm")
    im = finish(im, OK_W, BTN_H)
    im.save(os.path.join(OUT, "un-btn-ok.png"))
    print("  un-btn-ok.png        %dx%d" % (im.width, im.height))


# ==========================================================================
#  4) 关闭按钮 ✕
# ==========================================================================
def make_close():
    im = Image.new("RGB", (px(CLOSE_S), px(CLOSE_S)), WHITE)
    d = ImageDraw.Draw(im)
    rr_stroke(d, (0, 0, CLOSE_S, CLOSE_S), 7, LINE)
    m = CLOSE_S * 0.32
    lw = max(1, int(1.4 * S))
    d.line([px(m), px(m), px(CLOSE_S - m), px(CLOSE_S - m)],
           fill=BTN_BORDER, width=lw)
    d.line([px(CLOSE_S - m), px(m), px(m), px(CLOSE_S - m)],
           fill=BTN_BORDER, width=lw)
    im = finish(im, CLOSE_S, CLOSE_S)
    im.save(os.path.join(OUT, "un-close.png"))
    print("  un-close.png         %dx%d" % (im.width, im.height))


# ==========================================================================
#  5) 警示条：只出「粉底 + 红三角」一张底图，文字由脚本运行时画
#     ⚠️ 旧版按「勾了几项 × 有没有勾模型」预出 13 张图（un-warn-N-m/o.bmp）。
#        体积一旦变成真实值，组合就爆炸了 —— 体积是任意数字，不可能预先出图。
#        所以底色单独一张，文字交给 TNewStaticText（颜色已由 scale_probe5.iss 实测可用）。
# ==========================================================================
def make_warning_bg():
    im = Image.new("RGB", (px(WARN_W), px(WARN_H)), WHITE)
    d = ImageDraw.Draw(im)
    rr(d, (0, 0, WARN_W, WARN_H), 8, fill=RED_BG)
    draw_warn_icon(d, 14, WARN_H / 2 - 7, 14)
    im = finish(im, WARN_W, WARN_H)
    im.save(os.path.join(OUT, "un-warn-bg.png"))
    print("  un-warn-bg.png       %dx%d" % (im.width, im.height))


# ==========================================================================
#  6) 验收用拼图：按逻辑坐标把素材拼成完整窗体（勾选态）
# ==========================================================================
def make_preview():
    # ⚠️ 素材现在已经是**最终尺寸**（finish() 缩过），所以拼接坐标就是素材坐标。
    im = Image.open(os.path.join(OUT, "un-bg.png")).convert("RGB")

    def paste(path, x, y):
        g = Image.open(os.path.join(OUT, path)).convert("RGB")
        im.paste(g, (int(round(x * SX)), int(round(y * SY))))

    for y0 in CARD_Y:
        # 勾选框热区 23x23，让 15x15 的框落在卡内 (14,18)
        # ⚠️ 2026-10-10 起默认是「全不勾选」，预览也照这个画 —— 预览图要等于
        #    用户真正打开卸载框看到的样子，否则拿它验收会得出错误结论。
        paste("un-check-off.png", CARD_X + CHK_X - 4, y0 + CHK_Y - 4)
    paste("un-warn-bg.png", WARN_X, WARN_Y)
    paste("un-close.png", CLOSE_X, CLOSE_Y)
    paste("un-btn-cancel.png", CANCEL_X, BTN_Y)
    paste("un-btn-ok.png", OK_X, BTN_Y)

    # 运行时才画的动态文字，这里用示例值补上 —— 只为看图对位，不进安装包。
    # ⚠️ 坐标与字号都要乘 SX/SY：这张画布已经是放大后的物理尺寸，
    #    用逻辑坐标会整体偏到左上角、字也偏小。
    d = ImageDraw.Draw(im)
    P = lambda x, y: (int(round(x * SX)), int(round(y * SY)))
    f13 = font_phys(int(round(13 * SX)))
    demo = ["1.2 KB", "149 张 PNG", "165.8 MB", "2.4 MB"]
    for i, s in enumerate(demo):
        y0 = CARD_Y[i]
        if i == 1:      # 历史截图：动态数量占的是「副文字」那一行
            d.text(P(CARD_X + TXT_X, y0 + 27), s, font=f13, fill=GRAY)
        else:           # 其余三项：体积，卡片内右对齐、垂直居中
            d.text(P(CARD_X + CARD_W - VOL_RIGHT, y0 + CARD_H // 2),
                   s, font=f13, fill=FAINT, anchor="rm")
    # 默认（一项都没勾）时警示条走的是兜底文案，见 RefreshUninstallTexts。
    # ⚠️ 这段文字必须与 .iss 里 RefreshUninstallTexts 的字面量**逐字一致**，
    #    否则预览图与实机不符（曾写成"本次不会删除…"，实机没有"本次"）。
    d.text(P(WARN_X + 36, WARN_Y + WARN_H // 2),
           "不会删除任何数据，仅移除程序本体。",
           font=f13, fill=RED, anchor="lm")

    im.save(os.path.join(OUT, "un-preview.png"))
    print("  un-preview.png       %dx%d (整窗预览，含动态文字示例)" % (im.width, im.height))


# ==========================================================================
#  7) 转 BMP 给 Inno
# ==========================================================================
BMP_STEMS = ["un-bg", "un-check", "un-check-off", "un-close",
             "un-btn-cancel", "un-btn-ok", "un-warn-bg"]


def export_bmp():
    for s in BMP_STEMS:
        src = os.path.join(OUT, s + ".png")
        if os.path.exists(src):
            Image.open(src).convert("RGB").save(os.path.join(OUT, s + ".bmp"), "BMP")
    print("  已导出 %d 个 BMP" % len(BMP_STEMS))


def main():
    print("输出目录: %s\n" % OUT)
    print("== 背景大图 ==")
    make_bg()
    print("\n== 勾选框 ==")
    make_checkbox()
    print("\n== 按钮 ==")
    make_buttons()
    print("\n== 关闭按钮 ==")
    make_close()
    print("\n== 警示条 ==")
    make_warning_bg()
    print("\n== 整窗预览 ==")
    make_preview()
    print("\n== 导出 BMP ==")
    export_bmp()
    print("\n卸载窗体素材已生成 ✓")


if __name__ == "__main__":
    main()
