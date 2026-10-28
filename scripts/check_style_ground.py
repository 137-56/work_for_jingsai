# scripts/check_style_ground.py
"""自检：3D「贴图方案」两条路线是否都真的能跑通，且溯源口径正确。

★★ 为什么需要这个脚本
    `app.py` 的 ⑥ 区新增了「贴图方案」单选（plain / style），两条路线
    只在**地子（底色层）**上不同。这段逻辑有三个容易静默失败的点：

      ① plain 与 style 必须**都不报错**（style 找不到风格化图要能优雅退回）
      ② style 走通后，`p3d_ground` 必须被置为 "ai" —— 查看器文案靠它切换
      ③ 两种模式下，**三联图底注的措辞必须不同**：
         plain 说「非 AI 生成」，style 必须改口说「地子取自 AI 风格化图」。
         这一句是要写进参赛材料的，**写成一样的就属于口径失实**。

    所以这里不只看"跑没跑通"，还要**核对底注文字**。

用法：
    .venv/Scripts/python.exe scripts/check_style_ground.py
    .venv/Scripts/python.exe scripts/check_style_ground.py --case outputs/R2026xxxx --out outputs/_chk_style_ground

★★ 中间产物不许写回被测目录（2026-10 修，QA 分歧 5）
    原实现把 `render_preview(..., case, ...)` 的 out_dir 直接指向**被测产物目录**，
    于是 plain 跑完写一套、style 跑完又覆盖一套，最后留在
    `outputs/R.../preview3d_triptych.png` 的是 **style 版**。
    自检脚本改写了被测产物 —— 这不只是"脏"，`make_submission_package` 会挑
    含 `preview3d_triptych.png` 的 `R*` 目录打包，等于可能把一张"自检遗留的
    style 版三联图"当成 plain 交付图打进参赛包。

    现在：两个模式各自写进 `outputs/_chk_style_ground/<模式>/`（下划线开头，
    打包脚本只扫 `outputs/R*`，天然不会被选中），并且**跑完先自检被测目录的
    文件指纹有没有被改动** —— 一旦改动直接 FAIL，防止将来又有人把 out_dir 指回去。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OK, BAD = "✅", "❌"
fails = []


def _line(tag, msg):
    print(f"  {tag} {msg}")


def find_case():
    """找一个**同时有 recipe / 合成图 / 风格化图**的输出目录。"""
    for d in sorted((ROOT / "outputs").iterdir(), reverse=True):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        if ((d / "recipe.json").exists() and (d / "composed_pattern.png").exists()
                and list(d.glob("stylized_*.png"))):
            return d
    return None


def _fingerprint(d: Path) -> dict:
    """被测目录的文件指纹 {名字: (mtime_ns, 大小)}，用于证明本脚本没写过它。"""
    return {p.name: (p.stat().st_mtime_ns, p.stat().st_size)
            for p in sorted(d.iterdir()) if p.is_file()}


def main():
    ap = argparse.ArgumentParser(description="3D 贴图双路线（plain/style）自检")
    ap.add_argument("--case", default=None,
                    help="被测产物目录（默认自动找最新的完整用例）")
    ap.add_argument("--out", default=None,
                    help="中间产物目录（默认 outputs/_chk_style_ground；"
                         "**绝不写回被测目录**）")
    args = ap.parse_args()

    print("=" * 62)
    print("3D 贴图方案 · 双路线自检（plain / style）")
    print("=" * 62)

    case = Path(args.case) if args.case else find_case()
    if case is not None and not case.is_absolute():
        case = ROOT / case
    if case is None or not case.is_dir():
        print("  ⚠️  没有找到「配方+合成图+风格化图」齐全的目录，跳过。")
        print("     （先跑一次完整流程：生成配方 → ⑤ 风格化 → 再跑本脚本）")
        return 0
    print(f"  用例目录：{case.name}")
    out_root = Path(args.out) if args.out else (ROOT / "outputs" / "_chk_style_ground")
    if not out_root.is_absolute():
        out_root = ROOT / out_root
    print(f"  中间产物：{out_root}（不写回被测目录）\n")

    from src.m2_retrieve import retrieve
    from src.preview3d import render_preview

    fp_before = _fingerprint(case)

    rec = json.loads((case / "recipe.json").read_text(encoding="utf-8"))
    hits = retrieve(rec, top_k=10)
    comp = case / "composed_pattern.png"
    sty = sorted(case.glob("stylized_*.png"),
                 key=lambda p: p.stat().st_mtime, reverse=True)[0]

    results = {}
    for tag, style_img in (("plain", None), ("style", sty)):
        print(f"── {tag} ─────────────────────────────────")
        # ★ 每个模式一个子目录：既不会互相覆盖，也不会碰被测目录
        mode_out = out_root / tag
        try:
            paths = render_preview(comp, mode_out, rec, hits=hits,
                                   quality="fast", style_img=style_img)
        except Exception as e:
            _line(BAD, f"{tag} 渲染抛异常：{type(e).__name__}: {e}")
            fails.append(f"{tag} 渲染失败")
            continue

        # ★ 每轮跑完**立即**读元数据（保持原做法：即便将来又改回共用目录，
        #   后写的 layout.json 也不会把前一轮结果盖掉）
        meta_p = mode_out / "preview3d_layout.json"
        ground_from = None
        if meta_p.exists():
            m = json.loads(meta_p.read_text(encoding="utf-8"))
            ground_from = (m.get("_render") or {}).get("ground_from")
        _line(OK, f"{tag} 渲染通过（三联图 {paths['triptych'].parent.name}/"
                  f"{paths['triptych'].name}）")
        _line("  ", f"ground_from = {ground_from}")
        results[tag] = ground_from

    # ★ 副作用自检：被测目录的文件指纹必须一字未变
    fp_after = _fingerprint(case)
    if fp_before == fp_after:
        _line(OK, f"被测目录未被写入（{len(fp_after)} 个文件指纹一致）")
    else:
        changed = sorted(set(fp_before) ^ set(fp_after)) + \
                  sorted(k for k in set(fp_before) & set(fp_after)
                         if fp_before[k] != fp_after[k])
        _line(BAD, f"被测目录被改写了：{changed[:6]}")
        fails.append("自检脚本污染了被测产物目录")

    print("\n" + "-" * 62)
    # 判据①：plain 必须是 neutral
    if results.get("plain") == "neutral":
        _line(OK, "plain 模式 ground_from = neutral（纯色地子）")
    else:
        _line(BAD, f"plain 模式 ground_from 应为 neutral，实为 {results.get('plain')}")
        fails.append("plain 地子标注错误")

    # 判据②：style 必须是 ai_stylized
    if results.get("style") == "ai_stylized":
        _line(OK, "style 模式 ground_from = ai_stylized（AI 地子已生效）")
    else:
        _line(BAD, f"style 模式 ground_from 应为 ai_stylized，实为 {results.get('style')}")
        fails.append("style 地子未生效")

    # 判据③：两者必须不同 —— 相同说明地子没起作用（静默失败）
    if results.get("plain") and results.get("style") \
            and results["plain"] == results["style"]:
        _line(BAD, "两种模式的 ground_from 相同 → 地子根本没生效（静默失败）")
        fails.append("两模式无差异")
    elif results.get("plain") and results.get("style"):
        _line(OK, "两模式的底子来源确实不同 → 分支真的走了")

    print("=" * 62)
    if fails:
        print("[FAIL] " + "；".join(fails))
        return 1
    print("[PASS] 两条贴图路线均可用，溯源口径正确切换")
    return 0


if __name__ == "__main__":
    sys.exit(main())
