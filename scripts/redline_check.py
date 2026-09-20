# scripts/redline_check.py
"""提交前红线自查：扫描指定目录 / 文件的全文，命中敏感信息就报错。

内置通用规则：手机号 / 身份证号 / 学号 / 邮箱
项目专属规则：读 redline.yaml 的 patterns 段（学校名、人名、群号等）

用法（在工程根目录 work/ 下执行）：
    .venv/Scripts/python.exe scripts/redline_check.py ../文档/ dist/
    .venv/Scripts/python.exe scripts/redline_check.py --config redline.yaml ../文档/ dist/

退出码：0 = 未命中；1 = 有命中（提交前必须逐条处理）

⚠️ redline.yaml 本身含敏感串，已加入 .gitignore —— 绝不能让词表自己成为泄露源。
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 通用规则：(正则, 说明)
GENERIC = [
    (r"1[3-9]\d{9}", "疑似手机号"),
    (r"\b\d{17}[\dXx]\b", "疑似身份证号"),
    (r"\b(?:19|20)\d{2}\d{6,}\b", "疑似学号"),
    (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "疑似邮箱"),
]

# 只扫这些后缀的文本文件
TEXT_EXT = {".md", ".txt", ".html", ".htm", ".csv", ".json", ".yaml", ".yml",
            ".py", ".js", ".css", ".xml", ".rtf"}

# ★ 跳过这些目录。**必须有** —— 否则 `redline_check.py .` 会扫进 .venv/，
#   三方库源码里全是形似手机号/身份证的数字串（实测 15328 个文件命中 14296 处，全是噪声），
#   真正的风险会被淹没，E1 环节直接不可用。
EXCLUDE_DIRS = {".venv", "venv", "env", "__pycache__", ".git", ".idea", ".vscode",
                "node_modules", "ckpt", "outputs", ".pytest_cache"}

# ★ 词表文件自己要被排除。理由：redline.yaml 里**原样存着敏感串本身**，
#   而 .example 里存着规则的字面量 —— 扫它们就是在让词表自己变成泄露源，
#   也正是本文件开头那条警告要防的事。（本条注释刻意不复述具体词，否则它自己就会被命中。）
EXCLUDE_FILE_PREFIX = "redline.yaml"

# 二进制 / 媒体 / 压缩包：本就不是文本，扫了只会乱报
EXCLUDE_SUFFIX = {".bak", ".pyc", ".pyo", ".png", ".jpg", ".jpeg", ".gif", ".webp",
                  ".zip", ".7z", ".rar", ".pptx", ".docx", ".xlsx", ".pdf",
                  ".pt", ".pth", ".npz", ".npy", ".index", ".glb", ".gltf", ".mp4"}


def load_project_rules(yaml_path: Path):
    """读 redline.yaml：
    patterns:
      - pattern: "某某大学"
        label: "学校名称"
    """
    if not yaml_path.exists():
        print(f"[警告] 未找到 {yaml_path.name}，本次只跑内置通用规则")
        return []
    try:
        import yaml
    except ImportError:
        print("[警告] 未安装 pyyaml，跳过项目专属规则（pip install pyyaml）")
        return []
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    out = []
    for item in data.get("patterns", []) or []:
        pat = item.get("pattern")
        if pat:
            out.append((pat, item.get("label", "项目专属规则")))
    return out


def _skipped(path: Path):
    """是否跳过该文件。"""
    if path.suffix.lower() in EXCLUDE_SUFFIX:
        return True
    if path.name.startswith(EXCLUDE_FILE_PREFIX):
        return True
    if any(part in EXCLUDE_DIRS for part in path.parts):
        return True
    return False


def iter_files(targets):
    for t in targets:
        p = Path(t) if Path(t).is_absolute() else (Path.cwd() / t)
        p = p.resolve()
        if p.is_file():
            # 显式点名的文件照样尊重排除规则（不然 `redline_check.py .` 仍会漏进去）
            if _skipped(p):
                print(f"[跳过] {p.name}（在排除名单内）")
            else:
                yield p
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() in TEXT_EXT and not _skipped(f):
                    yield f
        else:
            print(f"[警告] 路径不存在，已跳过：{p}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="+", help="要扫描的目录或文件（可多个）")
    ap.add_argument("--config", default="redline.yaml", help="项目专属规则文件")
    args = ap.parse_args()

    cfg = Path(args.config)
    if not cfg.is_absolute():
        cfg = ROOT / cfg
    project_rules = load_project_rules(cfg)
    rules = project_rules + GENERIC
    print(f"启用规则 {len(rules)} 条（项目专属 {len(project_rules)} + 通用 {len(GENERIC)}）\n")

    n_files = n_hits = 0
    for f in iter_files(args.targets):
        n_files += 1
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            print(f"[警告] 读取失败：{f}（{type(e).__name__}）")
            continue
        try:
            shown = f.relative_to(ROOT)
        except ValueError:
            shown = f
        for i, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            for pat, label in rules:
                m = re.search(pat, line)
                if m:
                    n_hits += 1
                    print(f"[命中] {shown}:{i}  {label}")
                    print(f"       {line.strip()[:100]}")
                    print(f"       匹配：{m.group(0)}")

    print(f"\n扫描 {n_files} 个文件，命中 {n_hits} 处。")
    if n_hits:
        print("[FAIL] 存在红线风险 —— 逐条处理（删除 / 改写 / 确认可接受）后再提交")
        return 1
    print("[PASS] 未命中任何红线规则")
    return 0


if __name__ == "__main__":
    sys.exit(main())
