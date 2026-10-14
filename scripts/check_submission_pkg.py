# scripts/check_submission_pkg.py
"""提交包验收：模拟"三份材料合并"，核对代码依赖的路径是否齐备、有无冲突。

★ 为什么必须做这一步
    提交材料按要求拆成若干包后，**用户（或评委）要手动合并才能运行**。
    如果某一份材料把文件放错层级 —— 比如用中文目录名代替代码期望的
    `ckpt/`、`data/` —— 交出去时看着完整，一跑就报错。
    这是最致命也最隐蔽的交付事故，必须用脚本提前挡住。

★ 检查三件事
    1. 冲突：同一相对路径出现在两份材料里（合并时要覆盖，容易出错）
    2. 齐备：代码真正会读的路径（config.yaml / CFG["paths"] / 源码常量）是否都在
    3. 安全：不得含 .env（真实密钥）/ .venv / .git

用法：
    .venv/Scripts/python.exe scripts/check_submission_pkg.py
    .venv/Scripts/python.exe scripts/check_submission_pkg.py --pkg "D:/.../AIC-2026-xxx-算法模型创新-纹初迹现"
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_PKG = Path(
    r"D:/work/work_space/DeskTop/DeskBox/AIC-2026-49790132-算法模型创新-纹初迹现")

# 代码真正会读的路径（来自 config.yaml 的 paths、clip.download_root、源码常量）
NEED = [
    # 可执行程序
    "启动系统.bat", "启动系统.sh", "README_运行说明.md",
    # 源代码
    "app.py", "config.yaml", "requirements.txt", ".env.example",
    ".streamlit/config.toml",
    "src/pipeline.py", "src/m1_intent.py", "src/m2_retrieve.py",
    "src/m3_validate.py", "src/m4_compose.py", "src/m5_stylize.py",
    "src/m6_provenance.py", "src/m7_copyright.py", "src/artifact_layer.py",
    "src/clip_model.py", "src/pattern_layout.py", "src/preview3d.py",
    "src/glb_export.py", "src/style_ground.py", "src/utils.py",
    "web/viewer.html", "web/vendor/three.min.js", "web/vendor/GLTFLoader.js",
    "rules/culture_rules.json",
    # 模型数据
    "data/samples.json",
    "data/index/faiss.index",
    "data/index/clip_vectors.npz",
    "data/images/WENYANG-001.jpg",
    "data/artifacts_cle/index.json",
    "ckpt/clip_cn_vit-b-16.pt",
]

DEFAULT_PKG_WEB = Path(
    r"D:/work/work_space/DeskTop/DeskBox/"
    r"AIC-2026-49790132-算法模型创新-纹初迹现-Web演示版")

# Web 演示版：单页应用 + Serverless 函数，无本地模型
NEED_WEB = [
    # 可执行程序
    "启动预览.bat", "启动预览.sh", "部署到Netlify.md", "README_运行说明.md",
    # 源代码
    "index.html", "config.js", "netlify.toml", "package.json",
    "netlify/functions/proxy.mjs",
    "netlify/functions/submit3d.mjs",
    "netlify/functions/check3d.mjs",
    "netlify/functions/modelStore.mjs",
    "netlify/functions/getmodel.mjs",
    "libs/model-viewer.min.js",
    # 模型数据（本版本无模型权重，只有业务数据）
    "data/patterns.json",
    "images/patterns/w001.jpg",
    "README_模型数据.md",
]

PROFILES = {"main": NEED, "web": NEED_WEB}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkg", default=None,
                    help="提交包根目录（不给则按 --profile 取默认路径）")
    ap.add_argument("--profile", choices=list(PROFILES), default="main",
                    help="main=Streamlit 主版本（默认）；web=Web 演示版")
    args = ap.parse_args()
    need = PROFILES[args.profile]
    pkg = Path(args.pkg) if args.pkg else (
        DEFAULT_PKG if args.profile == "main" else DEFAULT_PKG_WEB)

    if not pkg.exists():
        print(f"★ 找不到提交包：{pkg}")
        return 1

    subs = sorted([d for d in pkg.iterdir() if d.is_dir()])
    if not subs:
        print(f"★ {pkg} 下没有子目录")
        return 1

    print("=" * 64)
    print(f"提交包验收：{pkg.name}")
    print("=" * 64)

    # ---- 1. 模拟合并：收集每份材料提供的相对路径 ----
    merged = {}
    conflicts = defaultdict(list)
    for base in subs:
        name = base.name.replace(pkg.name + "-", "") or base.name
        n = 0
        for f in base.rglob("*"):
            if f.is_file():
                rel = f.relative_to(base).as_posix()
                if rel in merged:
                    conflicts[rel].append(name)
                merged[rel] = name
                n += 1
        print(f"  {name:12s} 提供 {n:4d} 个文件")
    print(f"\n合并后文件数：{len(merged)}")

    # ---- 2. 冲突 ----
    dup = {k: v for k, v in conflicts.items() if v}
    print(f"\n[1] 同名路径冲突：{len(dup)} 个")
    if dup:
        for k, v in list(dup.items())[:15]:
            print(f"    ★ {k}  ← 同时来自 {merged[k]} 与 {v}")
    else:
        print("    ✓ 无冲突，可直接合并")

    # ---- 3. 齐备 ----
    miss = [p for p in need if p not in merged]
    print(f"\n[2] 代码依赖路径：{len(need)} 项，缺失 {len(miss)} 项")
    if miss:
        for p in miss:
            print(f"    ★ 缺失 {p}")
    else:
        print("    ✓ 全部齐备")

    # ---- 4. 安全 ----
    env = [k for k in merged if k == ".env" or k.endswith("/.env")]
    junk = [k for k in merged
            if k.startswith((".venv/", ".git/", "__pycache__/"))]
    print("\n[3] 安全检查")
    print(f"    {'★ 发现 .env（真实密钥）！' if env else '✓ 无 .env'}")
    print(f"    {'★ 发现环境/仓库目录！' if junk else '✓ 无 .venv / .git / __pycache__'}")

    ok = not dup and not miss and not env and not junk
    print("\n" + "=" * 64)
    print("✓ 验收通过：三份材料合并到同一目录即可运行" if ok
          else "★ 验收不通过，需修复")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
