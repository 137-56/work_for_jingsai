# scripts/make_submission_package_web.py
"""打包 Web 演示版（work_two）的提交材料 —— 与主版本同样的四分类。

★ 这是同一个作品的**第二个实现**：纯前端 + Serverless Functions，
  AI 能力（千问 / 万相 / Tripo）全部走云端 API，**不含本地模型**。
  因此「模型数据」这一类的内容与主版本不同 —— 放的是纹样数据与配图，
  而不是模型权重。这一点在包内 README 里写清楚了。

★ 复用 make_submission_package.py 的工具函数，避免两套实现发散。

用法：
    .venv/Scripts/python.exe scripts/make_submission_package_web.py
"""
import shutil
import sys
from pathlib import Path

# 复用主打包脚本的工具（import 不会触发它的 main()）
sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_submission_package import human, copy_tree, fresh, _bytes_of  # noqa

# ---------------------------------------------------------------- 可改参数
TEAM_ID = "AIC-2026-49790132"
TOPIC = "算法模型创新"
TITLE = "纹初迹现"
VARIANT = "Web演示版"
ROOT_NAME = f"{TEAM_ID}-{TOPIC}-{TITLE}-{VARIANT}"

DESK = Path(r"D:/work/work_space/DeskTop/DeskBox")
COMP = DESK / "竞赛"
SRC = COMP / "work_two" / "----"          # Web 版工程根目录
SHOTS = COMP / "work" / "docs" / "web_screenshots"   # 事先截好的界面图（已入库）

PKG = DESK / ROOT_NAME
D_EXE = PKG / f"{ROOT_NAME}-可执行程序"
D_DAT = PKG / f"{ROOT_NAME}-模型数据"
D_SRC = PKG / f"{ROOT_NAME}-源代码"
D_DRW = PKG / f"{ROOT_NAME}-高清图纸"


# ================================================================ 1 源代码
def build_source():
    print("\n[1/4] 源代码…")
    fresh(D_SRC)
    items = ["index.html", "config.js", "netlify.toml", "package.json",
             "README.md", ".gitattributes"]
    n = b = 0
    for it in items:
        s = SRC / it
        if s.exists():
            shutil.copy2(s, D_SRC / it)
            n += 1
            b += s.stat().st_size
    # serverless 函数
    n2, b2 = copy_tree(SRC / "netlify", D_SRC / "netlify")
    # 3D 查看器依赖（前端固定依赖，必须随源码走）
    n3, b3 = copy_tree(SRC / "libs", D_SRC / "libs")
    n += n2 + n3
    b += b2 + b3
    print(f"      ✓ 页面/配置 {len(items)} 项 + 云函数 {n2} 个 + 依赖库 {n3} 个")
    print(f"      合计 {n} 个文件 ｜ {human(b)}")
    return n, b


# ================================================================ 2 模型数据
MODEL_README = """# 模型数据 · 说明（Web 演示版）

## ★ 本版本不含本地模型

本版本是**纯前端 + 云端大模型 API** 的实现，**不在本地存放任何模型权重**。
全部 AI 能力由阿里云百炼（DashScope）在云端提供：

| 能力 | 云端模型 | 调用位置 |
|---|---|---|
| AI 提示词精化 / 智能问答 | `qwen-plus` | `netlify/functions/proxy.mjs` |
| 2D 写实文物图 | `wan2.2-t2i-flash` | `netlify/functions/proxy.mjs` |
| 3D 写实模型（图转 3D） | `Tripo/Tripo-H3.1` | `netlify/functions/submit3d.mjs`、`check3d.mjs` |

因此本目录存放的是**运行所需的业务数据**，而非模型权重。

## 目录内容

```
data/patterns.json        纹样数据：500 条纹样（含名称/类别/年代/载体/寓意/
                          构成元素/出处/授权/色彩/几何等字段）
images/patterns/          纹样配图：500 张（w001.jpg ~ w500.jpg）
```

其中「文化配方」与「元素溯源卡片」两步**完全在浏览器本地完成** ——
直接读取 `data/patterns.json` 做语义匹配，不经过任何网络请求。
只有「AI 提示词精化」「2D 写实图」「3D 模型」「智能问答」四步需要云端 API。

## 数据来源与授权

纹样数据与配图：**Wényàng 中华传统纹样图鉴（wenyang.net）· 原创再设计**。
依据 `patterns.json` 中 `license` 字段的声明：
「改编自 Wényàng 中华传统纹样图鉴（wenyang.net），原创再设计，
不直接复制具体文物图案。」

> ⚠️ 注意：本版本的数据来源与主版本（Streamlit 版）**不同**，
> 两个版本的数据口径不可混用。主版本使用 BLCaptain《中国传统纹样图鉴 Wényàng》
> （CC BY-NC 4.0），且 `dynasty` 字段全库为「不详」；本版本数据含年代字段。

## 关于 API Key

云端接口需要 `DASHSCOPE_API_KEY`。**出于安全考虑，本材料不含任何真实密钥**。
部署时需在 Netlify 后台配置环境变量（见「可执行程序」中的部署说明）。
未配置时，界面的本地两步（文化配方 / 元素溯源卡片）仍可正常演示。
"""


