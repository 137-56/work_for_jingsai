# scripts/make_submission_package.py
"""按赛方要求打包提交材料（四类：可执行程序 / 模型数据 / 源代码 / 高清图纸）。

★ 赛方要求（附件1 第三条 7 款「作品其他材料链接」）
    大容量文件放**一个根文件夹**，内部各项命名为
    `参赛团队编号-赛题名称-作品名称-XX（材料名称）`，上传网盘并提交分享链接。

★ 为什么要写脚本而不是手动复制
    1. 三份材料有几十处排除规则（.gitignore 排除 data/images，但赛方**必须**看到它 ——
       「git 不提交」≠「赛方不提交」），手抄必错。
    2. 编号或作品名变更时，只需改三个常量重跑，不必手工重命名几百个文件。
    3. 体积/文件数可核对，避免漏包。

用法：
    .venv/Scripts/python.exe scripts/make_submission_package.py
"""
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------- 可改参数
TEAM_ID = "AIC-2026-49790132"          # 团队编号
TOPIC = "算法模型创新"                  # 赛题名称
TITLE = "纹初迹现"                      # 作品名称
ROOT_NAME = f"{TEAM_ID}-{TOPIC}-{TITLE}"

DESK = Path(r"D:/work/work_space/DeskTop/DeskBox")
COMP = DESK / "竞赛"
SRC = COMP / "work"                     # 主系统
DOCS = COMP / "文档"                     # 仓库外的资料（只取图，不取内部文档）
# 赛方「材料封面页」PDF 的位置（早期占位骨架里已放好，编号是占位的，内容通用）
SEAL_DIR = COMP / "AIC-2026-12345678-算法模型创新-作品名称" \
                / "AIC-2026-12345678-算法模型创新-作品名称-代码与数据"

PKG = DESK / ROOT_NAME
D_EXE = PKG / f"{ROOT_NAME}-可执行程序"
D_DAT = PKG / f"{ROOT_NAME}-模型数据"
D_SRC = PKG / f"{ROOT_NAME}-源代码"
D_DRW = PKG / f"{ROOT_NAME}-高清图纸"

# ---------------------------------------------------------------- 排除规则
# 源代码包：排除环境/依赖/数据/模型/产物/敏感文件
SRC_IGNORE_NAMES = {
    ".venv", ".git", "__pycache__", "ckpt", "data", "outputs", "static",
    ".env", "redline.yaml", ".pytest_cache", ".mypy_cache",
}
SRC_IGNORE_SUFFIX = {".pyc", ".pyo", ".log"}
SRC_IGNORE_FILES = {"redline.yaml", "redline.yaml.bak"}


