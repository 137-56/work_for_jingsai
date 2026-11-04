# scripts/check_merge_contract.py
"""两工程合并 · 结构性断言（只读）。

★ 为什么是「结构」断言
   合并的底线是：不把另一工程的数据 / 配置 / 云函数搬进本仓，也不把定稿 run
   的目录写得到处都是。本脚本只做**可审计的结构断言**，不判断内容好坏：

     ① data/samples.json 恒 100 条
     ② rules/culture_rules.json 非空且 ≥ 25 条
     ③ 全仓不出现另一工程的数据指纹（只按抽象结构特征识别）
     ④ 定稿 run 的 run id 字面量在 .py 全文本中恰好 1 处，且来自 FINAL_RUN
     ⑤ --pkg <path>：提交包不得出现另一工程的数据 / 云函数 / 配置结构标记

★ ③ 为什么只写抽象结构特征
   项目规范（docs/redline_notes.md）要求：任何具体命中串都不得写进正则、
   注释或 docstring —— 自查器扫的是全文，注释一样会被扫。因此这里识别的是
   **形状**：样本库规模、顶层键的组合、固定缩图尺寸、id 的编号形态与序号
   区间、以及「大量条目共享同一署名值」这一类结构特征。
   本仓若干脚本会**描述**另一工程的形态（例如提交包制作脚本里的目录清单），
   那是合法说明文字、不是搬进来的数据。故结构检测只读**数据文件**；对脚本
   文档仅检测「成序列的 id 值」，单个范围端点不构成指纹。

★ ④ 为什么用严格全文本计数（主理人 2026-11-04 裁定）
   redline_notes.md 的规矩是不为一时变绿放宽检查器。若按「跳过 docstring」
   计数，等于把一类出现排除在外，正是放宽；而且 docstring 里硬编码定稿 run
   本身就是过期隐患（换 run 时示例失真）。故按全文本计数，不依赖 ast，
   简单可审计 —— ast 解析遇到语法错误还会把检查器自己弄挂。
   定稿 run 的目录只由 src.run_source.FINAL_RUN 保存；本脚本自身不硬编码
   该字面量，搜索 token 由 FINAL_RUN.name 取得。

★ 本批不加入针对第二批「6 步向导」代码的断言（禁 shuffle /  onerror= /
   硬编码状态词等）—— 那些代码还不存在，且 app.py 现有合法三态文案全仓
   扫会误报。留给第二批。

用法（在工程根目录 work/ 下执行）：
    .venv/Scripts/python.exe scripts/check_merge_contract.py
    .venv/Scripts/python.exe scripts/check_merge_contract.py --pkg "D:/.../提交包"

退出码：0 = 全部通过；1 = 任一项失败。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.run_source import FINAL_RUN            # noqa: E402

# ---------------------------------------------------------------- 契约常量
SAMPLES = ROOT / "data" / "samples.json"
RULES = ROOT / "rules" / "culture_rules.json"
EXPECTED_SAMPLE_COUNT = 100
MIN_RULE_COUNT = 25

# 扫描时跳过的目录（复用 redline_check.py 的 EXCLUDE_DIRS 思路）。
EXCLUDE_DIRS = {
    ".venv", "venv", "env", "__pycache__", ".git", ".idea", ".vscode",
    "node_modules", "ckpt", "outputs", ".pytest_cache", "vendor", "libs",
    "static", "viewer", ".workbuddy",
}

# 只把这些后缀当文本扫（与 redline_check.py 的 TEXT_EXT 对齐）。
TEXT_EXT = {
    ".md", ".txt", ".html", ".htm", ".csv", ".json", ".yaml", ".yml",
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue",
    ".css", ".scss", ".toml", ".svg", ".xml", ".rtf",
}

# ③ 的抽象结构特征常量 —— 全是形状 / 数值特征，不是任何具体命中串。
OTHER_LIB_ARRAY_LEN = 500          # 另一工程样本库的规模
OTHER_LIB_TOP_KEY = "patterns"     # 另一工程数据的顶层键
OTHER_LIB_EMPTY_KEY = "rules"      # 与之同现的空数组键
THUMB_W, THUMB_H = 480, 640        # 另一工程配图的固定尺寸
W_ID_RE = re.compile(r"\bw(\d{3})\b")   # 另一工程的 id 编号形态
W_ID_MIN_SEQ = 100                 # 序号须越过本仓说明文字里的小序号端点
ID_SEQ_MIN_DISTINCT = 3            # 单个端点不算序列，≥3 个不同值才算指纹
# 署名类字段名（通用键名，不含任何具体署名内容）。
SIGNATURE_KEYS = {"author", "creator", "signature", "credit",
                  "attribution", "byline", "署名", "作者", "绘制", "设计"}
SIGNATURE_MIN_RATIO = 0.8

# ⑤ 提交包里不应出现的另一工程结构标记（通用技术目录 / 文件名，非敏感串）。
PKG_CLOUD_FN_DIRS = {"functions"}
PKG_DATA_DIRS = {"patterns"}
PKG_CONFIG_FILES = {"netlify.toml", "config.js", "patterns.json"}

RUN_SOURCE_REL = "src/run_source.py"


def iter_scan_files() -> list[Path]:
    """遍历 work/ 全树，产出未被排除的文本文件（按路径排序，便于复现）。"""
    out = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in p.parts):
            continue
        if p.suffix.lower() in TEXT_EXT:
            out.append(p)
    return sorted(out)


def _read_text(path: Path) -> str:
    """读文本；读不了时返回空串（由各检查项自行判定，不静默当通过）。"""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _iter_arrays(node: Any):
    """递归产出 JSON 里的所有数组，供「统一署名」结构检测使用。"""
    if isinstance(node, dict):
        for v in node.values():
            yield from _iter_arrays(v)
    elif isinstance(node, list):
        yield node
        for v in node:
            yield from _iter_arrays(v)


def check_samples() -> tuple[bool, str]:
    """① data/samples.json 恒 100 条。"""
    label = "① data/samples.json 恒 100 条"
    if not SAMPLES.is_file():
        return False, f"{label} —— 文件不存在：{SAMPLES}"
    try:
        data = json.loads(SAMPLES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return False, f"{label} —— 读取/解析失败（{type(e).__name__}）"
    if not isinstance(data, list):
        return False, f"{label} —— 顶层须为数组，实际 {type(data).__name__}"
    if len(data) != EXPECTED_SAMPLE_COUNT:
        return False, f"{label} —— 实际 {len(data)} 条，契约 {EXPECTED_SAMPLE_COUNT} 条"
    return True, f"{label}（{len(data)} 条）"


def check_rules() -> tuple[bool, str]:
    """② rules/culture_rules.json 非空且 ≥ 25 条。"""
    label = "② rules/culture_rules.json 非空且 ≥25 条"
    if not RULES.is_file():
        return False, f"{label} —— 文件不存在：{RULES}"
    try:
        data = json.loads(RULES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return False, f"{label} —— 读取/解析失败（{type(e).__name__}）"
    if not isinstance(data, list) or not data:
        return False, f"{label} —— 顶层须为非空数组"
    if len(data) < MIN_RULE_COUNT:
        return False, f"{label} —— 实际 {len(data)} 条，下限 {MIN_RULE_COUNT} 条"
    return True, f"{label}（{len(data)} 条）"


def _json_fingerprints(text: str, data: Any) -> list[str]:
    """识别单个 JSON 数据文件里另一工程的抽象结构特征，返回标签列表。"""
    tags: list[str] = []
    if isinstance(data, list) and len(data) == OTHER_LIB_ARRAY_LEN:
        tags.append(f"样本库规模恰为 {OTHER_LIB_ARRAY_LEN} 条")
    if isinstance(data, dict) and OTHER_LIB_TOP_KEY in data \
            and data.get(OTHER_LIB_EMPTY_KEY) == []:
        tags.append(f"顶层含 {OTHER_LIB_TOP_KEY} 且 {OTHER_LIB_EMPTY_KEY} 为空数组")
    if re.search(rf'"width"\s*:\s*{THUMB_W}\b', text) and \
            re.search(rf'"height"\s*:\s*{THUMB_H}\b', text):
        tags.append(f"配图尺寸声明为 {THUMB_W}×{THUMB_H}")
    for m in W_ID_RE.finditer(text):
        if int(m.group(1)) > W_ID_MIN_SEQ:
            tags.append("id 为「小写字目 + 三位」且序号超百")
            break
    sig_found = False
    for arr in _iter_arrays(data):
        if sig_found:
            break
        if len(arr) < 3 or not all(isinstance(x, dict) for x in arr):
            continue
        for key in SIGNATURE_KEYS:
            vals = [x.get(key) for x in arr
                    if isinstance(x.get(key), str) and x.get(key).strip()]
            if len(vals) >= SIGNATURE_MIN_RATIO * len(arr) and len(set(vals)) == 1:
                tags.append("大量条目共享同一署名值")
                sig_found = True
                break
    return tags


def check_fingerprints(files: list[Path]) -> tuple[bool, str]:
    """③ 全仓不出现另一工程的数据指纹（数据文件查结构，脚本文档查 id 序列）。"""
    label = "③ 全仓不出现另一工程的数据指纹"
    problems: list[tuple[str, str]] = []
    n_json = n_text = 0
    for p in files:
        text = _read_text(p)
        rel = p.relative_to(ROOT).as_posix()
        if p.suffix.lower() == ".json":
            n_json += 1
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = None
            if data is not None:
                for tag in _json_fingerprints(text, data):
                    problems.append((rel, tag))
        else:
            n_text += 1
            seq = {m.group(0) for m in W_ID_RE.finditer(text)
                   if int(m.group(1)) > W_ID_MIN_SEQ}
            if len(seq) >= ID_SEQ_MIN_DISTINCT:
                problems.append((rel, "脚本文档里出现成序列的 id 值"))
    if problems:
        detail = "; ".join(f"{r} → {t}" for r, t in problems[:8])
        return False, f"{label} —— 命中 {len(problems)} 处：{detail}"
    return True, f"{label}（扫 {n_json} 个 .json + {n_text} 个其它文本，0 命中）"


def check_final_run_literal(files: list[Path]) -> tuple[bool, str]:
    """④ 定稿 run 字面量在 .py **全文本**恰好 1 处，且命中行是 FINAL_RUN。"""
    label = "④ 定稿 run 字面量在 .py 全文本恰好 1 处"
    token = FINAL_RUN.name                 # 搜索 token 取自单一真源，不硬编码
    if not token:
        return False, f"{label} —— FINAL_RUN.name 为空"
    hits: list[tuple[str, int, int]] = []
    n_py = 0
    for p in files:
        if p.suffix.lower() != ".py":
            continue
        n_py += 1
        for i, line in enumerate(_read_text(p).splitlines(), 1):
            n = line.count(token)
            if n:
                hits.append((p.relative_to(ROOT).as_posix(), i, n))
    total = sum(h[2] for h in hits)
    if total != 1:
        return False, f"{label} —— 实际 {total} 处：{hits}"
    rel, lineno, _ = hits[0]
    if rel != RUN_SOURCE_REL:
        return False, f"{label} —— 唯一命中在 {rel}:{lineno}，应来自 {RUN_SOURCE_REL}"
    lines = _read_text(ROOT / RUN_SOURCE_REL).splitlines()
    if lineno > len(lines) or "FINAL_RUN" not in lines[lineno - 1]:
        return False, f"{label} —— 唯一命中行不是 FINAL_RUN 定义（{rel}:{lineno}）"
    return True, f"{label}（{rel}:{lineno} FINAL_RUN；扫 {n_py} 个 .py）"


def check_pkg(pkg_arg: str | None) -> tuple[bool | None, str]:
    """⑤ 可选：提交包不得出现另一工程的数据 / 云函数 / 配置结构标记。"""
    label = "⑤ 提交包不出现另一工程的数据/云函数/配置结构标记"
    if not pkg_arg:
        return None, f"{label} —— 未指定 --pkg，跳过"
    pkg = Path(pkg_arg)
    if not pkg.is_dir():
        return False, f"{label} —— 目录不存在：{pkg}"
    bad: list[tuple[str, str]] = []
    for q in sorted(pkg.rglob("*")):
        rel = q.relative_to(pkg).as_posix()
        if q.is_dir() and q.name in PKG_CLOUD_FN_DIRS:
            bad.append((rel, "云函数目录"))
        elif q.is_dir() and q.name in PKG_DATA_DIRS:
            bad.append((rel, "数据目录"))
        elif q.is_file() and q.name in PKG_CONFIG_FILES:
            bad.append((rel, "配置/数据文件"))
    if bad:
        detail = "; ".join(f"{r}({c})" for r, c in bad[:8])
        return False, f"{label} —— 命中 {len(bad)} 处：{detail}"
    return True, f"{label}（0 命中）"


def main() -> int:
    """跑完五项断言，打印 [PASS]/[FAIL]/[SKIP] 并返回退出码 0/1。"""
    ap = argparse.ArgumentParser(description="两工程合并 · 结构性断言（只读）")
    ap.add_argument("--pkg", default=None,
                    help="待检查的提交包目录（可选；不给则跳过第 ⑤ 项）")
    args = ap.parse_args()

    files = iter_scan_files()
    print("=" * 68)
    print("两工程合并 · 结构性断言（只读）")
    print("=" * 68)
    print(f"扫描根：{ROOT}")
    print(f"纳入扫描的文本文件：{len(files)} 个\n")

    checks = [
        check_samples(),
        check_rules(),
        check_fingerprints(files),
        check_final_run_literal(files),
        check_pkg(args.pkg),
    ]
    passed = failed = skipped = 0
    for ok, msg in checks:
        if ok is None:
            skipped += 1
            print(f"[SKIP] {msg}")
        elif ok:
            passed += 1
            print(f"[PASS] {msg}")
        else:
            failed += 1
            print(f"[FAIL] {msg}")
    print("-" * 68)
    if failed:
        print(f"[FAIL] {failed} 项未通过（通过 {passed} / 跳过 {skipped}）—— 修正后再提交")
        return 1
    print(f"[PASS] 全部结构断言通过（通过 {passed} / 跳过 {skipped}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