def build_model_data():
    print("\n[2/4] 模型数据…")
    fresh(D_DAT)

    d = D_DAT / "data"
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC / "data" / "patterns.json", d / "patterns.json")
    print(f"      ✓ data/patterns.json（500 条纹样数据）")

    n2, b2 = copy_tree(SRC / "images", D_DAT / "images")
    print(f"      ✓ images/patterns/（{n2} 张配图，{human(b2)}）")

    (D_DAT / "README_模型数据.md").write_text(MODEL_README, encoding="utf-8")
    print("      ✓ README_模型数据.md")

    n = sum(1 for f in D_DAT.rglob("*") if f.is_file())
    b = _bytes_of(D_DAT)
    print(f"      合计 {n} 个文件 ｜ {human(b)}")
    return n, b


# ================================================================ 3 高清图纸
def build_drawings():
    print("\n[3/4] 高清图纸…")
    fresh(D_DRW)
    d = D_DRW / "界面截图"
    d.mkdir(parents=True, exist_ok=True)
    pairs = [("01_界面_输入文化需求.png", "01_界面_输入文化需求.png"),
             ("02_界面_文化配方与元素溯源卡片.png",
              "02_界面_文化配方与元素溯源卡片.png")]
    n = 0
    for s, t in pairs:
        if (SHOTS / s).exists():
            shutil.copy2(SHOTS / s, d / t)
            n += 1
            print(f"      ✓ {t}")
    if n == 0:
        print("      ! 未找到界面截图（先跑 scripts/_shot_web2.py）")

    (D_DRW / "README_图纸说明.md").write_text(DRAW_README, encoding="utf-8")
    n += 1
    b = _bytes_of(D_DRW)
    print(f"      合计 {n} 个文件 ｜ {human(b)}")
    return n, b


DRAW_README = """# 高清图纸 · 说明（Web 演示版）

## 本版本图纸为何较少

与主版本（Streamlit 版）不同，本版本是**单页 Web 应用**，
其完整流程涉及云端 API 调用（2D 写实图 / 3D 模型），
**无法在离线截图环境中完整走通**。

因此本目录收录的是**离线可完整复现的部分**：

| 图 | 内容 |
|---|---|
| `01_界面_输入文化需求.png` | 工作台首屏与需求输入 |
| `02_界面_文化配方与元素溯源卡片.png` | 需求输入后，系统本地生成的 ② 文化配方与 ④ 元素溯源卡片 |

这两步**完全由浏览器本地完成**（读取 `data/patterns.json` 做语义匹配），
不含任何网络请求，因此截图结果与线上部署后一致。

## 完整效果的查看方式

2D 写实文物图与 3D 写实模型需要云端 API，请按「可执行程序」中的说明部署后查看。
"""


# ================================================================ 4 可执行程序
BAT = r"""@echo off
title 纹初迹现 · Web 演示版 本地预览
echo ============================================================
echo    纹初迹现 . Web 演示版 本地预览
echo ============================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python。本预览脚本用 Python 起一个本地静态服务。
    echo        请安装 Python 3.10 或以上版本：https://www.python.org/downloads/
    echo.
    echo        也可以改用 Node.js：npx serve .
    echo.
    pause
    exit /b 1
)

echo [1/2] 正在启动本地静态服务...
echo [2/2] 浏览器将打开 http://localhost:8080/index.html
echo.
echo    停止服务：在本窗口按 Ctrl+C
echo.
start "" http://localhost:8080/index.html
python -m http.server 8080
pause
"""