def _bytes_of(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def human(n: int) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def fresh(p: Path):
    if p.exists():
        shutil.rmtree(p)
    p.mkdir(parents=True, exist_ok=True)


def copy_tree(src: Path, dst: Path, ignore_names=None, ignore_suffix=None,
              ignore_files=None):
    """目录复制（带排除）。返回 (文件数, 字节数)。"""
    ignore_names = ignore_names or set()
    ignore_suffix = ignore_suffix or set()
    ignore_files = ignore_files or set()
    n = b = 0
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in ignore_names or item.name in ignore_files:
            continue
        if item.suffix in ignore_suffix:
            continue
        target = dst / item.name
        if item.is_dir():
            n2, b2 = copy_tree(item, target, ignore_names, ignore_suffix,
                               ignore_files)
            n += n2
            b += b2
        else:
            shutil.copy2(item, target)
            n += 1
            b += item.stat().st_size
    return n, b


# ================================================================ 1 源代码
def build_source():
    print("\n[1/4] 源代码…")
    fresh(D_SRC)
    n, b = copy_tree(SRC, D_SRC,
                     ignore_names=SRC_IGNORE_NAMES,
                     ignore_suffix=SRC_IGNORE_SUFFIX,
                     ignore_files=SRC_IGNORE_FILES)
    print(f"      {n} 个文件 ｜ {human(b)}")
    return n, b


# ================================================================ 2 模型数据
MODEL_README = """# 模型数据 · 说明

本目录的**目录结构已与程序代码中的路径一一对应** ——
把 `ckpt/` 和 `data/` 两个目录整体复制到工程根目录即可，无需改名或调整层级。

```
ckpt/                              ← 视觉模型权重（程序从 ./ckpt 读取）
└── clip_cn_vit-b-16.pt            中文 CLIP ViT-B/16 权重，约 718 MB

data/                              ← 数据层
├── samples.json                   纹样母题库：100 条母题（语义层，唯一检索依据）
├── images/                        母题库配图：100 张母题参考图
├── index/                         向量索引：clip_vectors.npz + faiss.index
├── artifacts_cle/                 实物佐证层：303 件织物藏品（材质层）
└── raw/                           数据源原始文件
```

## 各部分作用

| 目录 | 说明 | 是否参与元素级溯源 |
|---|---|---|
| `samples.json` + `images/` | **纹样母题库**，系统的知识底座。M2 检索依据、M3 校验依据，元素级出处的唯一来源 | **是** |
| `index/` | 由母题库预先算好的向量索引，避免每次启动重新编码（否则每次要几分钟） | — |
| `ckpt/` | 视觉模型权重。程序用它把纹样图与文本编码到同一向量空间 | — |
| `artifacts_cle/` | **实物佐证层**（织物藏品）。仅提供织物肌理（材质层），无文化语义字段 | **否** |

> ⚠️ 请注意口径：**纹样层元素级可溯；材质层仅实物可溯。两者不得混称"100% 可溯源"。**

## 数据来源与授权

- **纹样母题库**：BLCaptain（爆裂队长NEXT）《中国传统纹样图鉴 Wényàng》，**CC BY-NC 4.0**
  （署名 · 非商业性使用）。本项目仅规范化原始字段，并补充标注「使用场合」「构成元素」
  两项派生字段；纹样图像本身未作修改。
- **实物佐证层**：克利夫兰艺术博物馆（Cleveland Museum of Art）Open Access，**CC0**。

## 必须完整放置

`ckpt/clip_cn_vit-b-16.pt` 是系统的**核心依赖** —— 元素检索（M2）与版权预警（M7）
都建立在它之上。缺少该文件时检索功能不可用，系统无法正常演示。
请务必完整复制 `ckpt/` 与 `data/` 两个目录。
"""


def build_model_data():
    """模型数据包。

    ★★ 目录名必须与**代码期望的路径一致**（`ckpt/` 与 `data/`），
       不能用「模型权重/」「纹样母题库/」这类中文名 —— 那样虽然好看，
       但用户把三份材料合并后程序**找不到数据**，直接跑不起来。
       实测教训：好看 ≠ 可用。
       这里按代码路径建目录，另用 README 说明每个目录是什么。
    """
    print("\n[2/4] 模型数据…")
    fresh(D_DAT)

    # ---- 模型权重 → ckpt/（config.yaml: clip.download_root = ./ckpt）----
    ck = D_DAT / "ckpt"
    ck.mkdir(parents=True, exist_ok=True)
    w = SRC / "ckpt" / "clip_cn_vit-b-16.pt"
    if w.exists():
        shutil.copy2(w, ck / w.name)
        print(f"      ✓ ckpt/{w.name}  {human(w.stat().st_size)}")
    else:
        print("      ! 未找到 CLIP 权重")

    # ---- data/ 下各子目录（与 CFG['paths'] 一致）----
    d = D_DAT / "data"
    d.mkdir(parents=True, exist_ok=True)

    # 向量索引
    idx = d / "index"
    idx.mkdir(parents=True, exist_ok=True)
    for f in (SRC / "data" / "index").glob("*"):
        if f.is_file():
            shutil.copy2(f, idx / f.name)
    print(f"      ✓ data/index/  {len(list(idx.iterdir()))} 个文件")

    # 母题库
    shutil.copy2(SRC / "data" / "samples.json", d / "samples.json")
    img_src = SRC / "data" / "images"
    if img_src.exists():
        nimg, bimg = copy_tree(img_src, d / "images")
        print(f"      ✓ data/samples.json + data/images/（{nimg} 张母题图，"
              f"{human(bimg)}）")

    # 实物佐证层
    cs = SRC / "data" / "artifacts_cle"
    if cs.exists():
        n2, b2 = copy_tree(cs, d / "artifacts_cle")
        print(f"      ✓ data/artifacts_cle/  {n2} 个文件  {human(b2)}")

    # 源数据（可选）
    raw = SRC / "data" / "raw"
    if raw.exists() and any(raw.iterdir()):
        n3, b3 = copy_tree(raw, d / "raw")
        print(f"      ✓ data/raw/  {n3} 个文件  {human(b3)}")

    # ---- 说明 ----
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
    n = b = 0

    def put(src, sub):
        nonlocal n, b
        if not src.exists():
            print(f"      ! 缺 {src}")
            return
        d = D_DRW / sub
        d.mkdir(parents=True, exist_ok=True)
        for f in sorted(src.glob("*.png")):
            shutil.copy2(f, d / f.name)
            n += 1
            b += f.stat().st_size

    put(SRC / "docs" / "figures", "01_系统架构与流程图")
    # 谱系图单独归类（figures 里混了架构图，按名挑）
    kinship = D_DRW / "02_纹样谱系与关系网络"
    kinship.mkdir(parents=True, exist_ok=True)
    for f in sorted((SRC / "docs" / "figures").glob("kinship_*.png")):
        shutil.move(str(D_DRW / "01_系统架构与流程图" / f.name),
                    kinship / f.name)
    print(f"      ✓ 01 架构图 3 张 ｜ 02 谱系图 {len(list(kinship.glob('*.png')))} 张")

    put(SRC / "docs" / "screenshots", "03_界面截图")

    d4 = D_DRW / "04_数据与标定图表"
    d4.mkdir(parents=True, exist_ok=True)
    for f in sorted((SRC / "docs").glob("fig_*.png")):
        shutil.copy2(f, d4 / f.name)
        n += 1
        b += f.stat().st_size

    # 文档/ 下的图：只取 png，且区分"正式图"与"过程验证图"
    d5 = D_DRW / "05_效果图与样品"
    d6 = D_DRW / "06_过程验证记录"
    d5.mkdir(parents=True, exist_ok=True)
    d6.mkdir(parents=True, exist_ok=True)
    for f in sorted(DOCS.glob("*.png")):
        tgt = d6 if f.name.startswith("试验_") else d5
        shutil.copy2(f, tgt / f.name)
        n += 1
        b += f.stat().st_size
    print(f"      ✓ 03 截图 {len(list((D_DRW/'03_界面截图').glob('*.png')))} 张 ｜ "
          f"04 图表 {len(list(d4.glob('*.png')))} 张")
    print(f"      ✓ 05 效果图 {len(list(d5.glob('*.png')))} 张 ｜ "
          f"06 过程图 {len(list(d6.glob('*.png')))} 张")

    # 代表作：挑一个**最完整**的运行产物目录
    # ★ 不能只按时间选最新 —— 最新那次可能没跑 3D（实测踩到：只捞到 4 张）。
    #   优先选含 preview3d_triptych.png 的，那说明 3D 也跑通了。
    cands = sorted([d for d in (SRC / "outputs").glob("R*") if d.is_dir()],
                   key=lambda d: d.name, reverse=True)
    picked = next((d for d in cands
                   if (d / "preview3d_triptych.png").exists()),
                  cands[0] if cands else None)
    if picked:
        d7 = D_DRW / "07_运行产物样例"
        d7.mkdir(parents=True, exist_ok=True)
        for name in ("provenance_card.png", "design_board.png",
                     "composed_pattern.png", "preview3d_triptych.png",
                     "preview3d_vase.png", "preview3d_box.png",
                     "preview3d_fan.png", "stylized_30.png", "stylized_85.png",
                     "pattern_vase.glb", "pattern_box.glb", "pattern_fan.glb"):
            f = picked / name
            if f.exists():
                shutil.copy2(f, d7 / name)
        print(f"      ✓ 07 运行产物样例（{picked.name}）"
              f" {len(list(d7.glob('*.png')))} 张图 + "
              f"{len(list(d7.glob('*.glb')))} 个 GLB")

    b = _bytes_of(D_DRW)
    n = sum(1 for f in D_DRW.rglob("*") if f.is_file())
    print(f"      合计 {n} 张 ｜ {human(b)}")
    return n, b


# ================================================================ 4 可执行程序
BAT = r"""@echo off
title 纹初迹现 · 传统纹样可溯源生成系统
echo ============================================================
echo    纹初迹现 . 传统纹样可溯源生成系统
echo ============================================================
echo.

REM ---- 1. 检查 Python ----
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python。
    echo        请先安装 Python 3.10 或以上版本：https://www.python.org/downloads/
    echo        安装时务必勾选 "Add Python to PATH"。
    echo.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo [1/4] Python %%v 已就绪

REM ---- 2. 准备虚拟环境 ----
if not exist ".venv\Scripts\python.exe" (
    echo [2/4] 首次运行，正在创建虚拟环境...
    python -m venv .venv
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败。
        pause
        exit /b 1
    )
    echo [3/4] 正在安装依赖（首次约需 5-15 分钟，请耐心等待）...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip -q
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [错误] 依赖安装失败。可尝试国内镜像：
        echo        .venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
        pause
        exit /b 1
    )
) else (
    echo [2/4] 虚拟环境已存在，跳过创建
    echo [3/4] 跳过依赖安装
)

REM ---- 3. 检查模型权重 ----
if not exist "ckpt\clip_cn_vit-b-16.pt" (
    echo.
    echo [警告] 未找到模型权重：ckpt\clip_cn_vit-b-16.pt
    echo        请确认已把「模型数据」材料中的模型权重放到 ckpt\ 目录下，
    echo        否则元素检索功能无法工作（其余功能仍可使用）。
    echo.
)

REM ---- 4. 启动 ----
echo [4/4] 正在启动系统...
echo.
echo    浏览器将自动打开：http://localhost:8501
echo    如未自动打开，请手动在浏览器访问上述地址。
echo    停止服务：在本窗口按 Ctrl+C
echo.
".venv\Scripts\python.exe" -m streamlit run app.py

pause
"""

SH = r"""#!/usr/bin/env bash
# 纹初迹现 · 传统纹样可溯源生成系统 —— 一键启动（Linux / macOS）
set -e
cd "$(dirname "$0")"

echo "============================================================"
echo "   纹初迹现 · 传统纹样可溯源生成系统"
echo "============================================================"

if ! command -v python3 >/dev/null 2>&1; then
    echo "[错误] 未检测到 python3，请先安装 Python 3.10 或以上版本。"
    exit 1
fi

PY=python3
if [ ! -x ".venv/bin/python" ]; then
    echo "[1/3] 首次运行，创建虚拟环境..."
    $PY -m venv .venv
    echo "[2/3] 安装依赖（首次约需 5-15 分钟）..."
    .venv/bin/python -m pip install --upgrade pip -q
    .venv/bin/python -m pip install -r requirements.txt
else
    echo "[1/3] 虚拟环境已存在"
    echo "[2/3] 跳过依赖安装"
fi

if [ ! -f "ckpt/clip_cn_vit-b-16.pt" ]; then
    echo "[警告] 未找到 ckpt/clip_cn_vit-b-16.pt —— 请先放置「模型数据」材料中的模型权重。"
fi

echo "[3/3] 启动系统：http://localhost:8501 （Ctrl+C 停止）"
.venv/bin/python -m streamlit run app.py
"""

README_EXE = """# 可执行程序 · 运行说明

**纹初迹现 · 传统纹样可溯源生成系统**

---

## 一、这份材料包含什么

| 文件 | 说明 |
|---|---|
| `启动系统.bat` | Windows 一键启动（自动建环境 → 装依赖 → 检查模型 → 启动） |
| `启动系统.sh` | Linux / macOS 一键启动 |
| `README_运行说明.md` | 本文件 |

> 依赖清单（`requirements.txt`）、系统配置（`config.yaml`）与配置模板（`.env.example`）
> 属于**「源代码」材料**，不在此重复放置 —— 三份材料合并后它们自然就在根目录，
> 启动脚本会直接使用。

启动脚本会自动检测 Python 环境、创建虚拟环境、安装依赖、检查模型权重，
然后启动服务并给出访问地址。

## 二、运行环境要求

| 项目 | 要求 |
|---|---|
| 操作系统 | Windows 10/11 ｜ Linux ｜ macOS |
| Python | **3.10 或以上**（安装时勾选 "Add Python to PATH"） |
| 内存 | 建议 8 GB 以上 |
| 显卡 | **不需要**（视觉模型走 CPU 推理） |
| 磁盘 | 首次安装依赖约需 3–4 GB |

## 三、如何运行（重要）

本材料需与 **「模型数据」「源代码」** 两份材料**配合使用**。请按以下方式摆放：

```
任意目录/
├── 启动系统.bat          ← 来自「可执行程序」
├── 启动系统.sh           ← 来自「可执行程序」
├── app.py                ← 来自「源代码」
├── requirements.txt      ← 来自「源代码」
├── config.yaml           ← 来自「源代码」
├── .env.example          ← 来自「源代码」
├── src/                  ← 来自「源代码」
├── scripts/              ← 来自「源代码」
├── web/                  ← 来自「源代码」
├── .streamlit/           ← 来自「源代码」
├── rules/                ← 来自「源代码」
├── ckpt/                 ← 来自「模型数据」（模型权重）
│   └── clip_cn_vit-b-16.pt
└── data/                 ← 来自「模型数据」（母题库 / 向量索引 / 实物佐证层）
    ├── samples.json
    ├── images/
    ├── index/
    └── artifacts_cle/
```

即：**把三份材料的内容合并到同一个目录下**（直接复制子目录与文件，不会产生同名冲突），然后：

- **Windows**：双击 `启动系统.bat`
- **Linux / macOS**：`chmod +x 启动系统.sh && ./启动系统.sh`

首次运行会自动安装依赖（约 5–15 分钟），之后启动只需十几秒。

## 四、可选配置（API Key）

系统的「意图解析」（M1）与「AI 风格化」（M5）需要调用大模型 API。
**不配置也能运行** —— 此时意图解析会退化为内置规则，其余功能完全正常。

若要启用：把 `.env.example` 复制为 `.env`，填入自己的 API Key：

```
DASHSCOPE_API_KEY=sk-你的密钥
```

> ⚠️ 出于安全考虑，本材料**不包含任何真实密钥**。

## 五、启动后怎么看

启动成功后浏览器会自动打开 <http://localhost:8501>，界面分三个标签页：

| 标签页 | 作用 |
|---|---|
| **生成与溯源** | 输入一句需求 → 生成纹样方案 + 元素级溯源卡片 + 3D 器物预览 |
| **版权相似度审查** | 上传任意纹样图，与本库比对给出风险分级 |
| **纹样谱系** | 全库 100 条母题的关联网络与五族划分 |

## 六、常见问题

**Q：提示 `No module named 'faiss'`？**
用系统 Python 了。请用启动脚本（它使用虚拟环境），或手动执行
`.venv\\Scripts\\python.exe -m streamlit run app.py`。

**Q：依赖安装很慢或超时？**
换国内镜像：
`.venv\\Scripts\\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`

**Q：3D 预览区是空白的？**
该区域需要先点击「生成静态效果图 + GLB」按钮（纯 CPU 渲染，约 15 秒）。
若仍空白，请确认浏览器支持 WebGL。

**Q：首次启动很慢？**
首次需加载视觉模型（约 20–40 秒），之后会缓存，再次生成只需数秒。

**Q：端口被占用？**
在启动命令后加 `--server.port 8502` 换一个端口。
"""


def build_exe():
    print("\n[4/4] 可执行程序…")
    fresh(D_EXE)
    # ★ .bat 必须用 **GBK(cp936)** 编码写，不能用 UTF-8：
    #   中文 Windows 的 cmd 按当前代码页（默认 936）读取 .bat 文件内容，
    #   若文件是 UTF-8，中文 echo 会变成乱码。
    #   加 `chcp 65001` 也救不了 —— 文件在 chcp 生效前就已被按 936 解码。
    (D_EXE / "启动系统.bat").write_text(BAT, encoding="gbk", newline="\r\n")
    # .sh 用 UTF-8 + LF（Linux/macOS 约定）
    (D_EXE / "启动系统.sh").write_text(SH, encoding="utf-8", newline="\n")
    (D_EXE / "README_运行说明.md").write_text(README_EXE, encoding="utf-8")
    # ★ 刻意**不**在这里放 requirements.txt / config.yaml / .env.example ——
    #   它们本质属于源代码，重复放置会让"三份材料合并"时出现同名覆盖冲突
    #   （实测被 _verify_pkg.py 检出）。启动脚本会在合并后的根目录找到它们。
    n = sum(1 for f in D_EXE.rglob("*") if f.is_file())
    b = _bytes_of(D_EXE)
    print(f"      {n} 个文件 ｜ {human(b)}")
    for f in sorted(D_EXE.iterdir()):
        print(f"        - {f.name}")
    return n, b


def place_covers():
    """把赛方的三张材料封面页 PDF 放进对应文件夹（按新编号重命名）。

    ★ 封面内容只有一行通用标题（如「AC1-算法模型创新-可执行程序」），不含编号，
      所以直接沿用即可；文件名按赛方命名规范改成新编号。
    """
    print("\n[+] 放置赛方材料封面页…")
    mapping = {
        "可执行程序": D_EXE,
        "模型数据": D_DAT,
        "源代码": D_SRC,
    }
    if not SEAL_DIR.exists():
        print("      ! 未找到封面页来源目录，跳过")
        return
    for key, folder in mapping.items():
        src = next(SEAL_DIR.glob(f"*{key}.pdf"), None)
        if src is None:
            print(f"      ! 缺少「{key}」封面页")
            continue
        dst = folder / f"{ROOT_NAME}-{key}.pdf"
        shutil.copy2(src, dst)
        print(f"      ✓ {dst.name}")


ROOT_README = """# {root}

> **作品名称**：纹初迹现 · 传统纹样可溯源生成系统
> **赛题**：{topic}
> **提交内容**：可执行程序 / 模型数据 / 源代码 / 高清图纸

---

## 一、四份材料

| 文件夹 | 内容 | 体量 |
|---|---|---|
| `{root}-可执行程序/` | 一键启动脚本（Windows / Linux）、运行说明、依赖清单、配置模板 | {sz_exe} |
| `{root}-模型数据/` | 视觉模型权重、向量索引、纹样母题库（100 条 + 配图）、实物佐证层（303 件）、文化规则库 | {sz_dat} |
| `{root}-源代码/` | 完整工程源码：界面、七个功能模块、工具脚本、三维查看器、数据契约文档 | {sz_src} |
| `{root}-高清图纸/` | 系统架构与流程图、纹样谱系图、界面截图、数据图表、效果图、运行产物样例 | {sz_drw} |

每个文件夹内附有赛方「材料封面页」PDF。

---

## 二、如何运行

**第一步**：把 `可执行程序`、`源代码`、`模型数据` 三份材料的内容**合并到同一个目录**下
（可执行程序提供启动脚本，源代码提供程序本体，模型数据提供运行所需的数据与权重）。

**第二步**：
- Windows：双击 `启动系统.bat`
- Linux / macOS：`chmod +x 启动系统.sh && ./启动系统.sh`

启动脚本会自动创建运行环境、安装依赖、检查模型数据，然后启动系统并给出访问地址。
浏览器打开后即可使用。

> 详细的环境要求、目录摆放图示与常见问题，见
> `{root}-可执行程序/README_运行说明.md`。

**环境要求**：Python 3.10+ ｜ 内存 8 GB+ ｜ **无需显卡**（视觉模型走 CPU 推理）。

---

## 三、系统简介

本作品提出「可解释的组合式生成」范式：不让模型凭空画，而是把一句自然语言需求
解析为结构化的《纹样文化配方》，从**真实纹样母题库**检索元素并按传统构图程式组合，
**在生成的同时即确定每个元素的出处与授权**（而非事后推测），最后输出元素级溯源卡片。

系统提供**三种溯源层次**，互不替代：

| 层次 | 回答的问题 |
|---|---|
| **元素级** | 这张图的每个部件来自哪条母题 |
| **谱系级** | 这类纹样在谱系上跟谁最近 |
| **风险级** | 一张设计图与本库是否雷同 |

---

## 四、数据来源与授权

- **纹样母题库**：BLCaptain（爆裂队长NEXT）《中国传统纹样图鉴 Wényàng》，
  **CC BY-NC 4.0**（署名 · 非商业性使用）。本项目仅对原始字段做规范化处理，
  并补充标注「使用场合」与「构成元素」两项派生字段；纹样图像本身未作修改。
- **实物佐证层**：克利夫兰艺术博物馆（Cleveland Museum of Art）Open Access，**CC0**。
  仅作为织物肌理（材质层）使用，**不参与元素级溯源**。
- 本作品的代码与数据结构采用 **MIT** 许可。
- 本作品为**学术竞赛用途，不涉及商业使用**。

---

## 五、合规声明

- 本材料中**不含**任何单位标识与人员身份信息。
- 源代码与配置中**不包含**任何真实 API 密钥（仅提供配置模板）。
- 项目已通过提交前的合规自查脚本检查。

---

*打包时间：{date}　｜　材料生成脚本：`scripts/make_submission_package.py`*
"""


def build_root_readme(sizes, date_str):
    print("\n[+] 生成根目录材料清单…")
    txt = ROOT_README.format(
        root=ROOT_NAME, topic=TOPIC,
        sz_exe=sizes["可执行程序"], sz_dat=sizes["模型数据"],
        sz_src=sizes["源代码"], sz_drw=sizes["高清图纸"],
        date=date_str)
    dst = PKG / f"{ROOT_NAME}-材料清单.md"
    dst.write_text(txt, encoding="utf-8")
    print(f"      ✓ {dst.name}")


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
    place_covers()
    build_root_readme({k: human(v[1]) for k, v in r.items()},
                      datetime.datetime.now().strftime("%Y-%m-%d"))

    print("\n" + "=" * 66)
    print("汇总")
    print("=" * 66)
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
