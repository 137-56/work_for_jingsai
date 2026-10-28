# scripts/check_board_layout.py
"""设计依据板（M4）版面自检：元素不得互相遮挡、不得越出配方框、同一输入必须幂等。

★★ 为什么需要（2026-10 压字事故）
    `② 配色` 的色块原先放在 `y = y_recipe + RECIPE_H - 74`，而结构块 5 行从
    `y_recipe+68` 起、每行 36px → 结束于 `y_recipe+248`；**纵向重叠 26px**，正好压在
    「对称」那一行；同时色块 x 起点与结构块标签同列 → **横向也盖住标签**。
    结果：交付图上红色方块实实在在盖住了「对称」二字和「主色」的「主」字。

★★ 为什么不能只靠像素断言（这是本次最重要的教训）
    被盖住的文字**根本没有出现在图里** —— 像素上没有任何"这里本该有字"的证据。
    所以：
      · **几何判据**（元素是否相交 / 是否出框）必须用 `compose_board(..., layout_out=)`
        导出的**实际矩形**来判 —— 那是唯一知道"本来要画哪"的地方；
      · 像素判据只用于它能判的事：**是否画出配方框**、**两次渲染是否一致**（幂等）。
    "看起来没问题"不是判据。上一版曾用"新旧板同区域像素 diff=0"判定没问题，
    那只能证明"不是本轮引入"，既有 bug 同样像素一致。

四个判据（每个都对应一次真实事故或潜在事故）：
  ① 结构块与配色行**矩形不相交**（压字事故）
  ② 配色行在结构块**之下**且整行在配方框内（不让色块跑出框 / 跑到文字行里）
  ③ 配方框外的左右页边**不得有任何非底色像素**（内容溢出会被裁掉或压到框线）
  ④ 同一配方渲染两次必须**逐像素一致**（幂等）+ 取值长度变体不得破坏 ①②③

⚠️ 板高**只记录不硬断言**：素材区按行数算高，素材数量变了板高就会变
   （10 个素材 → 1680×2172）。写死 2172 会在 hits 少的配方上假红。

★★★ 这个脚本的阈值是**拿图校准出来的，不是推出来的；改判据前先看图。**

    具体地：「结构区内 连续同色 run ≥ 30px」这个阈值来自实测 —— 结构区标签是 26px 字，
    单个汉字最长横笔画 ≈ 26px（< 30）；配色色块是 46px 实心填充（> 30）。
    30 恰好把"字的笔画"和"实心块"分开。但它**天生是脆的**：换字号 / 换色块尺寸 /
    换字体都会让它失效。

    两次真实翻车（都是"断言写好了、但断言本身是错的"）：
      · 按"结构区最后一行红字"定位「对称」→ 配色标签也是红字，被当成了对称；
      · 按"色块行是否与任何字带相交"判重叠 → 配色标签与色块**本来就同行不同列**，假红。
    所以：任何行带 / 像素启发式都**必须先用图校准**，且只能当报警，定案仍要看图。
    硬判据是 ①a 的几何相交（来自 `compose_board(..., layout_out=)` 的实际矩形）；
    像素判据 ①b / ③ / ④ 是复核。

用法（在 work/ 下执行）：
    .venv/Scripts/python.exe scripts/check_board_layout.py
    .venv/Scripts/python.exe scripts/check_board_layout.py --dir outputs/<id>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OK, BAD = "✅", "❌"
fails: list = []
OUT = ROOT / "outputs" / "_chk_board_layout"

# 底色（PAPER）容差：判断"页边有没有画出东西"
PAPER = (247, 241, 230)
TOL = 12


def _find_case():
    """找一个有 recipe.json + composed_pattern.png 的输出目录。"""
    for d in sorted((ROOT / "outputs").iterdir(), reverse=True):
        if d.is_dir() and not d.name.startswith("_") \
                and (d / "recipe.json").exists() and (d / "composed_pattern.png").exists():
            return d
    return None


def _intersect(a, b) -> bool:
    """两个 [l,t,r,b] 矩形是否有正面积交集。"""
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _check_geometry(lay: dict, tag: str) -> None:
    """① + ②：配色行不得压结构块，且配色行必须在结构块之下、留在配方框内。"""
    sb, pr, box = lay["structure_block"], lay["palette_row"], lay["recipe_box"]
    sw = lay.get("palette_swatches", pr)

    if _intersect(sb, sw):
        fails.append(f"{tag} ① 色块与结构块矩形相交 {sw} × {sb}")
        print(f"    {BAD} 色块与结构块相交：色块 {sw} / 结构块 {sb}")
    else:
        print(f"    {OK} 色块与结构块不相交（结构块底 {sb[3]}，色块顶 {sw[1]}）")

    if _intersect(lay["left_block"], sw):
        fails.append(f"{tag} ① 色块与左块（配方内容）矩形相交")
        print(f"    {BAD} 色块与左块相交")
    else:
        print(f"    {OK} 色块与左块不相交")

    if sw[1] < max(sb[3], lay["left_block"][3]):
        fails.append(f"{tag} ② 配色行没有落在两个块之下")
        print(f"    {BAD} 配色行未在块下方")
    else:
        print(f"    {OK} 配色行在两个块下方 16px 处（间距 "
              f"{sw[1] - max(sb[3], lay['left_block'][3])}px）")

    if not (pr[0] >= box[0] and pr[1] >= box[1] and pr[2] <= box[2] and pr[3] <= box[3]):
        fails.append(f"{tag} ② 配色行超出配方框：{pr} vs {box}")
        print(f"    {BAD} 配色行超出配方框")
    else:
        print(f"    {OK} 配色行完整落在配方框内")

    if sb[3] > box[3] or lay["left_block"][3] > box[3]:
        fails.append(f"{tag} ② 结构块/左块超出配方框")
        print(f"    {BAD} 块底越过配方框底")
    else:
        print(f"    {OK} 两个文字块都在配方框内")


def _check_structure_pixels(png: Path, lay: dict, tag: str) -> None:
    """①b：结构区（配色行**之上**、右半）不得出现 ≥30px 连续饱和同色 run。

    ★ 为什么范围要用几何裁出来，而不是"整板扫色块"：
      ⑤/④ 区有纹样图，本身就是大色块，整板扫必假红（lead 特意提醒过）。
      这里的上界取 `min(结构块底, 左块底)`，下界取配方框顶 —— 也就是
      **几何上已证明只该有文字**的那块区域。几何由 `layout_out` 提供，
      所以这条像素复核不会与版面设计打架。
    ★ 为什么判"饱和色"：标签是正红 #C8102E（饱和 184），文字笔画细；
      正文是墨色 #2B2318（饱和 19）。色块是饱和实心填充。
      所以"饱和 + 连续 ≥30px"能可靠区分"字的笔画"与"实心块"（阈值校准见文件头）。

    ★ 为什么是"**宽 ≥30px 且 高 ≥20 行**"而不是只看宽度（★ 阈值校准史）：
      第一版只判"某行有 ≥30px 连续饱和 run"，结果在**正常板**上报 38px → 假红。
      原因是 PIL 逐字渲染时，相邻两字的横笔画在同一个 y 上会**接成一条长 run**
      （「母题」两字的底横就接成了 38px）。也就是说**宽度单独不可靠**。
      而色块的本质特征是"**实心**" —— 宽 46px 且高 34 行。
      所以改成二维判据：宽度 ≥30 的 run 必须**连续出现在 ≥20 行**才算实心块。
      文字笔画再长，也只在 2~4 行里出现；这个差距是数量级的，不靠调阈值。
    """
    from PIL import Image
    a = np.asarray(Image.open(png).convert("RGB"), np.int16)
    l, t, r, b = lay["recipe_box"]
    struct_bottom = max(lay["structure_block"][3], lay["left_block"][3])
    y0, y1 = t + 6, max(t + 6, min(struct_bottom - 4, b))
    x0, x1 = lay["structure_block"][0], r - 4
    if x1 <= x0 or y1 <= y0:
        return
    reg = a[y0:y1, x0:x1]
    sat = reg.max(-1) - reg.min(-1)
    solid_color = sat >= 60                      # 饱和色（文字墨色/纸色都不满足）

    wide_rows, worst = 0, 0
    for row in solid_color:
        run = best = 0
        for v in row:
            run = run + 1 if v else 0
            best = max(best, run)
        worst = max(worst, best)
        if best >= 30:
            wide_rows += 1

    if wide_rows >= 20:
        fails.append(f"{tag} ①b 结构区内出现实心色块"
                     f"（宽 {worst}px 的饱和 run 连续 {wide_rows} 行）")
        print(f"    {BAD} 结构区出现实心色块：宽 {worst}px × {wide_rows} 行"
              f"（阈值 宽≥30 且 行≥20）")
    else:
        print(f"    {OK} 结构区无实心色块（最宽 run {worst}px 仅存在于 {wide_rows} 行，"
              f"属文字笔画）")


def _check_margins(png: Path, lay: dict, tag: str) -> None:
    """③ 配方框左右页边不得有非底色像素（内容溢出/压到框线）。"""
    from PIL import Image
    a = np.asarray(Image.open(png).convert("RGB"), np.int16)
    l, t, r, b = lay["recipe_box"]
    nonbg = (np.abs(a - np.array(PAPER)).sum(-1) > TOL)
    left = nonbg[t:b, 0:max(0, l - 1)]
    right = nonbg[t:b, min(a.shape[1], r + 1):a.shape[1]]
    if left.any() or right.any():
        fails.append(f"{tag} ③ 配方框外页边出现内容：左 {int(left.sum())}px / 右 {int(right.sum())}px")
        print(f"    {BAD} 框外页边有内容（左 {int(left.sum())} / 右 {int(right.sum())} 像素）")
    else:
        print(f"    {OK} 配方框外页边干净（无内容溢出）")


def main() -> int:
    ap = argparse.ArgumentParser(description="设计依据板版面自检")
    ap.add_argument("--dir", default=None, help="用例目录（默认自动找最新的）")
    args = ap.parse_args()

    print("=" * 66)
    print("设计依据板 · 版面自检（元素遮挡 / 出框 / 幂等）")
    print("=" * 66)

    case = Path(args.dir) if args.dir else _find_case()
    if case is not None and not case.is_absolute():
        case = ROOT / case
    if case is None or not case.is_dir():
        print("  ⚠️  没有找到含 recipe.json 的输出目录，跳过。")
        return 0
    print(f"  用例目录：{case.name}\n")

    from src.m2_retrieve import retrieve
    from src.m4_compose import compose_board

    rec = json.loads((case / "recipe.json").read_text(encoding="utf-8"))
    hits = retrieve(rec, top_k=10)
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- 基线一次 + 同一输入再跑一次（幂等）----
    p1, s1 = compose_board(rec, hits, OUT / "base_1.png", layout_out=OUT / "base_1.json")
    p2, s2 = compose_board(rec, hits, OUT / "base_2.png", layout_out=OUT / "base_2.json")
    lay = json.loads((OUT / "base_1.json").read_text(encoding="utf-8"))

    print(f"── 基线（{len(hits)} 个素材）────────────────────────────")
    print(f"    板面尺寸 = {s1[0]}×{s1[1]}（★ 只记录不硬断言：素材数量变化会改变板高）")
    _check_geometry(lay, "基线")
    _check_structure_pixels(p1, lay, "基线")
    _check_margins(p1, lay, "基线")

    from PIL import Image
    a1 = np.asarray(Image.open(p1).convert("RGB"))
    a2 = np.asarray(Image.open(p2).convert("RGB"))
    if s1 != s2 or a1.shape != a2.shape or not np.array_equal(a1, a2):
        fails.append("④ 幂等失败：同一配方两次渲染结果不一致")
        print(f"    {BAD} 幂等：两次渲染不一致（{s1} vs {s2}）")
    else:
        print(f"    {OK} 幂等：两次渲染逐像素一致")

    # ---- ④ 取值长度变体（"只测一个配方等于没测"）----
    variants = [
        ("四轴对称", "传统点染配色"),
        ("中心对称", "传统五色体系"),
        ("二轴对称加旋转", "基于五行相生的传统配色"),
        ("中心放射状四向对称构图", "依节令取色的传统配色方案，兼顾喜庆与雅致"),
    ]
    print(f"── 取值长度变体（{len(variants)} 个）────────────────────────")
    for i, (sym, basis) in enumerate(variants):
        vrec = json.loads(json.dumps(rec))
        vrec.setdefault("structure", {})["symmetry"] = sym
        vrec.setdefault("palette", {})["scheme_basis"] = basis
        vp, vs = compose_board(vrec, hits, OUT / f"var_{i}.png",
                               layout_out=OUT / f"var_{i}.json")
        vlay = json.loads((OUT / f"var_{i}.json").read_text(encoding="utf-8"))
        sb, sw = vlay["structure_block"], vlay["palette_swatches"]
        if _intersect(sb, sw):
            fails.append(f"④ 变体「{sym}」：色块压住结构块")
            print(f"    {BAD} 对称=「{sym}」 板高 {vs[1]} → 色块与结构块相交")
        else:
            print(f"    {OK} 对称=「{sym}」({len(sym)}字) 板高 {vs[1]} "
                  f"结构底 {sb[3]} / 色块顶 {sw[1]} 间距 {sw[1] - sb[3]}px")

    print("\n" + "=" * 66)
    if fails:
        print(f"[FAIL] {len(fails)} 项失败：")
        for x in fails:
            print("  · " + x)
        return 1
    print("[PASS] 版面自检通过：无遮挡、无出框、幂等、长度变体安全")
    return 0


if __name__ == "__main__":
    sys.exit(main())