SH = r"""#!/usr/bin/env bash
# 纹初迹现 · Web 演示版 本地预览
set -e
cd "$(dirname "$0")"

PORT=8080
echo "============================================================"
echo "   纹初迹现 · Web 演示版 本地预览"
echo "============================================================"

if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "[错误] 未检测到 Python。可改用 Node.js：npx serve ."
    exit 1
fi

echo "预览地址：http://localhost:${PORT}/index.html"
echo "停止服务：Ctrl+C"
echo
$PY -m http.server "$PORT"
"""

README_EXE = """# 可执行程序 · 运行说明（Web 演示版）

**纹初迹现 · AI 纹样创作与 3D 生成平台（Web 演示版）**

---

## 一、这份材料包含什么

| 文件 | 说明 |
|---|---|
| `启动预览.bat` | Windows：启动本地预览服务（自动打开浏览器） |
| `启动预览.sh` | Linux / macOS：同上 |
| `部署到Netlify.md` | 线上部署完整步骤（含环境变量配置） |
| `README_运行说明.md` | 本文件 |

## 二、这个版本是什么

本版本是**纯前端 + 云端大模型 API** 的 Web 实现，
提供 7 步创作工作台：

```
① 输入文化需求 → ② 文化配方 → ③ AI 提示词精化 → ④ 元素溯源卡片
→ ⑤ AI 写实文物图（可跳过）→ ⑥ AI 3D 写实模型（可跳过）→ ⑦ 智能问答
```

其中 **①→② 与 ④ 完全在浏览器本地完成**（读取内置的 500 条纹样数据做语义匹配），
其余步骤调用云端大模型 API。

| 能力 | 云端模型 |
|---|---|
| AI 提示词精化 / 智能问答 | 通义千问 `qwen-plus` |
| 2D 写实文物图 | 通义万相 `wan2.2-t2i-flash` |
| 3D 写实模型（图转 3D） | `Tripo/Tripo-H3.1` |

## 三、本地预览（离线可看）

**第一步**：把 `可执行程序`、`源代码`、`模型数据` 三份材料**合并到同一个目录**：

```
任意目录/
├── 启动预览.bat          ← 来自「可执行程序」
├── 启动预览.sh           ← 来自「可执行程序」
├── 部署到Netlify.md      ← 来自「可执行程序」
├── index.html            ← 来自「源代码」
├── config.js             ← 来自「源代码」
├── netlify.toml          ← 来自「源代码」
├── package.json          ← 来自「源代码」
├── netlify/              ← 来自「源代码」（5 个 Serverless 函数）
├── libs/                 ← 来自「源代码」（3D 查看器依赖）
├── data/                 ← 来自「模型数据」（500 条纹样数据）
└── images/               ← 来自「模型数据」（500 张配图）
```

**第二步**：双击 `启动预览.bat`（或 `./启动预览.sh`），浏览器会自动打开。

> ★ **必须通过本地服务器访问，不能直接双击 `index.html`。**
> 因为页面用 `fetch()` 读取 `data/patterns.json`，
> 浏览器对 `file://` 协议有跨域限制，直接打开会读不到数据。

本地预览可完整体验 **① 输入需求 → ② 文化配方 → ④ 元素溯源卡片**；
其余步骤需要云端 API，本地没有 Serverless 运行环境，会提示不可用。

## 四、线上部署（完整效果）

完整效果需部署到 Netlify（免费额度足够），步骤详见 `部署到Netlify.md`。
简要说明：

1. 把合并后的目录推到 GitHub 仓库
2. Netlify → Add new site → Import from Git，Publish directory 填 `.`
3. 在 Site settings → Environment variables 添加 `DASHSCOPE_API_KEY`
4. 触发一次重新部署，让环境变量生效

> ⚠️ 出于安全考虑，本材料**不含任何真实 API Key**，需自行配置。

## 五、常见问题

**Q：打开页面后点「生成配方」没反应 / 提示读取失败？**
直接双击 `index.html` 了。请用 `启动预览.bat` 通过本地服务器访问。

**Q：提示「AI 解析不可用」？**
本地没有 Serverless 运行环境，属正常现象。本地一步（文化配方、元素溯源卡片）
不受影响；需要 AI 步骤请按上述方式部署。

**Q：页面样式正常但 3D 区域空白？**
3D 模型需通过云端生成，本地无法完成。

**Q：为什么本版本没有"模型数据"里的模型权重？**
本版本不依赖本地模型，AI 能力全部由云端 API 提供。
「模型数据」材料里放的是运行所需的纹样数据与配图。
"""


