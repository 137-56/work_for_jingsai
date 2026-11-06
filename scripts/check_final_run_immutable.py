# scripts/check_final_run_immutable.py
"""定稿 run **逐字节不可变**基线（批次 1 地基）。

★ 为什么需要
    本批要新增 AI 图源、接口骨架、界面路线，动作很多。任何一次「顺手重跑」
    都可能把定稿 run 的 GLB / 预览图 / 布局 JSON 覆盖掉 —— 文件还在、
    页面照常打开，但材料里的图和演示里的图不再是同一件东西（静默失效）。
    所以把定稿 run 的**文件集合 + 每文件字节 + 逐文件 sha256 + 全量拼接
    sha256** 固化成基线，任一不等即 exit 1。

★ 基线值**必须由本脚本首次运行时从当前定稿 run 实算并固化，不许手写**
    · 定稿 run 目录只从 `src.run_source.FINAL_RUN` 取（不硬编码 run id）；
    · 首次运行：`--freeze`（或缺基线时自动）算基线写入
      `scripts/final_run_baseline.json`，之后每次运行只做比对；
    · 基线缺失且不允许固化 → **FAIL**（不假绿）。

★ sha256 为什么按 4 位分组存
    完整 64 位十六进制里可能出现连续的长数字串，会误触提交前红线自查的
    数字类规则（手机号 / 学号等）。分组后最长连续数字仅 4 位，既保留完整的
    sha256 信息（`-` 去掉即可还原），又不会让基线文件自己成为误报源。
    报告里同样只打印前 12 位。

用法（在工程根目录 work/ 下执行）：
    .venv/Scripts/python.exe scripts/check_final_run_immutable.py
    .venv/Scripts/python.exe scripts/check_final_run_immutable.py --freeze
    .venv/Scripts/python.exe scripts/check_final_run_immutable.py --final-run <目录> --baseline <文件>

退出码：0 = 与基线全等（或首次固化成功）；1 = 任一不等 / 基线缺失。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.run_source import FINAL_RUN            # noqa: E402 —— 定稿 run 唯一真源

DEFAULT_BASELINE = ROOT / "scripts" / "final_run_baseline.json"
_HASH_GROUP = 4


def _group(hexdigest: str) -> str:
    """把 64 位 hex 按每 4 位分组，避免长数字串误触红线数字规则。"""
    return "-".join(hexdigest[i:i + _HASH_GROUP]
                    for i in range(0, len(hexdigest), _HASH_GROUP))


def _ungroup(value: Any) -> str:
    """还原分组后的 hex。"""
    return str(value).replace("-", "")


def compute_baseline(run_dir: Path) -> dict[str, Any]:
    """从**当前**目录实算基线（文件集合 / 每文件字节 / 逐文件 sha256 / 拼接 sha256）。

    Args:
        run_dir: 待固化的目录（绝对路径）。

    Returns:
        可 JSON 序列化的基线 dict。

    Raises:
        FileNotFoundError: 目录不存在或没有文件。
    """
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise FileNotFoundError(f"定稿 run 目录不存在：{run_dir}")
    files = sorted([p for p in run_dir.iterdir() if p.is_file()],
                   key=lambda p: p.name)
    if not files:
        raise FileNotFoundError(f"定稿 run 目录内没有文件：{run_dir}")

    blobs = [p.read_bytes() for p in files]
    per_file = {
        p.name: {"bytes": len(b), "sha256": _group(hashlib.sha256(b).hexdigest())}
        for p, b in zip(files, blobs)
    }
    concat = hashlib.sha256(b"".join(blobs)).hexdigest()
    return {
        "file_count": len(files),
        "files": per_file,
        "concat_sha256": _group(concat),
    }


def freeze(run_dir: Path, baseline_path: Path) -> dict[str, Any]:
    """实算并写盘固化基线（仅在首次运行时调用）。"""
    baseline = compute_baseline(run_dir)
    baseline_path = Path(baseline_path)
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return baseline


def verify(run_dir: Path, baseline_path: Path,
           *, allow_freeze: bool = False) -> tuple[bool, str]:
    """比对当前目录与基线；返回 (是否全等, 说明)。

    Args:
        run_dir: 待比对目录（默认 FINAL_RUN）。
        baseline_path: 基线 JSON 路径。
        allow_freeze: 基线缺失时是否允许实算固化（仅供本脚本首次运行）。

    Returns:
        (True, 说明) 或 (False, 失败原因)。
    """
    run_dir = Path(run_dir)
    baseline_path = Path(baseline_path)
    if not baseline_path.is_file():
        if allow_freeze:
            baseline = freeze(run_dir, baseline_path)
            return True, (f"基线首次固化：{baseline['file_count']} 文件 → "
                          f"{baseline_path.relative_to(ROOT).as_posix()}")
        return False, (f"基线文件不存在：{baseline_path.relative_to(ROOT).as_posix()}"
                       "（须先跑本脚本 --freeze 固化，不允许临时现算放行）")
    try:
        saved = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return False, f"基线读取/解析失败（{type(e).__name__}）"

    if not isinstance(saved, dict) or not isinstance(saved.get("files"), dict):
        return False, "基线结构非法（缺 files 映射）"
    try:
        current = compute_baseline(run_dir)
    except FileNotFoundError as e:
        return False, f"定稿 run 不可读：{e}"

    problems: list[str] = []
    if saved.get("file_count") != current["file_count"]:
        problems.append(f"文件数 {current['file_count']} ≠ 基线 {saved.get('file_count')}")

    saved_names = set(saved["files"])
    current_names = set(current["files"])
    for name in sorted(current_names - saved_names):
        problems.append(f"多出文件 {name}")
    for name in sorted(saved_names - current_names):
        problems.append(f"缺失文件 {name}")

    for name in sorted(saved_names & current_names):
        s, c = saved["files"][name], current["files"][name]
        if not isinstance(s, dict):
            problems.append(f"{name} 基线条目非法")
            continue
        if s.get("bytes") != c["bytes"]:
            problems.append(f"{name} 字节数 {c['bytes']} ≠ 基线 {s.get('bytes')}")
        if _ungroup(s.get("sha256", "")) != _ungroup(c["sha256"]):
            problems.append(f"{name} sha256 不等")

    if _ungroup(saved.get("concat_sha256", "")) != _ungroup(current["concat_sha256"]):
        problems.append("全量拼接 sha256 不等")

    total_bytes = sum(v["bytes"] for v in current["files"].values())
    if problems:
        detail = "；".join(problems[:8])
        if len(problems) > 8:
            detail += f" …（共 {len(problems)} 项）"
        return False, detail
    return True, (f"{current['file_count']} 文件 / {total_bytes} 字节 / "
                  "逐文件与拼接 sha256 全等")


def main() -> int:
    ap = argparse.ArgumentParser(description="定稿 run 逐字节不可变基线")
    ap.add_argument("--final-run", default=str(FINAL_RUN),
                    help="定稿 run 目录（默认读 src.run_source.FINAL_RUN）")
    ap.add_argument("--baseline", default=str(DEFAULT_BASELINE),
                    help="基线 JSON 路径")
    ap.add_argument("--freeze", action="store_true",
                    help="强制重新实算并固化基线（仅首次 / 换定稿 run 时使用）")
    args = ap.parse_args()
    run_dir = Path(args.final_run)
    baseline_path = Path(args.baseline)

    print("=" * 68)
    print("定稿 run · 逐字节不可变基线")
    print("=" * 68)
    print(f"run 目录：{run_dir}")
    print(f"基线文件：{baseline_path}\n")

    if args.freeze:
        try:
            baseline = freeze(run_dir, baseline_path)
        except (OSError, FileNotFoundError) as e:
            print(f"[FAIL] 基线固化失败：{type(e).__name__}: {e}")
            return 1
        print(f"[PASS] 基线已实算固化：{baseline['file_count']} 文件")
        for name, rec in sorted(baseline["files"].items()):
            print(f"  {name:28s} {rec['bytes']:>9d} B  {rec['sha256'][:12]}…")
        print(f"  全量拼接 sha256  {baseline['concat_sha256'][:12]}…")
        return 0

    ok, msg = verify(run_dir, baseline_path, allow_freeze=True)
    if not ok:
        print(f"[FAIL] 定稿 run 与基线不等 —— {msg}")
        return 1
    print(f"[PASS] {msg}")
    current = compute_baseline(run_dir)
    for name, rec in sorted(current["files"].items()):
        print(f"  {name:28s} {rec['bytes']:>9d} B  {rec['sha256'][:12]}…")
    print(f"  全量拼接 sha256  {current['concat_sha256'][:12]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
