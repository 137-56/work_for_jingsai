#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""check_glb_sync.py —— 校验 GLB 在三处是否同源

    $PY scripts/check_glb_sync.py                 # 自动取最新的 outputs/R*
    $PY scripts/check_glb_sync.py --dir outputs/<run-id>
    定稿 run 以 src.run_source.FINAL_RUN 为准，本文件不硬编码。

★ 为什么需要这个脚本（实测踩过）
    GLB 存在三个位置，各自被不同环节写入：

      outputs/<run>/pattern_*.glb   管线产物（**定稿基准**）
      web/glb/pattern_*.glb         入库的开发态副本（直接打开 web/viewer.html 时用）
      static/viewer/glb/*.glb       运行时副本（Streamlit iframe 实际加载这个）

    2026-10-28 实测：方盒 run=902,496B 而 web/static=1,032,852B（09-27 旧版），
    团扇 web 又是第三个版本（1,178,036B）。**页面照样打开、不报错**，
    只是"演示时转的模型"和"材料里的图"不是同一件东西 —— 静默失效。

★ 两条不变量分开断言（不能合并成一条）
    A 同源：run 的 GLB == 两份副本
    B 副本一致：web == static
    实测曾出现"A 破而 B 成立"（方盒）与"B 破而 A 成立"（团扇）各一次，
    合并成一条会漏掉其中一种。

★ 只读。不修复、不复制 —— 修复动作必须人工确认后单独执行（避免覆盖定稿）。
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORMS = ("vase", "box", "fan")
LABEL = {"vase": "梅瓶", "box": "方盒", "fan": "团扇"}


def sha12(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12]


def latest_run() -> Path | None:
    cands = sorted([p for p in (ROOT / "outputs").glob("R*") if p.is_dir()])
    return cands[-1] if cands else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=None, help="定稿 run 目录（默认取最新的 outputs/R*）")
    args = ap.parse_args()

    run_dir = Path(args.dir) if args.dir else latest_run()
    if run_dir is None or not run_dir.is_dir():
        print("[FAIL] 找不到 run 目录（outputs/R*）")
        return 1
    if not run_dir.is_absolute():
        run_dir = (ROOT / run_dir).resolve()

    places = {
        "run": run_dir,
        "web": ROOT / "web" / "glb",
        "static": ROOT / "static" / "viewer" / "glb",
    }

    print(f"run 目录：{run_dir.relative_to(ROOT)}")
    print()
    print(f"{'形态':6}{'run':>15}{'web':>15}{'static':>15}   判定")
    print("-" * 62)

    bad: list[str] = []
    for kind in FORMS:
        row, missing = {}, []
        for name, d in places.items():
            p = d / f"pattern_{kind}.glb"
            if p.exists():
                row[name] = sha12(p)
            else:
                row[name] = "缺失"
                missing.append(name)

        same_src = row["run"] == row["web"] == row["static"]
        if missing:
            verdict = f"[FAIL] 缺文件：{'/'.join(missing)}"
        elif not same_src:
            verdict = "[FAIL] 三处不一致"
        else:
            verdict = "[PASS]"
        if verdict != "[PASS]":
            bad.append(f"{kind}（{LABEL[kind]}）{verdict}")

        print(f"{LABEL[kind]:6}{row['run']:>15}{row['web']:>15}{row['static']:>15}   {verdict}")

    print()
    # 两条不变量分开报，便于定位是哪一条破了
    inv_a = all(
        (run_dir / f"pattern_{k}.glb").exists()
        and (ROOT / "web" / "glb" / f"pattern_{k}.glb").exists()
        and sha12(run_dir / f"pattern_{k}.glb") == sha12(ROOT / "web" / "glb" / f"pattern_{k}.glb")
        for k in FORMS
    )
    inv_b = all(
        (ROOT / "web" / "glb" / f"pattern_{k}.glb").exists()
        and (ROOT / "static" / "viewer" / "glb" / f"pattern_{k}.glb").exists()
        and sha12(ROOT / "web" / "glb" / f"pattern_{k}.glb")
        == sha12(ROOT / "static" / "viewer" / "glb" / f"pattern_{k}.glb")
        for k in FORMS
    )
    print(f"不变量 A（run == web，同源）：      {'✅ 成立' if inv_a else '❌ 不成立'}")
    print(f"不变量 B（web == static，副本一致）：{'✅ 成立' if inv_b else '❌ 不成立'}")

    if bad:
        print()
        print("[FAIL] 三处 GLB 不同源。修复方式（**不要重新生成**，重跑会产生新 recipe_id）：")
        print("  1) 先备份：cp -p web/glb/*.glb static/viewer/glb/*.glb <备份目录>/")
        print("  2) 再字节复制：cp -p <run>/pattern_*.glb web/glb/ && cp -p <run>/pattern_*.glb static/viewer/glb/")
        return 1

    print()
    print("[PASS] 三形态三处全等")
    return 0


if __name__ == "__main__":
    sys.exit(main())