def build_exe():
    print("\n[4/4] 可执行程序…")
    fresh(D_EXE)
    (D_EXE / "启动预览.bat").write_text(BAT, encoding="gbk", newline="\r\n")
    (D_EXE / "启动预览.sh").write_text(SH, encoding="utf-8", newline="\n")
    (D_EXE / "部署到Netlify.md").write_text(DEPLOY_DOC, encoding="utf-8")
    (D_EXE / "README_运行说明.md").write_text(README_EXE, encoding="utf-8")
    n = sum(1 for f in D_EXE.rglob("*") if f.is_file())
    b = _bytes_of(D_EXE)
    print(f"      {n} 个文件 ｜ {human(b)}")
    for f in sorted(D_EXE.iterdir()):
        print(f"        - {f.name}")
    return n, b


DEPLOY_DOC = """# 部署到 Netlify（完整效果）

本版本**本身就是可部署的站点根目录，无需构建**。

---

## 1. 推送到 GitHub

用 GitHub Desktop 新建仓库（或使用已有仓库），把**合并后的目录内容**放进去：

需要包含：`netlify/`、`netlify.toml`、`index.html`、`config.js`、
`config.js`、`package.json`、`libs/`、`data/`、`images/`

> ⚠️ 不要把外层文件夹也包进去 —— 仓库根目录应当**直接**是 `index.html` 所在目录。

Commit & Push。

## 2. 接入 Netlify

1. 登录 [app.netlify.com](https://app.netlify.com)
2. **Add new site → Import from Git** → 选择上面的 GitHub 仓库
3. 配置：
   - **Build command**：留空（`netlify.toml` 里已写静态站点，无需构建）
   - **Publish directory**：填 `.`
4. 点击部署，等待完成

## 3. 配置 API 密钥（关键）

没有密钥时，AI 相关接口会返回「缺少 DASHSCOPE_API_KEY」。

1. 站点 → **Site settings → Environment variables → Add a variable**
2. 变量名：`DASHSCOPE_API_KEY`
   - 值：阿里云百炼的 API Key（千问 / 万相 / 3D 共用这一个）
3. 保存后 **Deploys → Trigger deploy**，手动触发一次重新部署，让变量生效

> 阿里云百炼需开通「3D 生成（Tripo）」产品，否则 3D 步骤会提示「产品未开通」。

## 4. 技术说明（供答辩参考）

- **前端不暴露任何密钥**，所有调用经 `/.netlify/functions/*` 代理转发
- **千问**：`netlify/functions/proxy.mjs` 转发到
  `dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`
- **万相**：同一函数转发异步接口（提交 + 轮询），模型 `wan2.2-t2i-flash`
- **3D**：`submit3d.mjs` 提交、`check3d.mjs` 轮询，
  模型 `Tripo/Tripo-H3.1`
- **模型库复用**：生成的 GLB 存入 Netlify Blobs（分区 `tripo3d`），
  相同词条再次生成直接复用，不重复消耗 API 额度
"""


