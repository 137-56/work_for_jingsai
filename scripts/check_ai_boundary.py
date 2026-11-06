# scripts/check_ai_boundary.py
"""AI 新产物**边界**自查（批次 1 地基，只读）。

★ 三条断言
    ① `outputs/ai/` 不得出现在提交包验收的 NEED / NEED_WEB 清单里
       （AI 产物不进提交包主线）；
    ② AI 产物不得进定稿 run：定稿 run 文件集合/字节/sha256 与基线全等、
       目录内无 AI 标记文件、打包脚本不引用 `outputs/ai/`，
       且 AI 产物不进 web/glb/ 与 static/viewer/glb/ 三处同源链；
    ③ 无 `.env` 真实密钥外泄：把 `.env` 里的实际值当**词表**扫全仓文本，
       命中即 FAIL。报告只给路径 + 行号 + 类别，**绝不回显值或整行**。

★ 反例可注入
    `--pkg-check-src` 可指向系统临时目录里的 `check_submission_pkg.py` 副本
    （把 `outputs/ai` 塞进 NEED 清单），用于证明 ① 真的会 FAIL，用完即删。
    `--final-run` / `--baseline` 可指向临时副本，用于证明 ② 可证伪。

用法（在工程根目录 work/ 下执行）：
    .venv/Scripts/python.exe scripts/check_ai_boundary.py
    .venv/Scripts/python.exe scripts/check_ai_boundary.py --pkg-check-src <临时副本>

退出码：0 = 三条全过；1 = 任一失败。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.run_source import FINAL_RUN            # noqa: E402

DEFAULT_PKG_CHECK_SRC = ROOT / "scripts" / "check_submission_pkg.py"
DEFAULT_BASELINE = ROOT / "scripts" / "final_run_baseline.json"
AI_DIR_TOKEN = "outputs/ai"
AI_MARKER_PREFIXES = ("stylized_", "ai_glb_manifest.json", "ai_texture_", "ai_")
PKG_SCRIPT_NAMES = ("check_submission_pkg.py", "make_submission_package.py",
                    "make_submission_package_web.py")

TEXT_EXT = {".md", ".txt", ".html", ".htm", ".csv", ".json", ".yaml", ".yml",
            ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue",
            ".css", ".scss", ".toml", ".svg", ".xml", ".rtf", ".example"}
EXCLUDE_DIRS = {".venv", "venv", "env", "__pycache__", ".git", ".idea", ".vscode",
                "node_modules", "ckpt", "outputs", ".pytest_cache", "vendor",
                "libs", ".workbuddy"}
# 词表自身含敏感串，扫它等于让词表成为泄露源。
EXCLUDE_FILE_NAMES = {"redline.yaml", ".env"}


def _load_module(path: Path, name: str):
    """按路径动态加载模块（可与仓库内同名模块互不干扰）。"""
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"无法为 {path} 建立模块规格")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(spec.name, None)
    return mod


def _norm(value: Any) -> str:
    """路径统一成正斜杠小写形态，便于跨 Windows / POSIX 比对。"""
    return str(value).replace("\\", "/").lower()


def check_pkg_lists(pkg_check_src: Path) -> tuple[bool, str]:
    """① outputs/ai 不在 NEED / NEED_WEB；且 .env 也不在清单里。"""
    if not pkg_check_src.is_file():
        return False, f"提交包验收模块不存在：{pkg_check_src}"
    try:
        mod = _load_module(pkg_check_src, "_ai_boundary_pkg_probe")
    except Exception as e:
        return False, f"加载提交包验收模块失败（{type(e).__name__}）"
    hits: list[str] = []
    for list_name in ("NEED", "NEED_WEB"):
        items = getattr(mod, list_name, None)
        if not isinstance(items, list):
            return False, f"{list_name} 不是列表（契约被改动）"
        for item in items:
            n = _norm(item)
            if AI_DIR_TOKEN in n:
                hits.append(f"{list_name} 含 {AI_DIR_TOKEN}")
            if n == ".env" or n.endswith("/.env"):
                hits.append(f"{list_name} 含 .env")
    if hits:
        return False, "；".join(sorted(set(hits)))
    return True, f"NEED/NEED_WEB 均无 {AI_DIR_TOKEN} 与 .env"


def _immutable_module():
    """加载同目录的不可变基线模块，复用其 verify（不重复实现）。"""
    return _load_module(ROOT / "scripts" / "check_final_run_immutable.py",
                        "_ai_boundary_immutable_probe")


def check_ai_not_in_final_run(final_run: Path, baseline: Path,
                              pkg_check_src: Path) -> tuple[bool, str]:
    """② AI 产物不进定稿 run / 打包脚本 / 三处同源链。"""
    problems: list[str] = []
    try:
        ok, msg = _immutable_module().verify(final_run, baseline,
                                             allow_freeze=False)
    except Exception as e:
        return False, f"定稿 run 基线校验异常（{type(e).__name__}）"
    if not ok:
        problems.append(f"定稿 run 与基线不等：{msg}")

    run = Path(final_run)
    if run.is_dir():
        for p in run.iterdir():
            if p.is_file() and p.name.lower().startswith(
                    tuple(x.lower() for x in AI_MARKER_PREFIXES)):
                problems.append(f"定稿 run 内出现 AI 标记文件（类别：{p.suffix}）")

    # 打包脚本正文不得引用 AI 产物目录（连说明性引用也不放，避免后来顺手打包）。
    scan_srcs = [pkg_check_src] + [ROOT / "scripts" / n
                                   for n in PKG_SCRIPT_NAMES[1:]]
    for src in scan_srcs:
        if not src.is_file():
            continue
        text = src.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(text.splitlines(), 1):
            if AI_DIR_TOKEN in _norm(line):
                problems.append(f"打包脚本引用了 {AI_DIR_TOKEN}（{src.name}:{i}）")
                break

    # AI 产物不得进 web/glb 与 static/viewer/glb 的同源链。
    for chain in (ROOT / "web" / "glb", ROOT / "static" / "viewer" / "glb"):
        if chain.is_dir():
            for p in chain.iterdir():
                if p.is_file() and p.name.lower().startswith("ai_"):
                    problems.append(f"同源链目录出现 AI 产物（{chain.name}）")
                    break

    if problems:
        return False, "；".join(problems[:8])
    return True, "定稿 run 与基线全等，无 AI 标记文件，打包脚本/同源链均无 AI 产物"


def _is_placeholder(value: str) -> bool:
    """明显是占位示例的值不算真实密钥。"""
    low = value.lower()
    return (not value or "xxxx" in low or "your" in low or "changeme" in low
            or "<" in value or ">" in value or set(value) <= {"*", "-", "."})


def _env_values() -> list[str]:
    """读 .env，返回可能为真实密钥的值（不打印、不落盘）。"""
    env = ROOT / ".env"
    if not env.is_file():
        return []
    try:
        lines = env.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    values: list[str] = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        _, raw = s.split("=", 1)
        v = raw.strip().strip('"').strip("'")
        if len(v) >= 8 and not _is_placeholder(v):
            values.append(v)
    return values


def _iter_text_files() -> Iterator[Path]:
    """遍历全仓可扫文本（排除二进制目录与词表自身）。"""
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file() or p.name in EXCLUDE_FILE_NAMES:
            continue
        if any(part in EXCLUDE_DIRS for part in p.parts):
            continue
        if p.suffix.lower() in TEXT_EXT:
            yield p


def check_no_env_secret_leak() -> tuple[bool, str]:
    """③ 全仓文本不得出现 .env 里的真实值；命中只报路径+行号+类别。"""
    values = _env_values()
    if not values:
        return True, "无可外泄的真实配置值（.env 不存在或全为占位）"
    hits: list[str] = []
    n_files = 0
    for p in _iter_text_files():
        n_files += 1
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for v in values:
            if v not in text:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if v in line:
                    hits.append(f"{p.relative_to(ROOT).as_posix()}:{i}（配置值外泄）")
                    break
    if hits:
        return False, "；".join(sorted(set(hits))[:8])
    return True, f"扫 {n_files} 个文本、{len(values)} 个配置值，0 命中"


def verify(pkg_check_src: Path, final_run: Path,
           baseline: Path) -> tuple[bool, str]:
    """跑完三条断言，返回 (是否全过, 汇总说明)。"""
    checks = [
        ("① 提交包清单边界", check_pkg_lists(pkg_check_src)),
        ("② 定稿 run / 同源链边界",
         check_ai_not_in_final_run(final_run, baseline, pkg_check_src)),
        ("③ .env 配置值不外泄", check_no_env_secret_leak()),
    ]
    problems = [f"{label} —— {msg}" for label, (ok, msg) in checks if not ok]
    if problems:
        return False, "；".join(problems)
    return True, "；".join(f"{label}：{msg}" for label, (_, msg) in checks)


def main() -> int:
    ap = argparse.ArgumentParser(description="AI 新产物边界自查（只读）")
    ap.add_argument("--pkg-check-src", default=str(DEFAULT_PKG_CHECK_SRC),
                    help="提交包验收模块（可指向系统临时目录的反例副本）")
    ap.add_argument("--final-run", default=str(FINAL_RUN),
                    help="定稿 run 目录（默认读 src.run_source.FINAL_RUN）")
    ap.add_argument("--baseline", default=str(DEFAULT_BASELINE),
                    help="不可变基线 JSON 路径")
    args = ap.parse_args()
    pkg_check_src = Path(args.pkg_check_src)
    final_run = Path(args.final_run)
    baseline = Path(args.baseline)

    print("=" * 68)
    print("AI 新产物 · 边界自查（只读）")
    print("=" * 68)
    checks = [
        ("① 提交包清单边界", check_pkg_lists(pkg_check_src)),
        ("② 定稿 run / 同源链边界",
         check_ai_not_in_final_run(final_run, baseline, pkg_check_src)),
        ("③ .env 配置值不外泄", check_no_env_secret_leak()),
    ]
    failed = 0
    for label, (ok, msg) in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {label} —— {msg}")
        if not ok:
            failed += 1
    print("-" * 68)
    if failed:
        print(f"[FAIL] 汇总：通过 {len(checks) - failed} / 失败 {failed} —— 修正后再提交")
        return 1
    print(f"[PASS] 汇总：通过 {len(checks)} / 失败 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
