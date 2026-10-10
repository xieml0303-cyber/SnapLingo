; ============================================================================
;  SnapLingo 安装脚本（Inno Setup 7.1.0）
;
;  编译：  ISCC.exe packaging\snaplingo.iss
;  产物：  packaging\build\SnapLingo-Setup-<版本>.exe
;
;  视觉目标：极简无边框 + 小清新（品牌绿 #0CAF76 + 细线语言）
;  技术路线（全部官方能力，零第三方 DLL）：
;    1. WizardForm.BorderStyle := bsNone  去掉系统标题栏
;    2. 自绘一条细标题栏（Logo + 最小化/关闭），原有内容整体下移
;    3. 圆角：Win11 走 DWM，Win10 退 CreateRoundRectRgn + SetWindowRgn
;    4. 拖动：ReleaseCapture + WM_SYSCOMMAND(SC_DRAGMOVE)
;    5. 卸载：无边框进度窗体 + 自定义「候选删除项」询问窗体
;
;  ⚠️ 写 Inno Pascal 的血泪教训（来自同机 nexusops.iss，务必遵守）：
;    - 注释里**绝不能出现花括号**（Pascal 注释不支持嵌套，会提前闭合）
;    - 不支持 ['a','b'] 数组字面量，要用 SetArrayLength 逐项赋值
;    - usPostUninstall 阶段**绝不能碰 UninstallProgressForm**（会抛 Runtime error）
;    - TaskDialogMsgBox 不受 /SUPPRESSMSGBOXES 压制，静默场景要自己判断
;    - 转义规则：只有 {{ 会展开成字面 {，} 不需要转义
; ============================================================================

#define AppName "SnapLingo"
#define AppVersion "0.1.0"
#define AppPublisher "SnapLingo"
#define ShellExe "SnapLingo.exe"
; 正式包用**真实程序**的 PyInstaller 产物（packaging/SnapLingo.spec，入口 ../main.py）。
; ⚠️ 测试包由 probe/make_test_iss.py 派生，它会把这里换回 build\shell\SnapLingo（空壳），
;    这样改安装器界面时不必每次重打 300 MB 的真实包。
#define SrcShell "build\app\SnapLingo"

; 离线翻译模型：**直接引用构建机上的 AppData**，不把 165.8 MB 复制进仓库。
; ⚠️ 构建机必须已装好模型，否则下面 #if 会立刻报错停下
;    （而不是悄悄打出一个没有模型的包 —— 那种包装完首次翻译才报错，很难查）。
#define ModelsDir GetEnv('LOCALAPPDATA') + '\ScreenshotTranslator\models'
#if !FileExists(AddBackslash(ModelsDir) + 'en_zh\model\model.bin')
  #error 找不到离线翻译模型（%LOCALAPPDATA%\ScreenshotTranslator\models）—— 请先在构建机上装好模型再打包
#endif

[Setup]
; AppId 固定不变 —— 升级安装时才能识别为「同一个应用」，否则会并存两个
AppId={{A7F3C2E1-9B4D-4E6A-8C15-3D7F0B2A9E48}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableReadyPage=yes
; ⚠️ Inno 的 UsePreviousTasks **默认为 yes**：它会记住用户上次的勾选状态。
;    主人要求「附加任务两个选项默认勾选」，若沿用上次（没勾）就永远勾不上 ——
;    实测就是这么回事（去掉 Flags 也没用）。这里显式关掉「记住上次」。
UsePreviousTasks=no
; 显式打开欢迎页 —— 它是左侧大图唯一的两处展示位之一（另一处是完成页）
DisableWelcomePage=no
OutputDir=build
OutputBaseFilename=SnapLingo-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
; 默认仍是 per-machine（admin）。额外允许命令行用 /CURRENTUSER 覆盖成 per-user 安装 ——
; 这既方便自动化测试（免 UAC），也给用户"只给自己装"的选择，不改变默认语义。
PrivilegesRequiredOverridesAllowed=commandline
; 极简浅色：modern 外观 + 强制浅色 + 隐藏横向分隔线
WizardStyle=modern light hidebevels
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#ShellExe}
ShowLanguageDialog=no
; 左栏底色图（纯深绿）—— 真正的左栏是 [Code] 里自绘的 Panel，
; 这张图只是兜底：万一 Panel 没盖满，也不会露出 Inno 的默认蓝色图
WizardImageFile=..\assets\installer\wizard-large.png
; 设计稿右栏右上角没有小图，做成与背景同色的隐形占位
WizardSmallImageFile=..\assets\installer\wizard-small.png
; ⚠️ TColor 是 $00BBGGRR 顺序（不是 RGB）：深绿 #0F6E56 → $00566E0F
WizardImageBackColor=$00566E0F
WizardBackColor=$00FFFFFF
; 许可协议页 —— 设计稿的「安装步骤」是 4 步（欢迎 / 许可协议 / 安装位置 / 完成），
; 所以这里必须真的放一页许可，否则「第 1 步，共 4 步」是假的
LicenseFile=..\assets\license.txt
DefaultDialogFontName=Microsoft YaHei UI

[Languages]
Name: "chinese"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
; 主人 2026-10-09 要求：两个附加任务**默认都勾选**。
; ⚠️ 不要用 `checkedonce` —— 那是「首次安装默认勾、之后记住用户上次的选择」，
;    机器上只要装过一次，就会沿用上次的状态（实测主人那边两个框都是空的）。
;    Inno 的 task 本身默认就是勾选的，不写 Flags 才会每次都默认勾上。
Name: "autostart"; Description: "开机自动启动 {#AppName}"; GroupDescription: "附加任务："
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："

[Files]
; ⚠️⚠️ **顺序有讲究：dontcopy 的自绘素材必须排在最前，不要往下挪。**
;    本脚本用 SolidCompression=yes（Compression=lzma2/max）—— 所有文件压成**一条流**，
;    Setup **无法随机访问**（Inno 帮助原文：某个文件即使不装，也得先把它前面的数据
;    解压掉才能继续）。而安装向导在 InitializeWizard 里就要 ExtractTemporaryFile
;    取这些素材去铺欢迎页。
;    实测（2026-10-10）：素材原先排在 227MB 程序 + 162MB 模型**之后**时，
;    TWizardForm 对象 0.03s 就创建了，但**窗口可见要 11.97s** —— 那 12 秒全是在
;    从头顺序解压近 390MB 的 solid 流。移到最前面后只需解压开头几 MB。
;    ⚠️ 动过这里务必重新实测「窗口可见耗时」（脚本见 README §43 的说明）。
Source: "..\assets\installer\left-1.bmp";            Flags: dontcopy
Source: "..\assets\installer\left-2.bmp";            Flags: dontcopy
Source: "..\assets\installer\left-3.bmp";            Flags: dontcopy
Source: "..\assets\installer\left-4.bmp";            Flags: dontcopy
Source: "..\assets\installer\welcome-right.bmp";     Flags: dontcopy
Source: "..\assets\installer\welcome-step.bmp";      Flags: dontcopy
Source: "..\assets\installer\btn-primary.bmp";       Flags: dontcopy
Source: "..\assets\installer\btn-next-off.bmp";      Flags: dontcopy
Source: "..\assets\installer\btn-ghost.bmp";         Flags: dontcopy
Source: "..\assets\installer\btn-prev.bmp";          Flags: dontcopy
Source: "..\assets\installer\btn-finish.bmp";        Flags: dontcopy
Source: "..\assets\installer\line.bmp";              Flags: dontcopy
Source: "..\assets\installer\line-frame.bmp";        Flags: dontcopy
Source: "..\assets\installer\btn-close.bmp";         Flags: dontcopy
; 程序本体（227 MB）。体积大的放后面 —— 它们只在真正安装时才需要解压，
; 不影响启动速度。
Source: "{#SrcShell}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 离线翻译模型（165.8 MB）—— **内置**到用户数据目录，装完即可离线翻译。
; ⚠️ 为什么装到 {localappdata} 而不是 {app}：程序的数据目录固定在
;    %LOCALAPPDATA%\ScreenshotTranslator（见 sctool/paths.py 的 ASCII 路径约束），
;    装到 {app} 程序根本找不到。这也正是卸载窗体那 4 张候选卡片的设计依据。
; ⚠️ uninsneveruninstall：**不写进卸载日志** ⇒ 卸载时不会被 Inno 自动删除，
;    改由卸载窗体的「候选框」控制（否则那个候选框就成了摆设）。
; ⚠️ Excludes 排掉 stanza\（约 3.9 MB）：那是早期版本解压留下的残留，
;    sctool/models.py 的 _SKIP_PREFIXES 本来就会跳过它。
Source: "{#ModelsDir}\*"; DestDir: "{localappdata}\ScreenshotTranslator\models"; Flags: ignoreversion recursesubdirs createallsubdirs uninsneveruninstall; Excludes: "stanza,*\stanza"
; 卸载询问窗体的自绘素材 —— ⚠️ 这组**要装到 {app}\ui\**，不能走 dontcopy：
;   卸载器禁止调用 ExtractTemporaryFile，只能从程序目录读（详见 LoadBmp 的说明）。
;   卸载窗体在删文件之前显示，那时这些文件还在。
;   （这组不必提前：它们是**安装期**才解压的，晚一点不影响启动速度。）
Source: "..\assets\installer\un-bg.bmp";             DestDir: "{app}\ui"; Flags: ignoreversion
Source: "..\assets\installer\un-check.bmp";          DestDir: "{app}\ui"; Flags: ignoreversion
Source: "..\assets\installer\un-check-off.bmp";      DestDir: "{app}\ui"; Flags: ignoreversion
Source: "..\assets\installer\un-close.bmp";          DestDir: "{app}\ui"; Flags: ignoreversion
Source: "..\assets\installer\un-btn-cancel.bmp";     DestDir: "{app}\ui"; Flags: ignoreversion
Source: "..\assets\installer\un-btn-ok.bmp";         DestDir: "{app}\ui"; Flags: ignoreversion
Source: "..\assets\installer\un-warn-bg.bmp";        DestDir: "{app}\ui"; Flags: ignoreversion
; ⚠️ 警示条**只有这一张底图**（粉底 + 红三角），文字由 RefreshUninstallTexts 运行时画。
;    旧版按「勾了几项 × 有没有勾模型」预出 13 张 un-warn-N-m/o.bmp；
;    体积改成真实值后组合会爆炸（任意数字无法预先出图），所以合并成一张。

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#ShellExe}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#ShellExe}"; Tasks: desktopicon

[Run]
; 开机自启：由程序自己写注册表，保证「注册表项」与「程序内配置」两处状态一致
Filename: "{app}\{#ShellExe}"; Parameters: "--set-autostart on"; Flags: runhidden waituntilterminated; Tasks: autostart; StatusMsg: "配置开机自启…"
Filename: "{app}\{#ShellExe}"; Description: "立即运行 {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 卸载前先结束进程，否则 exe 被占用、文件删不掉（SnapLingo 是托盘常驻 + 全局热键）
Filename: "{cmd}"; Parameters: "/c taskkill /F /IM {#ShellExe} /T > nul 2>&1 & ping -n 2 127.0.0.1 > nul"; Flags: runhidden waituntilterminated; RunOnceId: "KillApp"
; 无论用户是否勾选，自启项都必须删（它是无条件清理项，不作为候选）
Filename: "{app}\{#ShellExe}"; Parameters: "--set-autostart off"; Flags: runhidden waituntilterminated; RunOnceId: "ClearAutostart"

[Code]
// ==========================================================================
//  品牌色与常量
//  ⚠️ Inno 的 TColor 是 $00BBGGRR 顺序（不是 RGB），写反了颜色会错
// ==========================================================================
const
  // ---- 色板（取自主人 2026-10-09 的设计稿）----
  CLR_GREEN      = $00566E0F;   // #0F6E56 主深绿（左栏底 / 主按钮 / 强调）
  CLR_GREEN_LT   = $006E8231;   // #31826E 图标容器浅绿
  CLR_GREEN_PALE = $00EEF5E1;   // #E1F5EE 胶囊底 / 卡片图标底
  CLR_GREEN_SOFT = $00B4C78F;   // #8FC7B4 步骤未激活的描边与数字
  CLR_INK        = $00282A24;   // #242A28 主文字
  CLR_GRAY       = $0070726B;   // #6B7270 次要文字
  CLR_LINE       = $00E8EAE6;   // #E6EAE8 分隔线 / 卡片边框
  CLR_WHITE      = $00FFFFFF;

  TITLEBAR_H = 46;              // 自绘标题栏高度（100% DPI）
  CORNER_R   = 18;              // 圆角半径
  LEFT_W     = 196;             // 左栏宽度（100% DPI）≈ 设计稿的 32.9%

  // 欢迎页底部两个自绘按钮的尺寸与边距（量自设计稿）
  BTN_W        = 92;
  BTN_H        = 36;
  BTN_GAP      = 12;            // 两个按钮之间的间距
  BTN_MARGIN_R = 24;            // 距窗口右边缘
  BTN_MARGIN_B = 22;            // 距窗口底边

  // 右栏内容图的高度 —— **必须避开底部按钮区**，否则会把按钮的点击吃掉
  RIGHT_H = 392;
  // 页面标题带：一级标题（页面名）与次级文本（页面说明）在右栏内的纵向位置。
  // 与欢迎页自绘图片里的标题 / 副标题**同一基准** ⇒ 四页视觉完全对齐。
  HEAD_NAME_Y = 56;             // 一级标题的垂直中心（100% DPI）
  HEAD_DESC_Y = 96;             // 次级文本首行的垂直中心
  // 「第 N 步，共 4 步」单独一张小图，摆在按钮左侧
  STEP_W  = 124;
  STEP_H  = 26;

  // RedrawWindow 的标志位
  RDW_INVALIDATE  = $0001;
  RDW_ERASE       = $0004;
  RDW_ALLCHILDREN = $0080;
  RDW_UPDATENOW   = $0100;

  DWMWA_CORNER_PREFERENCE = 33;
  DWMWCP_ROUND            = 2;
  WM_SYSCOMMAND           = $0112;
  SC_DRAGMOVE             = $F012;
  BM_CLICK                = $00F5;

  // 子类化 / 命中测试
  GWLP_WNDPROC = -4;
  WM_NCHITTEST = $0084;
  WM_NCDESTROY = $0082;
  HTCLIENT     = 1;
  HTCAPTION    = 2;

// ==========================================================================
//  外部函数（全部来自系统 DLL，零第三方依赖）
//  ⚠️ SendMessage 是 Inno 内置函数，不要重复声明
// ==========================================================================
function ReleaseCapture: Boolean;
  external 'ReleaseCapture@user32.dll stdcall';

// ⚠️ Inno Pascal 没有 Pointer 类型，改用 var 参数传引用（自动取址）
function DwmSetWindowAttribute(hwnd: HWND; dwAttribute: DWORD;
  var pvAttribute: Integer; cbAttribute: DWORD): Longint;
  external 'DwmSetWindowAttribute@dwmapi.dll stdcall delayload';

function CreateRoundRectRgn(x1, y1, x2, y2, ew, eh: Integer): THandle;
  external 'CreateRoundRectRgn@gdi32.dll stdcall';

function SetWindowRgn(h: HWND; hRgn: THandle; bRedraw: Boolean): Integer;
  external 'SetWindowRgn@user32.dll stdcall';

// 窗口过程子类化所需（用于实现无边框窗口的拖动）
// ⚠️ 参数/返回值一律用 DWORD（32 位）而**不是** Longint。
//    Setup.exe 本体是 32 位进程，而 Inno 的 Longint 是 64 位 —— 用 Longint 声明
//    等于让 API 去读两个栈槽，参数会整体错位。参见 WizardWndProc 上方的血泪说明。
function CallWindowProcW(lpPrevWndFunc: Longint; hWnd: HWND; Msg: UINT;
  wParam: DWORD; lParam: DWORD): DWORD;
  external 'CallWindowProcW@user32.dll stdcall';

function DefWindowProcW(hWnd: HWND; Msg: UINT; wParam: DWORD;
  lParam: DWORD): DWORD;
  external 'DefWindowProcW@user32.dll stdcall';

function SetWindowLongW(hWnd: HWND; nIndex: Integer; dwNewLong: Longint): Longint;
  external 'SetWindowLongW@user32.dll stdcall';

// ⚠️ 这里**不要**再声明 ScreenToClient。它的真实签名是
//    ScreenToClient(hwnd, POINT*) —— 只有**一个**指针参数，而 Inno 里没法传结构体，
//    只能写成两个 var 参数，于是参数与 API 期望彻底对不上，**每调用一次就把安装器
//    打崩**（0xC000041D，日志探针实测崩溃点就停在这一行）。
//    要判断鼠标是否落在标题栏，直接用无边框顶层窗口的 Top 比大小就够了。

// 强制父窗口整体重绘。自绘控件（右栏整块图、自绘按钮）被隐藏或移走之后，
// WizardForm 不会自动重画那一块，屏幕上会留下残影 —— 实测切到许可页时，会同时
// 残留欢迎页右栏内容和一枚「下一步」按钮的鬼影，看起来像渲染坏了。
// ⚠️ 只调 InvalidateRect 不够（实测残影照旧）：它只是「标记待重绘」，子窗口
//    （TNewNotebook 之类）未必跟着重画。RedrawWindow 配上 RDW_UPDATENOW 与
//    RDW_ALLCHILDREN，才会立刻连子窗口一起重画。
// ⚠️ 指针类参数用 DWORD（4 字节）而不是 Longint：传 0 = 整个客户区，
//    声明成 8 字节会让参数错位（这个坑在 ScreenToClient 上刚吃过一次）。
function RedrawWindow(hWnd: HWND; lprcUpdate: DWORD; hrgnUpdate: DWORD;
  flags: UINT): BOOL;
  external 'RedrawWindow@user32.dll stdcall';

// ==========================================================================
//  全局变量
// ==========================================================================
var
  // ---- 自绘标题栏 ----
  // ⚠️⚠️ 色块一律用 TBitmapImage，**绝不要用 TPanel**。
  //    Inno 的 TPanel 即使设了 Color 也**不会绘制**（VCL 的主题化背景把它盖掉了），
  //    而且失败得毫无提示：深绿左栏整片变白、1px 分隔线看不见、深绿主按钮不出现，
  //    但同一份脚本里所有 TBitmapImage（卡片/胶囊/图标容器/关闭钮）全部正常。
  //    实测花了好几轮才把「颜色不显示」和「控件类型」联系起来，切记。
  TitleLine: TBitmapImage;      // 标题栏底部 1px 浅灰分隔线
  TitleDot: TNewStaticText;     // 左侧的「·」圆点（主人要求沿用原来这个样式）
  TitleText: TNewStaticText;
  TitleClose: TBitmapImage;     // 圆角方框 + ✕

  // ---- 左栏 / 右栏 ----
  // ⚠️ 这两块是**整幅图片**（left-1..4 / welcome-right），不是一堆小控件拼的。
  //    原因：Inno 的 TNewStaticText **不理会 Font.Color** —— 把字设成红色，屏幕上
  //    仍渲染成纯黑（字号、粗细倒是照做），深绿底上的白字根本显示不出来。
  //    整幅交给 Pillow 渲染后，颜色 / 居中 / 字重全部可控，定位代码也少了一大截。
  LeftPanel: TBitmapImage;      // 左栏（含高亮步骤，切页时换图）
  W_Right: TBitmapImage;        // 欢迎页右侧内容（标题 / 胶囊 / 副标题 / 卡片），仅欢迎页显示
  W_Step: TBitmapImage;         // 「第 N 步，共 4 步」（单独一张，避开按钮点击区）
  // 许可页阅读框的顶边线。Inno 天然不画这条（见 SetupPageHeadText 的说明），
  // 而线要盖在有句柄的页面容器之上，所以同样得用 TPanel 外壳 + 图片两层。
  MemoTopLineShell: TPanel;
  MemoTopLineImg: TBitmapImage;

  // ---- 安装进度页的实时百分比 ----
  // Inno 的进度页只有一条光秃秃的进度条（主人给的截图里就是那样，看不出装到哪了）。
  // 这里加一行文字，由 CurInstallProgressChanged 实时刷新。
  // ⚠️ 为什么不直接改 Inno 自带的 FilenameLabel：Inno 每个文件都会重设它的文字，
  //    我们改完立刻被覆盖，会来回闪。
  ProgPctLabel: TNewStaticText;

  // ---- 向导按钮：自绘外观 + 原生按钮转发 ----
  // ⚠️ 外壳用 TPanel（TWinControl）而不是直接用 TBitmapImage，原因见
  //    UpdateWizardChrome 上方的说明：图形控件（无窗口句柄）永远盖不过有句柄的
  //    页面容器，纯图片按钮在向导页上会被压住、永远收不到点击。
  BtnNextShell: TPanel;  BtnNextImg: TBitmapImage;   // 右格：下一步 / 完成
  BtnLeftShell: TPanel;  BtnLeftImg: TBitmapImage;   // 左格：取消（欢迎页）/ 上一步
  NextImgFile, LeftImgFile: String;   // 记住当前贴的图，避免反复解压加载
  LeftIsCancel: Boolean;              // 左格点下去该转发「取消」还是「上一步」
  // 原生按钮的原位置。被自绘接管时把它们挪到窗外 —— 不能改用 Visible=False，
  // Inno 会因此判定「无法前进到下一页」直接 Abort（实测退出码 1）。
  NativeSaved: Boolean;
  NativeNextL, NativeNextT, NativeNextW, NativeNextH: Integer;
  NativeBackL, NativeBackT, NativeBackW, NativeBackH: Integer;
  NativeCancelL, NativeCancelT, NativeCancelW, NativeCancelH: Integer;

  // 卸载候选框的勾选结果（下标与候选清单一一对应）
  PurgeChoices: array of Boolean;
  PurgePaths: array of String;
  //: 各项在**用户机器上实测**的磁盘占用（字节）。只有运行时才读得到，
  //: 这正是体积文案必须动态绘制的原因。见 InitUninstallOptions。
  PurgeSizes: array of Int64;
  // 卸载询问窗体的确认标志（Inno 无 mrOk 常量，用标志位代替 ModalResult）
  UninstallConfirmed: Boolean;
  // ⚠️ 按钮回调里**绝不能**写 TForm(Sender).Close —— Pascal Script 的类型转换会做
  //    运行时检查，而 Sender 实际是 TNewButton，与 TForm 不兼容，点按钮当场抛
  //    "Cannot cast an object."（实测踩过）。改用全局变量持有窗体引用。
  UninstallDlg: TSetupForm;

  // ---- 卸载询问窗体：自绘部分 ----
  // 整窗静态部分（标题栏/图标/标题/说明/4 张卡片框/主文字/橙胶囊/分隔线/
  // 底部小字）交给 Pillow 渲染成 un-bg.bmp —— 一次成图，定位代码最少。
  // ⚠️ 2026-10-09 更正：旧注释写「TNewStaticText 不理会 Font.Color」，**是错的**。
  //    探针 packaging/probe/scale_probe5.iss 实测（computer-use 插件读屏）：
  //    灰 #999999 / 红 #A32D2D / 绿 #0CAF76 / fsBold **全部正常渲染**，
  //    各控件的 Font 也互不影响。所以**动态**文字改回控件绘制（见下面三个变量），
  //    只有静态文字继续留在图里。TPanel 不绘制 Color 那条仍然成立。
  UninstallChecks: array of TBitmapImage;   // 4 个勾选框（只管显示）
  UninstallCheckOn: array of Boolean;       // 对应的勾选状态
  // ⚠️⚠️ 勾选框的 TPanel 外壳 —— 真正「收点击」的是它，不是上面那张图。
  //    TBitmapImage 是 TGraphicControl，**没有自己的窗口句柄**，点击要靠父窗体
  //    的 IsControlMouseMsg 按坐标分发给它；而 Inno 的 TSetupForm 覆盖了 WndProc，
  //    这条分发路径不通 ⇒ 裸 TBitmapImage 的 OnClick 永远不触发。
  //    实测（packaging/probe/un_click_test.py）：SendMessage / PostMessage /
  //    mouse_event 三种注入方式点完都是「画面 byte-identical、GetCapture() 仍为 0」。
  //    TPanel 是 TWinControl（**有句柄**），Windows 直接把鼠标消息投给它，
  //    绕开父窗体 —— 与安装向导那两个按钮外壳同一套路（那边实测可点）。
  //    外壳 Color 取白色，与卡片底色一致，肉眼看不出多了一层。
  UninstallCheckShells: array of TPanel;
  UninstallWarnImg: TBitmapImage;           // 警示条底图（只有粉底 + 红三角，文字另画）

  // ---- 卸载询问窗体：运行时才画的动态文字 ----
  // 体积 / 数量只有在用户机器上才读得到，不能烘进素材。
  // ⚠️ 必须是 TNewStaticText（TGraphicControl）：它透明、无句柄，
  //    叠在背景图之上不会挡住下面的 TBitmapImage；反过来若用 TPanel 就会整块盖住。
  //    创建顺序 = Z 顺序，所以这三个数组**必须在 Bg 之后创建**（见 UninstallAskForm）。
  UninstallVolLabels: array of TNewStaticText;   // 4 项的磁盘占用（卡内右对齐）
  UninstallSubLabel: TNewStaticText;             // 「历史截图」那一行的「N 张 PNG」
  UninstallWarnText: TNewStaticText;             // 警示条正文

  // 当前跑的是安装器还是卸载器 —— 决定自绘素材从哪里加载，见 LoadBmp。
  IsUninstaller: Boolean;

// ==========================================================================
//  版本判断
// ==========================================================================
function IsWindows11OrLater: Boolean;
var
  V: TWindowsVersion;
begin
  GetWindowsVersionEx(V);
  Result := (V.Major >= 10) and (V.Build >= 22000);
end;

// ==========================================================================
//  圆角：Win11 优先 DWM（平滑 + 系统阴影），Win10 退区域裁剪（有锯齿）
// ==========================================================================
procedure ApplyRoundedCorners(AForm: TForm);
var
  Pref: Integer;
  Rgn: THandle;
  W, H: Integer;
begin
  if IsWindows11OrLater then
  begin
    Pref := DWMWCP_ROUND;
    DwmSetWindowAttribute(AForm.Handle, DWMWA_CORNER_PREFERENCE,
      Pref, SizeOf(Pref));
  end
  else
  begin
    W := AForm.ClientWidth;
    H := AForm.ClientHeight;
    Rgn := CreateRoundRectRgn(0, 0, W + 1, H + 1,
      ScaleX(CORNER_R) * 2, ScaleY(CORNER_R) * 2);
    if Rgn <> 0 then
      SetWindowRgn(AForm.Handle, Rgn, True);
  end;
end;

// ==========================================================================
//  拖动：窗口过程子类化
//  ⚠️ Inno 7.1 的 Pascal **没有**注册 OnMouseDown（实测编译器报 Unknown identifier），
//     所以不能用事件做拖动，只能子类化 WndProc，在 WM_NCHITTEST 里把
//     窗口顶部标题栏带的命中结果从 HTCLIENT 改成 HTCAPTION，交给系统原生拖动。
//     子控件（按钮等）自己处理命中测试，不受影响。
// ==========================================================================
var
  OldWizardProc: Longint;

// ⚠️⚠️ 签名绝不能写 Longint —— 这是本脚本踩过最久的一个坑，务必照抄 DWORD。
//    Setup.exe 是 **32 位**进程（PE machine 0x14c），而 Inno 的 Longint 是 **64 位**。
//    官方文档 topic_64bit.htm 原文：
//      "In 32-bit installers, CreateCallback does not support callback parameters
//       passed by value when their type is larger than 4 bytes, such as Int64 ..."
//    用 Longint 当 wParam / lParam ⇒ 每次窗口消息回调都在栈上多传 8 字节 ⇒
//    参数整体错位 ⇒ 安装器进程以 0xC000041D (STATUS_FATAL_USER_CALLBACK_EXCEPTION)
//    崩掉，**而且崩在安装刚启动的几秒内**（窗口一闪就没了），看起来完全不像
//    "回调参数类型"的问题 —— 排查时被误导了好几轮。
//    减法实验：注释掉 HookWizardProc 后退出码立刻从 0xC000041D 变成 0。
function WizardWndProc(hwnd: HWND; msg: UINT; wParam: DWORD;
  lParam: DWORD): DWORD;
var
  X, Y, Cx, Cy, Prev: Longint;
begin
  // ⚠️ 窗口销毁时必须把旧 WndProc 装回去（子类化的标准收尾）。
  //    否则系统销毁窗口时仍会调这个脚本回调，而那时回调表已经在拆了，
  //    安装器进程会以 0xC000041D (STATUS_FATAL_USER_CALLBACK_EXCEPTION) 退出。
  //    ⚠️ 实测踩过：表现是"安装完全成功，但退出码异常"。
  if msg = WM_NCDESTROY then
  begin
    Prev := OldWizardProc;
    if Prev <> 0 then
    begin
      SetWindowLongW(hwnd, GWLP_WNDPROC, Prev);
      OldWizardProc := 0;
      Result := CallWindowProcW(Prev, hwnd, msg, wParam, lParam);
    end
    else
      Result := DefWindowProcW(hwnd, msg, wParam, lParam);
    Exit;
  end;

  if msg = WM_NCHITTEST then
  begin
    // lParam 低 16 位是屏幕 X、高 16 位是屏幕 Y（均为有符号 16 位）
    X := lParam and $FFFF;
    if X >= $8000 then X := X - $10000;
    Y := (lParam shr 16) and $FFFF;
    if Y >= $8000 then Y := Y - $10000;

    // 命中结果只有两种，全部按坐标判断，**不去问 DefWindowProcW**：
    //   标题栏（且不是右上角关闭按钮那一块）= HTCAPTION，交给系统拖动；
    //   其余客户区 = HTCLIENT。
    // ⚠️ 不能拿 DefWindowProcW 的返回值当依据：实测那样整个客户区的点击会一起
    //    丢失，表现是底部按钮全点不动（排查花了好几轮）。
    // ⚠️ 不能调 ScreenToClient 换算坐标：它的签名是单个 LPPOINT，在 Inno 里只能
    //    写成两个 var 参数，参数对不上，一调就把安装器打崩（见上方声明处的说明）。
    //    无边框顶层窗口的 Top / Left 本身就是屏幕坐标，直接相减即可。
    // ⚠️ 右上角的关闭按钮必须排除在 HTCAPTION 之外：否则系统会把按下当成
    //    「拖动窗口」，✕ 永远收不到 Click（实测踩过）。
    Cy := Y - WizardForm.Top;
    Cx := X - WizardForm.Left;
    if (Cy < ScaleY(TITLEBAR_H)) and (Cx < WizardForm.ClientWidth - ScaleX(52)) then
      Result := HTCAPTION
    else
      Result := HTCLIENT;
    Exit;
  end;
  Result := CallWindowProcW(OldWizardProc, hwnd, msg, wParam, lParam);
end;

procedure HookWizardProc;
begin
  OldWizardProc := SetWindowLongW(WizardForm.Handle, GWLP_WNDPROC,
    CreateCallback(@WizardWndProc));
end;

procedure TitleCloseClick(Sender: TObject);
var
  I: Integer;
begin
  // 点「关闭」等同于点「取消」：Inno 会走自己的取消确认流程。
  // ⚠️ 例外是**完成页**：那一页只剩「完成」，「取消」已被 Inno 禁用，
  //    转发过去毫无反应 —— 主人反馈的「完成向导页面点 ✕ 无反应」就是这个原因。
  if WizardForm.CurPageID = wpFinished then
  begin
    // ⚠️⚠️ 「完成」按钮除了关窗，还会执行 [Run] 段带 postinstall 的条目 ——
    //    也就是**把 SnapLingo 启动起来**。主人 2026-10-09 要求：点 ✕ 只关窗，
    //    不要再打开软件界面。
    //
    //    做法是**把完成页那个「立即运行 SnapLingo」复选框的勾去掉**：
    //    Inno 执行 postinstall 条目时是现读 RunList 勾选状态的，改它才管用。
    //    （2026-10-09 实测，用 computer-use 走完整向导、复选框勾着点 ✕：
    //      安装日志里没有出现任何 Run entry，SnapLingo 也没被拉起。）
    //
    //    ⚠️ 不要改用 [Run] 条目的 Check 函数来拦：那个钩子决定的是
    //       「复选框显不显示」，拦不住「关窗时执不执行」。
    if WizardForm.RunList <> nil then
      for I := 0 to WizardForm.RunList.Items.Count - 1 do
        WizardForm.RunList.Checked[I] := False;
    SendMessage(WizardForm.NextButton.Handle, BM_CLICK, 0, 0);
  end
  else
    SendMessage(WizardForm.CancelButton.Handle, BM_CLICK, 0, 0);
end;

// 注：Inno Pascal 未注册 OnMouseEnter / OnMouseLeave，故关闭按钮不做悬停变色

// ==========================================================================
//  键盘
//  ⚠️ 实测结论：bsNone 并没有破坏 Inno 自己的键盘处理 —— 向导的 Esc / Enter
//     照常工作（前几页靠 Enter 正常推进）。而自己再实现一套反而有害：
//     在「正在安装」页把 Enter 误判成取消，弹出了 Inno 的「退出安装程序」确认框，
//     导致安装流程卡死。所以这里**不做任何键盘拦截**，交给 Inno 原生处理。
// ==========================================================================

// ==========================================================================
//  控件构造辅助
// ==========================================================================
// 从安装包内解出 BMP 并塞进 TBitmapImage。
// ⚠️ 这些素材在 [Files] 里标了 dontcopy（不进目标机器），只存在于安装包内，
//    必须先用 ExtractTemporaryFile 解到 {tmp} 才能加载。
// 加载自绘素材。**安装器与卸载器的来源不同**，靠 IsUninstaller 分流：
//   安装器 —— 素材用 dontcopy 编进 setup.exe，靠 ExtractTemporaryFile 解到 {tmp}；
//   卸载器 —— **不能**调 ExtractTemporaryFile（实测报 "Cannot call
//             ExtractTemporaryFile function during Uninstall."），所以卸载窗体
//             用到的素材改成随程序装到 {app}\ui\，从那里读。
//             卸载窗体在删文件**之前**显示，那时文件还在，读得到。
procedure LoadBmp(Img: TBitmapImage; const FileName: String);
begin
  if IsUninstaller then
    Img.Bitmap.LoadFromFile(ExpandConstant('{app}\ui\') + FileName)
  else
  begin
    ExtractTemporaryFile(FileName);
    Img.Bitmap.LoadFromFile(ExpandConstant('{tmp}\') + FileName);
  end;
end;

// 造一个静态文本。Inno 的 TNewStaticText 默认 AutoSize，混排时不好对齐，统一关掉。
function NewText(Parent: TWinControl; const Cap: String; Size: Integer;
  Color: TColor; Bold: Boolean): TNewStaticText;
begin
  Result := TNewStaticText.Create(Parent);
  Result.Parent := Parent;
  Result.AutoSize := False;
  Result.Caption := Cap;
  Result.Font.Name := 'Microsoft YaHei UI';
  Result.Font.Size := Size;
  Result.Font.Color := Color;
  if Bold then
    Result.Font.Style := [fsBold];
end;

// ==========================================================================
//  自绘标题栏 + 无边框改造
// ==========================================================================
procedure BuildTitleBar;
var
  BarH, W: Integer;
begin
  BarH := ScaleY(TITLEBAR_H);
  W := WizardForm.ClientWidth;

  // 1) 去掉系统标题栏与边框
  //    ⚠️ bsNone 会改变客户区尺寸，必须先存后还原，否则右下会多出一条白边
  WizardForm.BorderStyle := bsNone;
  WizardForm.ClientWidth := W;
  WizardForm.ClientHeight := WizardForm.ClientHeight;

  // 2) 加高窗口，给自绘标题栏腾出空间
  WizardForm.ClientHeight := WizardForm.ClientHeight + BarH;

  // 3) 内容下移，给自绘标题栏腾空间。
  //    ⚠️ 只能动「顶部对齐 / 固定高度」的容器：MainPanel 和 OuterNotebook。
  //       Bevel 与三个按钮（Next/Back/Cancel）带底部锚点，客户区一变高，系统就会
  //       自动把它们下移；这里再手动移一次 = 重复位移，直接把按钮挤出窗口。
  //       实测踩过：按钮 Top 被推到 1086，而窗口高只有 1059 —— 「正在安装」页
  //       连「取消」都点不到，用户只能看着进度条干等。
  // ⚠️ 下移的同时必须**把高度减回去**，让"底边"原地不动。
  //    只改 Top 会让容器向下侵入底部按钮栏 —— 而它们是 TWinControl
  //    （有窗口句柄），会直接吃掉底部区域的鼠标消息：实测底部两个自绘按钮
  //    （图形控件，点击靠主窗口分发）因此完全点不动，而未被覆盖的 ✕ 是好的。
  //    用 WindowFromPoint 抓到覆盖按钮的窗口是 TNewNotebookPage，即此因。
  // ⚠️ 只减 OuterNotebook 的高度，**不要动 MainPanel 的高度**：
  //    MainPanel 本来就完整包含底部按钮栏，它下移后底边正好落在新的窗口底边上；
  //    再减高度会让页面内容被挤上去（实测许可页标题被裁掉上半截）。
  // ⚠️ 页头带同理：内容整体再下移 HeadH，空出来的那条带子交给自绘页头图。
  //    因为页头图是图形控件（会被有句柄的 TNewNotebookPage 压住），
  //    **必须让页面容器物理上不覆盖它** —— 只靠 z-order 是压不过去的。
  // ⚠️ 页面容器还要再下移一个「标题带」的高度：一级标题（PageNameLabel）与
  //    次级文本（PageDescriptionLabel）被搬到主窗口上、固定在上方这条带子里，
  //    页面原有内容必须让开，否则会被那两行字压住。
  WizardForm.MainPanel.Top := WizardForm.MainPanel.Top + BarH;
  WizardForm.OuterNotebook.Top := WizardForm.OuterNotebook.Top + BarH
    + ScaleY(HEAD_NAME_Y);
  WizardForm.OuterNotebook.Height := WizardForm.OuterNotebook.Height - BarH
    - ScaleY(HEAD_NAME_Y);

  // 4) 标题栏底色不单独画：WizardBackColor 本身就是白色，多加一层没有区别。
  //    原先这里放了个白色 TPanel 当底板，但 TPanel 设了 Color 也不绘制，
  //    等于白放 —— 去掉。

  // 5) 标题栏底部 1px 浅灰分隔线
  TitleLine := TBitmapImage.Create(WizardForm);
  TitleLine.Parent := WizardForm;
  TitleLine.Stretch := True;
  TitleLine.SetBounds(0, BarH - ScaleY(1), WizardForm.ClientWidth, ScaleY(1));
  LoadBmp(TitleLine, 'line.bmp');

  // 6) 左侧：**沿用原来的「·」圆点** + 应用名
  //    ⚠️ 主人 2026-10-09 明确要求标题栏不要换成图标，保留原来的圆点样式。
  TitleDot := NewText(WizardForm, '●', 9, CLR_GREEN, False);
  TitleDot.SetBounds(ScaleX(16), ScaleY(12), ScaleX(14), ScaleY(20));

  TitleText := NewText(WizardForm,
    '{#AppName}  {#AppVersion}  安装程序', 10, CLR_INK, False);
  TitleText.SetBounds(ScaleX(34), ScaleY(13), ScaleX(300), ScaleY(20));

  // 7) 右侧：关闭按钮（圆角方框 + ✕ 的图片，点击等同「取消」）
  TitleClose := TBitmapImage.Create(WizardForm);
  TitleClose.Parent := WizardForm;
  TitleClose.Stretch := True;
  TitleClose.Cursor := crHandPoint;
  TitleClose.SetBounds(WizardForm.ClientWidth - ScaleX(46), ScaleY(8),
    ScaleX(30), ScaleY(30));
  TitleClose.OnClick := @TitleCloseClick;
  LoadBmp(TitleClose, 'btn-close.bmp');
end;

// ==========================================================================
//  左栏：整幅深绿图片（含图标 / 字标 / 步骤列表，所有页常驻）
// ==========================================================================
procedure BuildLeftPanel;
var
  PW, PH: Integer;
begin
  PW := ScaleX(LEFT_W);
  PH := WizardForm.ClientHeight - ScaleY(TITLEBAR_H);

  // ⚠️ 用 TBitmapImage 而不是 TPanel：TPanel 设了 Color 也不绘制，左栏会整片变白。
  //    图片控件还顺带免掉了「Enabled=False 让鼠标穿透」的必要性 —— 它本身不拦截
  //    鼠标消息，WM_NCHITTEST 照旧落到 WizardForm，拖动完全不受影响。
  LeftPanel := TBitmapImage.Create(WizardForm);
  LeftPanel.Parent := WizardForm;
  LeftPanel.Stretch := True;
  LeftPanel.SetBounds(0, ScaleY(TITLEBAR_H), PW, PH);
  // 默认高亮第 1 步；切页时由 UpdateStepHighlight 换成 left-2/3/4
  LoadBmp(LeftPanel, 'left-1.bmp');
  LeftPanel.SendToBack;      // 垫底，别压住右栏

  // 自绘左栏已接管左侧区域：让 Inno 原有的左栏大图让位，
  // 并把页面容器右移，否则页面内容会被自绘左栏盖住
  // ⚠️ 控件名是 WizardBitmapImage（左栏）与 WizardBitmapImage2（完成页大图），
  //    不叫 WizardImage —— 后者是编译不过的（实测 Unknown identifier）
  WizardForm.WizardBitmapImage.Visible := False;
  WizardForm.WizardBitmapImage2.Visible := False;
  WizardForm.OuterNotebook.Left := PW;
  WizardForm.OuterNotebook.Width := WizardForm.ClientWidth - PW;

  // Inno 默认的欢迎页文字由自绘内容取代
  WizardForm.WelcomeLabel1.Visible := False;
  WizardForm.WelcomeLabel2.Visible := False;
end;

// 切页时换左栏整幅图来高亮当前步。
// 4 个版本都是构建期预生成的（left-1..4），运行时不画图，也就没有渲染差异。
procedure UpdateStepHighlight(Idx: Integer);
begin
  if (Idx >= 0) and (Idx <= 3) then
    LoadBmp(LeftPanel, 'left-' + IntToStr(Idx + 1) + '.bmp');
end;

// ==========================================================================
//  欢迎页右栏：整幅图片（标题 / 胶囊 / 副标题 / 三张卡片 / 步数，仅欢迎页显示）
// ==========================================================================
procedure BuildWelcomeExtras;
var
  PW, BX, BY: Integer;
begin
  PW := ScaleX(LEFT_W);

  // ⚠️ 高度**只到卡片下方，绝不能铺到窗口底部**。底部两个自绘按钮是图形控件
  //    （TBitmapImage = TGraphicControl，没有自己的窗口句柄），点击由父窗口按
  //    z-order 分发 —— 被这张图盖住就永远收不到 Click。实测：按钮日志里一条标记
  //    都没有，而没被盖住的 ✕ 是正常的。让大图物理上不压住按钮才是彻底解法。
  W_Right := TBitmapImage.Create(WizardForm);
  W_Right.Parent := WizardForm;
  W_Right.Stretch := True;
  W_Right.SetBounds(PW, ScaleY(TITLEBAR_H),
    WizardForm.ClientWidth - PW, ScaleY(RIGHT_H));
  LoadBmp(W_Right, 'welcome-right.bmp');

  // 「第 N 步，共 4 步」摆到**取消按钮**的左侧，跟按钮垂直居中对齐。
  // ⚠️ 注意是"取消"的左侧而不是"下一步"的左侧 —— 后者的位置正好压在取消按钮上
  //    （实测截图里文字被按钮盖住一半）。
  BX := WizardForm.ClientWidth - ScaleX(BTN_MARGIN_R) - ScaleX(BTN_W);
  BY := WizardForm.ClientHeight - ScaleY(BTN_MARGIN_B) - ScaleY(BTN_H)
        + ScaleY((BTN_H - STEP_H) div 2);
  W_Step := TBitmapImage.Create(WizardForm);
  W_Step.Parent := WizardForm;
  W_Step.Stretch := True;
  W_Step.SetBounds(
    BX - ScaleX(BTN_W + 2 * BTN_GAP + STEP_W), BY,
    ScaleX(STEP_W), ScaleY(STEP_H));
  LoadBmp(W_Step, 'welcome-step.bmp');
end;

// ==========================================================================
//  许可页阅读框的顶边线
//
//  Inno 的许可阅读框只画了左 / 右 / 下三条边，**顶部是空的** —— 放大截图逐像素
//  确认过：左边是一条中灰细线，顶边什么都没有。它并不是 bsNone，所以补
//  `BorderStyle := bsSingle` 只会再套一圈黑框，与原有的浅灰三条边完全不搭；
//  这里改为单独补一条与左边同色的顶线。
//
//  ⚠️ 线必须放在**有窗口句柄**的外壳里：TBitmapImage 是图形控件，会被有句柄的
//     TNewNotebookPage 压在下面（同一个坑在按钮那里已经踩过）。
//  ⚠️ 摆位用两个 ClientOrigin 相减换算客户区坐标 —— Inno 的 external 不能传
//     POINT 结构指针，`MapWindowPoints` 那条路走不通；ClientOrigin 两边都有，
//     相减即可，也不用去层层累加嵌套页面的偏移。
// ==========================================================================
procedure BuildLicenseTopLine;
begin
  MemoTopLineShell := TPanel.Create(WizardForm);
  MemoTopLineShell.Parent := WizardForm;
  MemoTopLineShell.BevelOuter := bvNone;
  MemoTopLineShell.Visible := False;

  MemoTopLineImg := TBitmapImage.Create(MemoTopLineShell);
  MemoTopLineImg.Parent := MemoTopLineShell;
  MemoTopLineImg.Stretch := True;
  MemoTopLineImg.SetBounds(0, 0, ScaleX(200), ScaleY(1));
  LoadBmp(MemoTopLineImg, 'line-frame.bmp');
end;

// 把一个控件的位置换算成 WizardForm 的客户区坐标。
// ⚠️ Inno 的 TControl **没有** ClientOrigin / ClientToScreen（实测编译报
//    Unknown identifier 'CLIENTORIGIN'），而 external 又传不了 POINT 结构指针
//    （MapWindowPoints 那条路走不通），所以只能沿 Parent 链把 Left / Top 累加。
//    notebook 内部那点 tab 边距不会反映在子控件的 Left 上，误差用下面的常量补。
procedure ClientPosOf(C: TControl; var X, Y: Integer);
var
  P: TWinControl;
begin
  X := C.Left;
  Y := C.Top;
  P := C.Parent;
  while (P <> nil) and (P.Handle <> WizardForm.Handle) do
  begin
    X := X + P.Left;
    Y := Y + P.Top;
    P := P.Parent;
  end;
end;

procedure PlaceLicenseTopLine;
var
  X, Y, LineW: Integer;
begin
  if MemoTopLineShell = nil then
    Exit;
  ClientPosOf(WizardForm.LicenseMemo, X, Y);
  // 线宽必须跟着阅读框走。
  // ⚠️ 之前只把外壳设成框宽、图片却写死 `ScaleX(200)`，结果线只画了六成、
  //    看起来「断了一半」（实测：框线 364px，我的线只有 227px）。
  LineW := WizardForm.LicenseMemo.Width + ScaleX(2);
  // ⚠️ 纵向位置要落在**框自带的左右边线起点**上，不能放在阅读框客户区顶。
  //    实测：框的左右边线是从客户区顶再往下 6px 才开始的（扫描出来各长 231px，
  //    而框高 237px），顶线若放在客户区顶就会与左右线之间空出 6px，看着「没连上」。
  //    这 6px 是 Inno 阅读框自己的内边距、按物理像素计，所以这里不加 Scale。
  MemoTopLineShell.SetBounds(X - ScaleX(1), Y + 6, LineW, ScaleY(1));
  MemoTopLineImg.SetBounds(0, 0, LineW, ScaleY(1));
  MemoTopLineShell.BringToFront;
end;

// 阅读框只用来「读」：点它不该像输入框那样冒出插入符（主人反馈）。
// 点一下就立刻把焦点交回窗体，插入符随焦点消失；鼠标仍在正文上，滚轮照常可用。
// ⚠️ Inno 的 TWinControl 没有 `SetFocus`（实测编译报 Unknown identifier 'SETFOCUS'），
//    要把焦点摘掉得用 `ActiveControl := nil`。
procedure LicenseMemoClick(Sender: TObject);
begin
  WizardForm.ActiveControl := nil;
end;

// 把页头这几个标签的底色刷成窗口白。
// ⚠️ 关键是 `StyleElements := []` —— Inno 的向导控件默认**走主题绘制**，主题会用自己的
//    颜色盖掉我们设的 `Color`，这正是「灰底反复出现、怎么刷都刷不掉」的原因
//    （早先 TPanel 设了 Color 却不绘制，也是同一个坑）。关掉主题后 `Color` 才说了算。
// ⚠️ 不要用 `ParentBackground := True`：那只是让标签透出**父窗口**的底色，而父窗口
//    （MainPanel）本身就是主题灰 —— 实测那样灰框照样在。
// ⚠️ 必须反复刷：Inno 在切页流程里会重设这些属性，只在 InitializeWizard 设一次不够。
procedure RepaintHeadTextColors;
begin
  if WizardForm = nil then
    Exit;
  WizardForm.PageNameLabel.StyleElements := [];
  WizardForm.PageNameLabel.Color := CLR_WHITE;
  WizardForm.PageDescriptionLabel.StyleElements := [];
  WizardForm.PageDescriptionLabel.Color := CLR_WHITE;
  WizardForm.FinishedHeadingLabel.StyleElements := [];
  WizardForm.FinishedHeadingLabel.Color := CLR_WHITE;
  WizardForm.FinishedLabel.StyleElements := [];
  WizardForm.FinishedLabel.Color := CLR_WHITE;
end;

// ==========================================================================
//  各页的「一级标题 + 次级文本」—— 调整 Inno **原本就有**的那两行，不另开页头
//
//  Inno 各页本来就带着标题与说明，只是分属两组控件：
//      许可 / 安装位置页 —— `PageNameLabel`（页面名）+ `PageDescriptionLabel`
//      完成页           —— `FinishedHeadingLabel` + `FinishedLabel`
//  主人 2026-10-09 的要求是：把这两行**调**成与第一页一致的字号、位置与字重，
//  让二、三、四页看起来是同一套版式。
//
//  做法：把这几个标签从页面容器里**搬到主窗口上**，位置按第一页的规格写死，
//  四页因此共用同一处坐标，天然对齐；文字内容仍由 Inno 按页自动填。
//  标签已不在页面容器内，页面自身的原有内容不需要逐个挪位置
//  （容器整体下移 HEAD_NAME_Y 给标题带让位，见 BuildTitleBar）。
//
//  ⚠️ 为什么非搬不可：这些标签原本是 `TNewNotebookPage` 的子控件，而页面容器
//     是有窗口句柄的控件，会把子控件的自由定位限制在容器范围内 —— 想放到
//     容器上方那条标题带里，会被直接裁掉。
//  ⚠️ `TNewStaticText` 不理会 `Font.Color`（实测屏幕采样仍为纯黑）：所以次级文本
//     到底能不能变浅不取决于这里写不写，写上是「能生效就生效」。
// ==========================================================================
procedure SetupPageHeadText;
var
  X, W: Integer;
begin
  X := ScaleX(LEFT_W + 34);                     // 与欢迎页右栏内容的左边距同源
  W := WizardForm.ClientWidth - X - ScaleX(34);

  // ---- 一级标题：第一页是 19px。Font.Size 的单位是**点**，96dpi 下 19px ≈ 14pt；
  //      Inno 会按向导字体的 PixelsPerInch 自动做 DPI 缩放，点值在各分辨率都成立。
  // ⚠️ 必须把 `Color` 显式改成窗口底色（白）。这几个标签原本待在页面容器里，
  //    背景被页面的白底盖着看不出来；一旦搬到主窗口，`TNewStaticText` 默认的
  //    `clBtnFace`（浅灰）底色就露出来，变成一条条灰底文字块（主人截图里那两块灰条）。
  WizardForm.PageNameLabel.Parent := WizardForm;
  WizardForm.PageNameLabel.Color := CLR_WHITE;
  WizardForm.PageNameLabel.Font.Size := 14;
  WizardForm.PageNameLabel.Font.Style := [];    // 主人要求：所有字体都不加粗
  WizardForm.PageNameLabel.SetBounds(X,
    ScaleY(TITLEBAR_H + HEAD_NAME_Y) - ScaleY(11), W, ScaleY(22));

  WizardForm.FinishedHeadingLabel.Parent := WizardForm;
  WizardForm.FinishedHeadingLabel.Color := CLR_WHITE;
  WizardForm.FinishedHeadingLabel.Font.Size := 14;
  WizardForm.FinishedHeadingLabel.Font.Style := [];
  WizardForm.FinishedHeadingLabel.SetBounds(X,
    ScaleY(TITLEBAR_H + HEAD_NAME_Y) - ScaleY(11), W, ScaleY(22));

  // ---- 次级文本：第一页是 13px ≈ 10pt ----
  WizardForm.PageDescriptionLabel.Parent := WizardForm;
  WizardForm.PageDescriptionLabel.Color := CLR_WHITE;
  WizardForm.PageDescriptionLabel.Font.Size := 10;
  WizardForm.PageDescriptionLabel.Font.Color := CLR_GRAY;
  WizardForm.PageDescriptionLabel.SetBounds(X,
    ScaleY(TITLEBAR_H + HEAD_DESC_Y) - ScaleY(9), W, ScaleY(20));

  WizardForm.FinishedLabel.Parent := WizardForm;
  WizardForm.FinishedLabel.Color := CLR_WHITE;
  WizardForm.FinishedLabel.Font.Size := 10;
  WizardForm.FinishedLabel.Font.Color := CLR_GRAY;
  WizardForm.FinishedLabel.SetBounds(X,
    ScaleY(TITLEBAR_H + HEAD_DESC_Y) - ScaleY(9), W, ScaleY(60));

  // ---- 许可页：把阅读框的边框补成完整的一套 ----
  // Inno 的许可阅读框（`TRichEditViewer`）天然只画左 / 右 / 下三条边，顶部是空的
  //（放大截图逐像素确认过：左边是一条中灰细线，顶边什么都没有）。
  // 它不是 `bsNone`，所以不能再上一个 `bsSingle` 补边 —— 那样会变成四周一圈的
  // 黑框，与原有的浅灰三条边完全不搭。改为**单独补一条顶线**：
  // 一个只有句柄的外壳 + 1px 图片，摆在阅读框正上方 1px 处。
  BuildLicenseTopLine;
end;

// 安装进度页的实时百分比文字。只在进度页出现，位置在进度条正下方。
procedure BuildProgressLabel;
begin
  ProgPctLabel := NewText(WizardForm, '', 10, CLR_INK, False);
  ProgPctLabel.Color := CLR_WHITE;
  ProgPctLabel.Visible := False;
end;

// 换按钮贴图。同一张就不重复解压+读盘，避免无谓闪烁。
procedure SetBtnImage(Img: TBitmapImage; var CurFile: String;
  const FileName: String);
begin
  if CurFile = FileName then
    Exit;
  LoadBmp(Img, FileName);
  CurFile := FileName;
end;

// ==========================================================================
//  向导按钮 + 欢迎页内容的整体更新（每次切页调用）
//
//  布局约定（主人 2026-10-09 指定：第二页起统一用欢迎页那套样式）：
//      欢迎页     ->  [取消]   [下一步]
//      许可/目录  ->  [上一步] [下一步]
//      完成页     ->           [完成]
//      其余页（预备 / 正在安装）-> 全部隐藏，交回 Inno 原生按钮
//
//  ⚠️ 外壳必须用 TPanel（TWinControl），不能直接用 TBitmapImage：
//     Inno 的页面容器 TNewNotebookPage 是**有窗口句柄**的控件，而 TBitmapImage
//     是图形控件（无句柄、画在父窗口客户区）。**子窗口永远盖在图形控件之上**，
//     所以纯图片按钮在向导页上会被页面容器压住、永远收不到点击
//     （实测：按钮位置上 WindowFromPoint 返回的正是 TNewNotebookPage）。
//     外壳负责占位与接点击，外观交给里面的图片 —— 顺带也绕开了
//     「TPanel 设了 Color 却不绘制」那个坑。
//  ⚠️ 外壳**始终 Enabled**：禁用态靠换图表现，点击照旧转发给原生按钮，
//     原生按钮禁用时 BM_CLICK 自然无效 —— 省掉一整套状态同步逻辑。
//  ⚠️ 原生按钮不能用 Visible=False 藏：Inno 会判定「无法前进到下一页」直接
//     Abort（实测退出码 1）。只能挪位置到窗外，原坐标存下来、需要时归位。
// ==========================================================================
procedure UpdateWizardChrome(PageID: Integer);
var
  BW, BH, Gap, Y, X: Integer;
  WantPrev, WantCancel, WantNext, IsFinish, ShowHead: Boolean;
begin
  case PageID of
    wpWelcome:
      begin WantPrev := False; WantCancel := True;  WantNext := True;  end;
    wpLicense, wpSelectDir, wpSelectTasks, wpSelectProgramGroup:
      begin WantPrev := True;  WantCancel := False; WantNext := True;  end;
    wpFinished:
      begin WantPrev := False; WantCancel := False; WantNext := True;  end;
    else
      begin WantPrev := False; WantCancel := False; WantNext := False; end;
  end;
  IsFinish := (PageID = wpFinished);

  // 欢迎页专属内容
  W_Right.Visible := (PageID = wpWelcome);
  W_Step.Visible := (PageID = wpWelcome);

  // ⚠️ 显隐一律**按页显式指定**，不要读 Caption 反推 —— Inno 更新页面名/说明的
  //    时机不由我们掌握，读到上一页的文字就会把旧的标题留在新课上。
  //    两组标签分工：页面名/说明给「许可 / 安装位置」系列，完成页走 Finished* 那一对。
  ShowHead := (PageID = wpLicense) or (PageID = wpSelectDir)
    or (PageID = wpSelectTasks) or (PageID = wpSelectProgramGroup);
  WizardForm.PageNameLabel.Visible := ShowHead;
  WizardForm.PageDescriptionLabel.Visible := ShowHead;
  WizardForm.FinishedHeadingLabel.Visible := (PageID = wpFinished);
  WizardForm.FinishedLabel.Visible := (PageID = wpFinished);

  // 每次切页都把标签底色刷回白 —— 见 RepaintHeadTextColors 的说明
  RepaintHeadTextColors;

  // ⚠️ 安装位置页自带的这行说明（「安装程序将把 X 安装到下面的文件夹中…」）与页头
  //    的说明是同一个意思。两个都显示，就成了主人截图里的「切换页面有残留」——
  //    其实不是残影，是**两行说明叠在一起**。这里让原生的那行退场。
  if PageID = wpSelectDir then
  begin
    WizardForm.SelectDirLabel.Visible := False;
    WizardForm.SelectDirBrowseLabel.Visible := False;
  end;

  // ⚠️ 这几个标签已被搬到主窗口上（不再是页面容器的子控件），会被有句柄的
  //    TNewNotebookPage 在 z-order 上盖住 —— 每次切页都要重新置顶一次。
  if ShowHead or (PageID = wpFinished) then
  begin
    WizardForm.PageNameLabel.BringToFront;
    WizardForm.PageDescriptionLabel.BringToFront;
    WizardForm.FinishedHeadingLabel.BringToFront;
    WizardForm.FinishedLabel.BringToFront;
  end;

  // 记下原生按钮的原始位置（只记一次）
  if not NativeSaved then
  begin
    NativeNextL := WizardForm.NextButton.Left;
    NativeNextT := WizardForm.NextButton.Top;
    NativeNextW := WizardForm.NextButton.Width;
    NativeNextH := WizardForm.NextButton.Height;
    NativeBackL := WizardForm.BackButton.Left;
    NativeBackT := WizardForm.BackButton.Top;
    NativeBackW := WizardForm.BackButton.Width;
    NativeBackH := WizardForm.BackButton.Height;
    NativeCancelL := WizardForm.CancelButton.Left;
    NativeCancelT := WizardForm.CancelButton.Top;
    NativeCancelW := WizardForm.CancelButton.Width;
    NativeCancelH := WizardForm.CancelButton.Height;
    NativeSaved := True;
  end;

  // 被自绘接管的原生按钮挪到窗外，其余归位
  if WantNext then
    WizardForm.NextButton.SetBounds(-4000, 0, NativeNextW, NativeNextH)
  else
    WizardForm.NextButton.SetBounds(NativeNextL, NativeNextT,
      NativeNextW, NativeNextH);

  if WantPrev then
    WizardForm.BackButton.SetBounds(-4000, 0, NativeBackW, NativeBackH)
  else
    WizardForm.BackButton.SetBounds(NativeBackL, NativeBackT,
      NativeBackW, NativeBackH);

  if WantNext or WantCancel then
    WizardForm.CancelButton.SetBounds(-4000, 0, NativeCancelW, NativeCancelH)
  else
    WizardForm.CancelButton.SetBounds(NativeCancelL, NativeCancelT,
      NativeCancelW, NativeCancelH);

  // 自绘按钮：统一摆右下角，左格 + 右格
  BW := ScaleX(BTN_W);
  BH := ScaleY(BTN_H);
  Gap := ScaleX(BTN_GAP);
  Y := WizardForm.ClientHeight - ScaleY(BTN_MARGIN_B) - BH;
  X := WizardForm.ClientWidth - ScaleX(BTN_MARGIN_R) - BW;

  if WantNext then
  begin
    BtnNextShell.SetBounds(X, Y, BW, BH);
    if IsFinish then
      SetBtnImage(BtnNextImg, NextImgFile, 'btn-finish.bmp')
    else if WizardForm.NextButton.Enabled then
      SetBtnImage(BtnNextImg, NextImgFile, 'btn-primary.bmp')
    else
      SetBtnImage(BtnNextImg, NextImgFile, 'btn-next-off.bmp');
    BtnNextShell.BringToFront;
  end
  else
    BtnNextShell.SetBounds(-4000, 0, BW, BH);

  if WantPrev or WantCancel then
  begin
    BtnLeftShell.SetBounds(X - Gap - BW, Y, BW, BH);
    if WantCancel then
      SetBtnImage(BtnLeftImg, LeftImgFile, 'btn-ghost.bmp')
    else
      SetBtnImage(BtnLeftImg, LeftImgFile, 'btn-prev.bmp');
    LeftIsCancel := WantCancel;
    BtnLeftShell.BringToFront;
  end
  else
    BtnLeftShell.SetBounds(-4000, 0, BW, BH);

  // ⚠️ 显隐/移位之后必须显式重绘，否则屏幕上会留下残影
  //    （单靠 InvalidateRect 实测无效，见文件里 RedrawWindow 的说明）
  RedrawWindow(WizardForm.Handle, 0, 0,
    RDW_INVALIDATE or RDW_ERASE or RDW_ALLCHILDREN or RDW_UPDATENOW);
end;

// 许可页勾选「同意 / 不同意」时 Inno 会立刻启用或禁用「下一步」，
// 自绘按钮要跟着换图（可用=深绿、禁用=浅灰），否则显示与实际状态对不上。
procedure LicenseRadioClick(Sender: TObject);
begin
  // ⚠️⚠️ 最容易踩的一个坑：给 LicenseAcceptedRadio.OnClick 赋值是**覆盖**，
  //    不是追加。Inno 自己在这个事件里的处理只有一行 —— 就是下面这句
  //    「按勾选状态启用/禁用下一步」。被我们覆盖掉却没补回来，
  //    症状就是：正文滚到底了、单选钮也勾上了（界面显示已选中），
  //    但「下一步」永远保持灰色禁用、点了毫无反应，整条流程卡死在许可页。
  WizardForm.NextButton.Enabled := WizardForm.LicenseAcceptedRadio.Checked;

  // ⚠️ 这里不能用 CurPageID —— 它只是 CurPageChanged 的**参数**，不是全局变量
  //    （编译报 Unknown identifier）。当前页要从 WizardForm 上取。
  UpdateWizardChrome(WizardForm.CurPageID);
end;

// ==========================================================================
//  向导按钮的点击：自绘按钮不自己实现逻辑，统一转发给对应的原生按钮 ——
//  这样 Inno 的校验（许可页没勾同意就前进）、页面跳转、取消确认流程全都沿用
//  官方行为，我们只换外观。
// ==========================================================================
procedure BtnNextClick(Sender: TObject);
begin
  SendMessage(WizardForm.NextButton.Handle, BM_CLICK, 0, 0);
end;

procedure BtnLeftClick(Sender: TObject);
begin
  // 左格在欢迎页是「取消」，第二页起是「上一步」
  if LeftIsCancel then
    SendMessage(WizardForm.CancelButton.Handle, BM_CLICK, 0, 0)
  else
    SendMessage(WizardForm.BackButton.Handle, BM_CLICK, 0, 0);
end;

procedure BuildCustomButtons;
var
  W, H: Integer;
begin
  W := ScaleX(BTN_W);
  H := ScaleY(BTN_H);

  // 左格：外壳 TPanel（TWinControl）+ 内贴图。外壳才是"占层级"的那一层，
  // 必须是有窗口句柄的控件，理由见 UpdateWizardChrome 上方的长注释。
  BtnLeftShell := TPanel.Create(WizardForm);
  BtnLeftShell.Parent := WizardForm;
  BtnLeftShell.BevelOuter := bvNone;
  BtnLeftShell.Cursor := crHandPoint;
  BtnLeftShell.OnClick := @BtnLeftClick;
  BtnLeftShell.SetBounds(-4000, 0, W, H);

  BtnLeftImg := TBitmapImage.Create(BtnLeftShell);
  BtnLeftImg.Parent := BtnLeftShell;
  BtnLeftImg.Stretch := True;
  BtnLeftImg.OnClick := @BtnLeftClick;   // 图片会吃掉点击，也接上同一个处理
  BtnLeftImg.SetBounds(0, 0, W, H);

  // 右格：下一步 / 完成，同理
  BtnNextShell := TPanel.Create(WizardForm);
  BtnNextShell.Parent := WizardForm;
  BtnNextShell.BevelOuter := bvNone;
  BtnNextShell.Cursor := crHandPoint;
  BtnNextShell.OnClick := @BtnNextClick;
  BtnNextShell.SetBounds(-4000, 0, W, H);

  BtnNextImg := TBitmapImage.Create(BtnNextShell);
  BtnNextImg.Parent := BtnNextShell;
  BtnNextImg.Stretch := True;
  BtnNextImg.OnClick := @BtnNextClick;
  BtnNextImg.SetBounds(0, 0, W, H);

  // 贴图状态清空，让首次 UpdateWizardChrome 一定会真正加载
  NextImgFile := '';
  LeftImgFile := '';
end;

// ==========================================================================
//  安装向导初始化
// ==========================================================================
procedure InitializeWizard;
begin
  // ⚠️ 这两行是**性能探针**，不是调试残留：本向导要 ExtractTemporaryFile 解一批
  //    自绘素材，而本脚本用 SolidCompression=yes（所有文件一条压缩流，无法随机
  //    访问）—— 素材在 [Files] 里的**位置**直接决定解压它们要先吞掉多少数据。
  //    实测素材排在末尾时窗口可见要 11.97s，移到最前后降到 1s 级。
  //    加这两行后，跑 `Setup.exe /VERYSILENT /LOG=x.log` 就能从日志时间戳
  //    直接量出这段耗时；Log() 只在带 /LOG 时写文件，正常安装无副作用。
  //    详见 README §43「安装包启动速度」。
  Log('SNAPLINGO-PERF: InitializeWizard begin');
  BuildTitleBar;
  BuildLeftPanel;
  BuildWelcomeExtras;
  SetupPageHeadText;
  BuildProgressLabel;
  BuildCustomButtons;
  ApplyRoundedCorners(WizardForm);
  HookWizardProc;

  // 许可页勾选「同意 / 不同意」时 Inno 会立刻启用或禁用「下一步」，
  // 自绘的下一步按钮必须跟着换图，否则显示与实际状态对不上。
  WizardForm.LicenseAcceptedRadio.OnClick := @LicenseRadioClick;
  WizardForm.LicenseNotAcceptedRadio.OnClick := @LicenseRadioClick;
  // 阅读框：点它不产生插入符（见 LicenseMemoClick 的说明）
  WizardForm.LicenseMemo.OnClick := @LicenseMemoClick;
  Log('SNAPLINGO-PERF: InitializeWizard end');
end;

// 切页：更新左栏步骤高亮 + 欢迎页内容显隐 + 向导按钮组合
// ⚠️ Inno 会在 InitializeWizard **之前**就对首页触发一次 CurPageChanged，
//    那时自建控件还不存在，直接访问会访问冲突（0xC0000005，实测踩过）。
// ==========================================================================
//  切页的「提前量」—— 在按钮点下的那一刻就调整欢迎页自绘内容的显隐
//
//  ⚠️ 为什么不能只在 CurPageChanged 里做：Inno 的时序是「**先把 notebook 切到新页、
//     再触发 CurPageChanged**」。等我们在 CurPageChanged 里隐藏欢迎页的自绘内容时，
//     新页的控件早已显示出来 —— 中间那一两帧就是主人看到的「两个页面叠在一起」
//     （截图实证：欢迎页的卡片框和许可页的阅读框叠着出现）。
//     所以在「离开 / 返回欢迎页」的点击瞬间就先把自绘内容收掉 / 摆回来。
//  ⚠️ 只对欢迎页动手：该页没有任何校验，点下去必定前进/后退，不存在
//     「隐藏了却没走成」的情况。返回方向只在上一页确实是欢迎页时才恢复。
// ==========================================================================
procedure PreAdjustForPageChange(GoingBack: Boolean);
begin
  if LeftPanel = nil then
    Exit;

  // ⚠️ 顺手把标签底色再刷一遍白：Inno 在切页流程里会重设这几个标签的属性，
  //    只在 InitializeWizard 设一次不够 —— 稳态是白的，过渡那几帧又变回灰，
  //    就是主人看到的「切换时字体背后有几帧长方形灰框」。
  RepaintHeadTextColors;

  if GoingBack then
  begin
    // 许可页的「上一步」就是回欢迎页
    if WizardForm.CurPageID = wpLicense then
    begin
      W_Right.Visible := True;
      W_Step.Visible := True;
    end;
  end
  else
  begin
    // 离开欢迎页：立刻收掉，别等 CurPageChanged
    if WizardForm.CurPageID = wpWelcome then
    begin
      W_Right.Visible := False;
      W_Step.Visible := False;
    end;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  PreAdjustForPageChange(False);
  Result := True;
end;

function BackButtonClick(CurPageID: Integer): Boolean;
begin
  PreAdjustForPageChange(True);
  Result := True;
end;

procedure CurPageChanged(CurPageID: Integer);
var
  Idx, PX, PY: Integer;
begin
  // 以 LeftPanel 是否已建作为"初始化完成"的判据
  if LeftPanel = nil then
    Exit;

  if CurPageID = wpWelcome then
    Idx := 0
  else if CurPageID = wpLicense then
    Idx := 1
  else if (CurPageID = wpSelectDir) or (CurPageID = wpSelectTasks) then
    Idx := 2
  else
    Idx := 3;

  UpdateStepHighlight(Idx);
  UpdateWizardChrome(CurPageID);

  // 许可阅读框：默认是**可编辑**的，鼠标点进去会冒出插入符、像输入框一样
  // （主人反馈「里面的文本不应该能被鼠标点击」）。许可正文只需要能读、能滚、
  // 能选中复制，设成只读即可去掉插入符与编辑能力。
  if CurPageID = wpLicense then
  begin
    WizardForm.LicenseMemo.ReadOnly := True;
    WizardForm.LicenseMemo.TabStop := False;
  end;

  // 阅读框顶线只在许可页出现（并每次重新贴合阅读框的实际位置）
  if MemoTopLineShell <> nil then
  begin
    MemoTopLineShell.Visible := (CurPageID = wpLicense);
    if CurPageID = wpLicense then
      PlaceLicenseTopLine;
  end;

  // 进度页的实时百分比：只在进度页显示，贴在进度条正下方。
  // 坐标用 ClientPosOf 换算 —— 进度条在页面容器里，我们的标签挂在主窗口上。
  if ProgPctLabel <> nil then
  begin
    ProgPctLabel.Visible := (CurPageID = wpInstalling);
    if CurPageID = wpInstalling then
    begin
      ClientPosOf(WizardForm.ProgressGauge, PX, PY);
      ProgPctLabel.SetBounds(PX,
        PY + WizardForm.ProgressGauge.Height + ScaleY(10),
        WizardForm.ProgressGauge.Width, ScaleY(20));
      ProgPctLabel.Caption := '正在安装…';
      ProgPctLabel.BringToFront;
    end;
  end;

end;

// 安装进度实时刷新。
// Inno 默认只在每个文件解压完成时动一次进度，本项目文件少而大，中间那段时间进度条
// 看着像卡住 —— 这里用进度变化事件把百分比实时写到界面上，顺带同步进度条。
procedure CurInstallProgressChanged(CurProgress, MaxProgress: Integer);
var
  Pct: Integer;
begin
  if ProgPctLabel = nil then
    Exit;
  if MaxProgress > 0 then
    Pct := (CurProgress * 100) div MaxProgress
  else
    Pct := 0;
  ProgPctLabel.Caption := '正在安装… ' + IntToStr(Pct) + '%';
  WizardForm.ProgressGauge.Position := CurProgress;
end;

// ⚠️ 收尾必须把旧 WndProc 装回去 —— 这是子类化不可省的一步。
//    只靠 WM_NCDESTROY 不够：实测 Inno 的收尾顺序是「先销毁脚本引擎（连同回调对象），
//    再销毁窗口」，等 WM_NCDESTROY 到来时回调已经没了，系统调到一个失效指针，
//    安装器进程就以 0xC000041D (STATUS_FATAL_USER_CALLBACK_EXCEPTION) 退出。
//    （现象很迷惑：安装本身完全成功，文件/注册表/自启全对，只是退出码不干净。）
//    DeinitializeSetup 在脚本引擎销毁**之前**触发，是唯一可靠的时机。
procedure DeinitializeSetup;
begin
  if (OldWizardProc <> 0) and (WizardForm <> nil) then
  begin
    SetWindowLongW(WizardForm.Handle, GWLP_WNDPROC, OldWizardProc);
    OldWizardProc := 0;
  end;
end;

// ==========================================================================
//  卸载：进度窗体同样做无边框 + 圆角
// ==========================================================================
procedure InitializeUninstallProgressForm;
var
  W, H: Integer;
begin
  W := UninstallProgressForm.ClientWidth;
  H := UninstallProgressForm.ClientHeight;
  UninstallProgressForm.BorderStyle := bsNone;
  UninstallProgressForm.ClientWidth := W;
  UninstallProgressForm.ClientHeight := H;
  ApplyRoundedCorners(UninstallProgressForm);
end;

// ==========================================================================
//  卸载：自定义「候选删除项」询问窗体
//  说明：空壳阶段候选数据是写死的假数据，接入真实程序后改成实际探测
// ==========================================================================
const
  OPT_COUNT = 4;

  // ---- 卸载询问窗体的版式（对照主人 2026-10-09 设计稿，2026-10-09 二轮紧凑化）----
  // ⚠️ 缩放倍率已用探针实测（packaging\probe\scale_probe.iss）：
  //    ScaleX = ScaleY = 1.0 —— 本机 Inno 不做任何缩放，这些数就是屏幕像素。
  //    仍然一律套 ScaleX/ScaleY，换高 DPI 机器时不会走形。
  // 二轮紧凑化：整窗 620x575 → 540x486，字号同步下调一档（见 make_uninstall_assets.py）。
  UN_W = 540;              // 窗体宽
  UN_H = 476;              // 窗体高（二轮再收：按钮下方留白从 18 收到 8）
  UN_CARD_X = 24;          // 卡片左边距
  UN_CARD_W = 492;         // 卡片宽
  UN_CARD_H = 50;          // 卡片高
  UN_CARD_Y0 = 130;        // 第一张卡片顶边
  UN_CARD_STEP = 58;       // 卡片间距 = 高 50 + 缝 8
  UN_CHK_IN_X = 14;        // 勾选框在卡片内的位置
  UN_CHK_IN_Y = 18;
  UN_CHK_S = 15;           // 勾选框可见边长
  UN_CHK_PAD = 4;          // 点击热区在可见框外再放 4px
  UN_WARN_X = 24;          // 警示条
  UN_WARN_Y = 368;
  UN_WARN_W = 492;
  UN_WARN_H = 34;
  UN_CLOSE_X = 500;        // 标题栏 ✕
  UN_CLOSE_Y = 7;
  UN_CLOSE_S = 26;
  UN_BTN_Y = 438;          // 底部两个按钮
  UN_BTN_H = 30;
  UN_CANCEL_X = 358;
  UN_CANCEL_W = 62;
  UN_OK_X = 430;
  UN_OK_W = 86;
  UN_MODEL_IDX = 2;        // 哪一项是「离线翻译模型」（决定警示条里的体积文案）
  UN_TITLEBAR_H = 40;      // 标题栏高度（拖动窗口的判定区）

  // ---- 运行时绘制的动态文字（位置与 make_uninstall_assets.py 对齐）----
  // ⚠️ 字号：素材里用的是 13px，Inno 的 Font.Size 单位是 pt，100% DPI 下
  //    10pt ≈ 13.3px，取整用 10。字体显式指定微软雅黑，与素材的 msyh.ttc 一致，
  //    否则 Inno 会拿默认字体渲染，同一张窗体上两种字形会露馅。
  UN_TXT_FONT = 'Microsoft YaHei UI';
  UN_TXT_SIZE = 10;        // pt
  UN_VOL_RIGHT = 20;       // 体积文字距卡片右边缘（右对齐基准）
  UN_SUB_X = 40;           // 「N 张 PNG」距卡片左边缘
  UN_SUB_DY = 27;          // 同上，距卡片顶边
  UN_WARN_TX = 36;         // 警示条文字距警示条左边缘
  UN_TXT_H = 17;           // 动态文字行高（仅用于垂直居中兜底，实际以控件 AutoSize 为准）

// ==========================================================================
//  卸载：真实磁盘占用探测
//  ⚠️ 这三个函数必须定义在 InitUninstallOptions **之前** —— Pascal Script 是
//     「先定义后使用」，放到后面会报 Unknown identifier。
//  ⚠️ 只用 FileSize() 取单个文件大小，不碰 TFindRec.SizeHigh/SizeLow：
//     那两个字段的类型在 Inno 各版本间改过，靠 FileSize 最稳。
// ==========================================================================
//: 目录（或单个文件）的递归磁盘占用。
//  ⚠️⚠️ 这里是 Inno 的 **Pascal Script**，它的 FileSize 与 ISPP（预处理器）同名不同参：
//      Pascal Script: function FileSize(const Name: String; var Size: Integer): Boolean;
//      ISPP:          int FileSize(str FileName);
//     按 ISPP 那种单参数写法调用，编译期直接报 "Invalid number of parameters"（踩过）。
//     取 64 位大小要用 FileSize64，同样是「文件名 + var 输出」并返回是否成功。
function PathSize(const Path: String): Int64;
var
  FindRec: TFindRec;
  Sub: String;
  Sz: Int64;
begin
  Result := 0;
  if not DirExists(Path) then
  begin
    if FileSize64(Path, Sz) then   // 候选里既有目录也有单个文件
      Result := Sz;
    Exit;
  end;
  if FindFirst(AddBackslash(Path) + '*', FindRec) then
  try
    repeat
      if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
      begin
        Sub := AddBackslash(Path) + FindRec.Name;
        if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
          Result := Result + PathSize(Sub)
        else if FileSize64(Sub, Sz) then
          Result := Result + Sz;
      end;
    until not FindNext(FindRec);
  finally
    FindClose(FindRec);
  end;
end;

//: 数某个目录下指定扩展名的文件个数（历史截图 = *.png）。
function CountFilesExt(const Path, Ext: String): Integer;
var
  FindRec: TFindRec;
begin
  Result := 0;
  if not DirExists(Path) then Exit;
  if FindFirst(AddBackslash(Path) + '*', FindRec) then
  try
    repeat
      if ((FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) = 0)
         and (CompareText(ExtractFileExt(FindRec.Name), Ext) = 0) then
        Result := Result + 1;
    until not FindNext(FindRec);
  finally
    FindClose(FindRec);
  end;
end;

//: 字节数转「165.8 MB」这种给人看的字符串。0 字节显示「—」。
//  ⚠️ 不用 Format 的浮点格式：Inno 的 Format 对精度修饰符支持不稳，
//     整数除 + 取余自己拼小数点，结果完全可控。
function FormatSize(Bytes: Int64): String;
var
  Whole, Frac: Int64;
begin
  if Bytes <= 0 then
  begin
    Result := '—';
    Exit;
  end;
  if Bytes >= 1048576 then
  begin
    Whole := Bytes div 1048576;
    Frac := (Bytes mod 1048576) * 10 div 1048576;
    Result := IntToStr(Whole) + '.' + IntToStr(Frac) + ' MB';
  end
  else if Bytes >= 1024 then
  begin
    Whole := Bytes div 1024;
    Frac := (Bytes mod 1024) * 10 div 1024;
    Result := IntToStr(Whole) + '.' + IntToStr(Frac) + ' KB';
  end
  else
    Result := IntToStr(Bytes) + ' B';
end;

procedure InitUninstallOptions;
var
  I: Integer;
begin
  SetArrayLength(PurgeChoices, OPT_COUNT);
  SetArrayLength(PurgePaths, OPT_COUNT);
  SetArrayLength(PurgeSizes, OPT_COUNT);
  // ⚠️ 2026-10-10 主人改定：**默认全部不勾选** —— 卸载只移除程序本体，
  //    用户数据（配置 / 截图历史 / 离线模型 / 日志）一律默认保留，
  //    要删哪几项由用户自己勾。原为「默认全部勾选删除」。
  //    依据：.workbuddy/风险扫描-SnapLingo-20261009.md 附录 §2.3 的选项 C
  //    （该报告指出 history 是用户生成的截图历史，默认删除风险偏高）。
  //    ⚠️ 同步点：素材里的头部说明与「离线翻译模型」卡片副文字已跟着反转，
  //       见 packaging/make_uninstall_assets.py 的 desc 与 ITEMS —— 别只改一边。
  for I := 0 to OPT_COUNT - 1 do
    PurgeChoices[I] := False;

  PurgePaths[0] := ExpandConstant('{localappdata}\ScreenshotTranslator\config.json');
  PurgePaths[1] := ExpandConstant('{localappdata}\ScreenshotTranslator\history');
  PurgePaths[2] := ExpandConstant('{localappdata}\ScreenshotTranslator\models');
  PurgePaths[3] := ExpandConstant('{localappdata}\ScreenshotTranslator\app.log');

  // ⚠️ 体积必须**在这里**量：此刻文件都还在（真正删除发生在 usPostUninstall），
  //    等删完再量只会得到一串 0。
  for I := 0 to OPT_COUNT - 1 do
    PurgeSizes[I] := PathSize(PurgePaths[I]);
end;

procedure UninstallOkClick(Sender: TObject);
begin
  UninstallConfirmed := True;
  if UninstallDlg <> nil then
    UninstallDlg.Close;
end;

procedure UninstallCancelClick(Sender: TObject);
begin
  UninstallConfirmed := False;
  if UninstallDlg <> nil then
    UninstallDlg.Close;
end;

// ---- 卸载询问窗体：勾选变化后刷新警示条文字 ----
// 旧版是「换图」（预出 un-warn-N-m/o.bmp 共 13 张）；体积改成真实值后组合会爆炸，
// 现在底图固定一张（un-warn-bg.bmp），只改文字。
// ⚠️ 必须定义在 UninstallCheckClick **之前** —— 那个回调要调它。
procedure RefreshUninstallTexts;
var
  I, N: Integer;
  Total: Int64;
begin
  if UninstallWarnText = nil then Exit;
  N := 0;
  Total := 0;
  for I := 0 to OPT_COUNT - 1 do
    if UninstallCheckOn[I] then
    begin
      N := N + 1;
      Total := Total + PurgeSizes[I];
    end;

  if N = 0 then
    UninstallWarnText.Caption := '不会删除任何数据，仅移除程序本体。'
  else
    UninstallWarnText.Caption := Format(
      '将随卸载删除 %d 项数据（约 %s），删除后不可恢复。', [N, FormatSize(Total)]);

  // 文字长度变了不影响左起点，但行高可能变 —— 重新垂直居中
  UninstallWarnText.Top := ScaleY(UN_WARN_Y) +
    (ScaleY(UN_WARN_H) - UninstallWarnText.Height) div 2;
end;

// ---- 卸载询问窗体：点勾选框 ----
procedure UninstallCheckClick(Sender: TObject);
var
  I: Integer;
begin
  // ⚠️ 不用 TBitmapImage(Sender) 强转：Pascal Script 的类型转换带运行时检查，
  //    万一 Sender 的实际类型不符就当场抛 "Cannot cast an object."（踩过）。
  //    改成遍历全局数组比对引用，零风险。
  // ⚠️ 要比对**两个**数组：真正收到点击的是 TPanel 外壳（见 UninstallCheckShells
  //    的声明注释），TBitmapImage 只在某些环境下才可能自己收到，一起认最稳。
  for I := 0 to OPT_COUNT - 1 do
    if (UninstallChecks[I] = Sender) or (UninstallCheckShells[I] = Sender) then
    begin
      UninstallCheckOn[I] := not UninstallCheckOn[I];
      if UninstallCheckOn[I] then
        LoadBmp(UninstallChecks[I], 'un-check.bmp')
      else
        LoadBmp(UninstallChecks[I], 'un-check-off.bmp');
      RefreshUninstallTexts;
      Exit;
    end;
end;

// ---- 无边框窗体自己实现拖动：只在标题栏区域响应 ----
// ⚠️ 已放弃：Inno 的 TBitmapImage（TGraphicControl）**没有注册 OnMouseDown**
//    （编译报 Unknown identifier 'ONMOUSEDOWN'，只有 OnClick）。
//    换成 TPanel 当拖动热区也不行 —— TPanel 有窗口句柄，会盖住背景图那块。
//    这个窗体本来就不支持拖动（旧版也没有），不引入回归，维持原样。

function UninstallAskForm: Boolean;
var
  Form: TSetupForm;
  Bg, BtnCancel, BtnOk, BtnClose: TBitmapImage;
  BtnShell: TPanel;      // ✕ / 两个按钮共用的外壳（有窗口句柄，收点击的那层）
  I: Integer;
begin
  Result := False;

  // ⚠️ 尺寸陷阱：实测 CreateCustomForm 内部用的 DPI 倍率与 ScaleX **不一致**，
  //    直接传 ScaleX(UN_W) 会得到比屏幕还大的窗体。
  //    解法：先建个小窗体，再用 ScaleX 手动设尺寸 —— 这样窗体尺寸与下面控件坐标同一基准。
  Form := CreateCustomForm(100, 100, False, False);
  UninstallDlg := Form;
  SetArrayLength(UninstallChecks, OPT_COUNT);
  SetArrayLength(UninstallCheckOn, OPT_COUNT);
  SetArrayLength(UninstallCheckShells, OPT_COUNT);
  try
    Form.ClientWidth := ScaleX(UN_W);
    Form.ClientHeight := ScaleY(UN_H);
    Form.Caption := '{#AppName} 卸载';
    Form.BorderStyle := bsNone;
    ApplyRoundedCorners(Form);

    // 1) 背景大图 —— 标题栏 / 图标 / 标题 / 说明 / 4 张卡片框 / 主文字 /
    //    橙胶囊 / 分隔线 / 底部小字（**纯静态**部分整块交给 Pillow 渲染，
    //    省掉一大堆定位代码；体积、数量这些运行时才知道的字留白不画）。
    Bg := TBitmapImage.Create(Form);
    Bg.Parent := Form;
    Bg.Stretch := True;
    // ⚠️⚠️ 这里**必须**用 ScaleX/ScaleY，不能用 Form.ClientWidth/ClientHeight：
    //    设过 Form.ClientWidth 之后立刻读它，拿到的还是**旧值**（Inno 延迟应用），
    //    于是背景图按错误的尺寸拉伸，与下面用 ScaleX/ScaleY 定位的勾选框、
    //    警示条、按钮全都对不上 —— 实测表现是「卡片间距忽大忽小、警示条压到卡片上」。
    Bg.SetBounds(0, 0, ScaleX(UN_W), ScaleY(UN_H));
    LoadBmp(Bg, 'un-bg.bmp');

    // 2) 4 个勾选框：叠在背景图留白的位置上
    //    ⚠️ 每格先建一个 TPanel 外壳（TWinControl，有窗口句柄，**它才收点击**），
    //       图片贴在壳里只管显示。原因见 UninstallCheckShells 的声明注释。
    for I := 0 to OPT_COUNT - 1 do
    begin
      UninstallCheckShells[I] := TPanel.Create(Form);
      UninstallCheckShells[I].Parent := Form;
      UninstallCheckShells[I].BevelOuter := bvNone;
      UninstallCheckShells[I].Color := clWhite;   // 卡片是白底，无缝
      UninstallCheckShells[I].Cursor := crHandPoint;
      UninstallCheckShells[I].OnClick := @UninstallCheckClick;
      UninstallCheckShells[I].SetBounds(
        ScaleX(UN_CARD_X + UN_CHK_IN_X - UN_CHK_PAD),
        ScaleY(UN_CARD_Y0 + I * UN_CARD_STEP + UN_CHK_IN_Y - UN_CHK_PAD),
        ScaleX(UN_CHK_S + UN_CHK_PAD * 2), ScaleY(UN_CHK_S + UN_CHK_PAD * 2));

      UninstallChecks[I] := TBitmapImage.Create(UninstallCheckShells[I]);
      UninstallChecks[I].Parent := UninstallCheckShells[I];
      UninstallChecks[I].Stretch := True;
      UninstallChecks[I].Cursor := crHandPoint;
      UninstallChecks[I].OnClick := @UninstallCheckClick;
      UninstallChecks[I].SetBounds(0, 0,
        ScaleX(UN_CHK_S + UN_CHK_PAD * 2), ScaleY(UN_CHK_S + UN_CHK_PAD * 2));
      UninstallCheckOn[I] := PurgeChoices[I];
      if UninstallCheckOn[I] then
        LoadBmp(UninstallChecks[I], 'un-check.bmp')
      else
        LoadBmp(UninstallChecks[I], 'un-check-off.bmp');
    end;

    // 3) 警示条底图（只有粉底 + 红三角）。文字**不在这里** —— 见末尾的
    //    「6) 动态文字」，那里必须最后创建才盖得住这张图。
    UninstallWarnImg := TBitmapImage.Create(Form);
    UninstallWarnImg.Parent := Form;
    UninstallWarnImg.Stretch := True;
    UninstallWarnImg.SetBounds(ScaleX(UN_WARN_X), ScaleY(UN_WARN_Y),
      ScaleX(UN_WARN_W), ScaleY(UN_WARN_H));
    LoadBmp(UninstallWarnImg, 'un-warn-bg.bmp');

    // 4) 标题栏 ✕：等同「取消」（关窗即中止卸载）
    //    ⚠️ 同样必须套 TPanel 外壳才收得到点击，见 UninstallCheckShells 注释。
    BtnShell := TPanel.Create(Form);
    BtnShell.Parent := Form;
    BtnShell.BevelOuter := bvNone;
    BtnShell.Color := clWhite;      // 标题栏是白底，无缝
    BtnShell.Cursor := crHandPoint;
    BtnShell.OnClick := @UninstallCancelClick;
    BtnShell.SetBounds(ScaleX(UN_CLOSE_X), ScaleY(UN_CLOSE_Y),
      ScaleX(UN_CLOSE_S), ScaleY(UN_CLOSE_S));

    BtnClose := TBitmapImage.Create(BtnShell);
    BtnClose.Parent := BtnShell;
    BtnClose.Stretch := True;
    BtnClose.OnClick := @UninstallCancelClick;
    BtnClose.SetBounds(0, 0, ScaleX(UN_CLOSE_S), ScaleY(UN_CLOSE_S));
    LoadBmp(BtnClose, 'un-close.bmp');

    // 5) 底部两个按钮（同样各自套 TPanel 外壳）
    BtnShell := TPanel.Create(Form);
    BtnShell.Parent := Form;
    BtnShell.BevelOuter := bvNone;
    BtnShell.Color := clWhite;
    BtnShell.Cursor := crHandPoint;
    BtnShell.OnClick := @UninstallCancelClick;
    BtnShell.SetBounds(ScaleX(UN_CANCEL_X), ScaleY(UN_BTN_Y),
      ScaleX(UN_CANCEL_W), ScaleY(UN_BTN_H));

    BtnCancel := TBitmapImage.Create(BtnShell);
    BtnCancel.Parent := BtnShell;
    BtnCancel.Stretch := True;
    BtnCancel.OnClick := @UninstallCancelClick;
    BtnCancel.SetBounds(0, 0, ScaleX(UN_CANCEL_W), ScaleY(UN_BTN_H));
    LoadBmp(BtnCancel, 'un-btn-cancel.bmp');

    BtnShell := TPanel.Create(Form);
    BtnShell.Parent := Form;
    BtnShell.BevelOuter := bvNone;
    BtnShell.Color := clWhite;
    BtnShell.Cursor := crHandPoint;
    BtnShell.OnClick := @UninstallOkClick;
    BtnShell.SetBounds(ScaleX(UN_OK_X), ScaleY(UN_BTN_Y),
      ScaleX(UN_OK_W), ScaleY(UN_BTN_H));

    BtnOk := TBitmapImage.Create(BtnShell);
    BtnOk.Parent := BtnShell;
    BtnOk.Stretch := True;
    BtnOk.OnClick := @UninstallOkClick;
    BtnOk.SetBounds(0, 0, ScaleX(UN_OK_W), ScaleY(UN_BTN_H));
    LoadBmp(BtnOk, 'un-btn-ok.bmp');

    // 6) 运行时才画得出来的动态文字：4 项体积 + 「N 张 PNG」+ 警示条正文。
    //    ⚠️⚠️ 必须建在**所有 TBitmapImage 之后**。TGraphicControl 的 Z 顺序就是
    //       创建顺序，而上面那张警示条底图是后建的 —— 文字若建在它前面，
    //       会被它整个盖住，屏幕上就是「警示条里一个字都没有」。
    //    ⚠️ 必须用 TNewStaticText（透明、无窗口句柄）而不是 TPanel：
    //       TPanel 是 TWinControl，会连底下的背景图一起挡住。
    SetArrayLength(UninstallVolLabels, OPT_COUNT);
    for I := 0 to OPT_COUNT - 1 do
    begin
      UninstallVolLabels[I] := TNewStaticText.Create(Form);
      UninstallVolLabels[I].Parent := Form;
      UninstallVolLabels[I].Font.Name := UN_TXT_FONT;
      UninstallVolLabels[I].Font.Size := UN_TXT_SIZE;
      UninstallVolLabels[I].Font.Color := $00999999;   // #999999（素材 FAINT 同色）
      UninstallVolLabels[I].AutoSize := True;
      // ⚠️ 顺序要紧：先给 Caption（AutoSize 立刻重算 Width），再用 Width 反推
      //    左边界做右对齐，最后设 Top（垂直居中也要用到 Height）。
      UninstallVolLabels[I].Caption := FormatSize(PurgeSizes[I]);
      UninstallVolLabels[I].Left :=
        ScaleX(UN_CARD_X + UN_CARD_W - UN_VOL_RIGHT) - UninstallVolLabels[I].Width;
      UninstallVolLabels[I].Top := ScaleY(UN_CARD_Y0 + I * UN_CARD_STEP) +
        (ScaleY(UN_CARD_H) - UninstallVolLabels[I].Height) div 2;
    end;

    // 「历史截图」那一行的数量（素材里整行留白，因为张数会变）
    UninstallSubLabel := TNewStaticText.Create(Form);
    UninstallSubLabel.Parent := Form;
    UninstallSubLabel.Font.Name := UN_TXT_FONT;
    UninstallSubLabel.Font.Size := UN_TXT_SIZE;
    UninstallSubLabel.Font.Color := $00666666;         // #666666（素材 GRAY 同色）
    UninstallSubLabel.AutoSize := True;
    UninstallSubLabel.Caption :=
      IntToStr(CountFilesExt(PurgePaths[1], '.png')) + ' 张 PNG';
    UninstallSubLabel.Left := ScaleX(UN_CARD_X + UN_SUB_X);
    UninstallSubLabel.Top := ScaleY(UN_CARD_Y0 + 1 * UN_CARD_STEP + UN_SUB_DY);

    // 警示条正文（底图里只有粉底和红三角）
    UninstallWarnText := TNewStaticText.Create(Form);
    UninstallWarnText.Parent := Form;
    UninstallWarnText.Font.Name := UN_TXT_FONT;
    UninstallWarnText.Font.Size := UN_TXT_SIZE;
    UninstallWarnText.Font.Color := $002D2DA3;         // #A32D2D（TColor 是 BGR）
    UninstallWarnText.AutoSize := True;
    UninstallWarnText.Left := ScaleX(UN_WARN_X + UN_WARN_TX);
    RefreshUninstallTexts;   // 首次填文案 + 垂直居中

    // 模态显示。点「取消」/「✕」/直接关窗 = 中止整个卸载
    UninstallConfirmed := False;
    Form.ShowModal;
    if UninstallConfirmed then
    begin
      for I := 0 to OPT_COUNT - 1 do
        PurgeChoices[I] := UninstallCheckOn[I];
      Result := True;
    end;
  finally
    UninstallDlg := nil;                       // 先清引用，避免 Free 后悬空
    UninstallWarnImg := nil;
    UninstallSubLabel := nil;
    UninstallWarnText := nil;
    SetArrayLength(UninstallChecks, 0);        // 控件已随窗体销毁，别留悬空引用
    SetArrayLength(UninstallCheckShells, 0);
    SetArrayLength(UninstallVolLabels, 0);
    Form.Free;
  end;
end;

function InitializeUninstall: Boolean;
begin
  IsUninstaller := True;   // 自绘素材改从 {app}\ui\ 读，见 LoadBmp
  InitUninstallOptions;

  // ⚠️ 静默卸载（/SILENT、/VERYSILENT）必须跳过候选框，两个原因：
  //    1) 覆盖安装时 Inno 会先自动静默卸载旧版，此刻弹模态框会把整个安装卡死；
  //    2) 静默场景（无人值守 / 企业部署）本就该保守 —— 保留用户数据，只删程序目录。
  // ⚠️ 2026-10-10 起 `InitUninstallOptions` 的默认值已经是全 False，
  //    这里仍然**显式**再置一遍：一是把「静默 = 一定不删用户数据」这个意图写死，
  //    二是将来若有人改默认值，静默分支不会跟着一起变。
  if UninstallSilent then
  begin
    PurgeChoices[0] := False;
    PurgeChoices[1] := False;
    PurgeChoices[2] := False;
    PurgeChoices[3] := False;
    Result := True;
    Exit;
  end;

  Result := UninstallAskForm;   // 返回 False 会中止卸载
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  I: Integer;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    // ⚠️ 此刻 UninstallProgressForm 已不可用，绝不能碰它
    for I := 0 to OPT_COUNT - 1 do
      if PurgeChoices[I] and (PurgePaths[I] <> '') then
      begin
        if DirExists(PurgePaths[I]) then
          DelTree(PurgePaths[I], True, True, True)
        else if FileExists(PurgePaths[I]) then
          DeleteFile(PurgePaths[I]);
      end;
  end;
end;