# ================================================================ main
ROOT_README = """# {root}

> **作品名称**：纹初迹现 · 传统纹样可溯源生成系统（{variant}）
> **赛题**：{topic}　｜　**提交内容**：可执行程序 / 模型数据 / 源代码 / 高清图纸

---

## 一、四份材料

| 文件夹 | 内容 | 体量 |
|---|---|---|
| `{root}-可执行程序/` | 本地预览启动脚本、线上部署说明、运行说明 | {sz_exe} |
| `{root}-模型数据/` | 纹样数据（500 条）与配图（500 张）。★ 本版本不含本地模型权重 | {sz_dat} |
| `{root}-源代码/` | 页面、全局配置、5 个 Serverless 函数、3D 查看器依赖 | {sz_src} |
| `{root}-高清图纸/` | 界面截图（离线可完整复现的两步） | {sz_drw} |

---

## 二、这是什么

本版本是**纯前端 + 云端大模型 API** 的 Web 实现，提供 7 步创作工作台：

```
① 输入文化需求 → ② 文化配方 → ③ AI 提示词精化 → ④ 元素溯源卡片
→ ⑤ AI 写实文物图（可跳过）→ ⑥ AI 3D 写实模型（可跳过）→ ⑦ 智能问答
```

其中 **①→② 与 ④ 完全在浏览器本地完成**（读取内置的 500 条纹样数据做语义匹配，
不经过任何网络请求）；其余步骤调用云端大模型 API（通义千问 / 通义万相 / Tripo）。

> ★ **与主版本的关系**：本作品的另一实现为 Streamlit 桌面版
> （以本地视觉模型做元素检索与文化校验，强调**元素级可溯源**）。
> 本 Web 版本侧重**多端可用与云端 AI 能力整合**。
> 两版本的数据来源不同，口径不可混用。

---

## 三、如何运行

**本地预览（离线可看）**：把 `可执行程序`、`源代码`、`模型数据` 三份材料
合并到同一目录，双击 `启动预览.bat`（Windows）或运行 `./启动预览.sh`
（Linux / macOS），浏览器会自动打开。

> ⚠️ 必须通过本地服务器访问，**不能直接双击 `index.html`** ——
> 页面用 `fetch()` 读取数据，`file://` 协议有跨域限制。

**完整效果**：按 `{root}-可执行程序/部署到Netlify.md` 部署到 Netlify，
并在后台配置 `DASHSCOPE_API_KEY` 环境变量。

**环境要求**：只需 Python 3.10+（用于起本地静态服务）或 Node.js。
**无需显卡、无需安装任何依赖包。**

---

## 四、数据来源与授权

纹样数据与配图：**Wényàng 中华传统纹样图鉴（wenyang.net）· 原创再设计**。
依据数据文件 `license` 字段声明：「改编自 Wényàng 中华传统纹样图鉴（wenyang.net），
原创再设计，不直接复制具体文物图案。」

本作品为**学术竞赛用途，不涉及商业使用**。

---

## 五、合规声明

- 本材料中**不含**任何单位标识与人员身份信息。
- **不含任何真实 API 密钥**（密钥需在部署平台后台配置）。

---

*打包时间：{date}　｜　打包脚本：`scripts/make_submission_package_web.py`*
"""


def main():
    import datetime
    print("=" * 66)
    print(f"打包提交材料：{ROOT_NAME}")
    print(f"输出位置：{PKG}")
    print("=" * 66)
    PKG.mkdir(parents=True, exist_ok=True)

    r = {}
    r["源代码"] = build_source()
    r["模型数据"] = build_model_data()
    r["高清图纸"] = build_drawings()
    r["可执行程序"] = build_exe()

    txt = ROOT_README.format(
        root=ROOT_NAME, topic=TOPIC, variant=VARIANT,
        sz_exe=human(r["可执行程序"][1]), sz_dat=human(r["模型数据"][1]),
        sz_src=human(r["源代码"][1]), sz_drw=human(r["高清图纸"][1]),
        date=datetime.datetime.now().strftime("%Y-%m-%d"))
    (PKG / f"{ROOT_NAME}-材料清单.md").write_text(txt, encoding="utf-8")
    print(f"\n[+] 材料清单 → {ROOT_NAME}-材料清单.md")

    print("\n" + "=" * 66)
    tn = tb = 0
    for k, (n, b) in r.items():
        print(f"  {k:8s} {n:5d} 个文件 ｜ {human(b)}")
        tn += n
        tb += b
    print(f"  {'合计':8s} {tn:5d} 个文件 ｜ {human(tb)}")
    print(f"\n根目录：{PKG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
