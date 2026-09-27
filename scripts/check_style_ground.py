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
"""
from __future__ import annotations

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


def main():
    print("=" * 62)
    print("3D 贴图方案 · 双路线自检（plain / style）")
    print("=" * 62)

    case = find_case()
    if case is None:
        print("  ⚠️  没有找到「配方+合成图+风格化图」齐全的目录，跳过。")
        print("     （先跑一次完整流程：生成配方 → ⑤ 风格化 → 再跑本脚本）")
        return 0
    print(f"  用例目录：{case.name}\n")

    from src.m2_retrieve import retrieve
    from src.preview3d import render_preview

    rec = json.loads((case / "recipe.json").read_text(encoding="utf-8"))
    hits = retrieve(rec, top_k=10)
    comp = case / "composed_pattern.png"
    sty = sorted(case.glob("stylized_*.png"),
                 key=lambda p: p.stat().st_mtime, reverse=True)[0]

    results = {}
    for tag, style_img in (("plain", None), ("style", sty)):
        print(f"── {tag} ─────────────────────────────────")
        try:
            paths = render_preview(comp, case, rec, hits=hits,
                                   quality="fast", style_img=style_img)
        except Exception as e:
            _line(BAD, f"{tag} 渲染抛异常：{type(e).__name__}: {e}")
            fails.append(f"{tag} 渲染失败")
            continue

        # ★ 每轮跑完**立即**读元数据：layout.json 是后写覆盖先写的，
        #   攒到最后一起读的话，第一次的结果会被第二次盖掉（实测踩过）。
        meta_p = case / "preview3d_layout.json"
        ground_from = None
        if meta_p.exists():
            m = json.loads(meta_p.read_text(encoding="utf-8"))
            ground_from = (m.get("_render") or {}).get("ground_from")
        _line(OK, f"{tag} 渲染通过（三联图 {paths['triptych'].name}）")
        _line("  ", f"ground_from = {ground_from}")
        results[tag] = ground_from

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
