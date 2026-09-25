# src/m5_stylize.py
"""M5 风格增强（AI 风格化）—— 可选环节，与溯源**严格分区**。

★★ 定位（写报告必须照这个口径）：
    这一步的输出 **不可溯源**。
    扩散模型会重绘构图：实测把「蝙蝠纹 + 回纹边饰」送去风格化后，
    蝙蝠变成了鸟、回纹变成了卷草（phash 漂移 18）。
    因此：
      · 输出一律标记「AI 风格化 · 不可溯源」，并**盖在图上**
      · **不进入溯源卡片**
      · 报告与界面里必须与"组合式合成（可溯源）"明确区分，
        **不得混在一起宣称 100% 可溯源** —— 这是诚信问题

★ 两档强度（实测得出）：
    EXPLORE  0.30 → 好看，但元素会换；phash 漂移约 18  → 「风格探索」
    FAITHFUL 0.85 → 构图保住、风格化弱；phash 漂移约 6  → 「轻度渲染」

★ 参考图用 M4a 的输出：outputs/<recipe_id>/composed_pattern.png

★ 刻意**不进 pipeline**：每张图约 35 秒并消耗额度，
  若每次跑管线都调，演示几次额度就没了。所以做成独立脚本，按需调用。

用法：
    .venv/Scripts/python.exe src/m5_stylize.py outputs/<recipe_id>
    .venv/Scripts/python.exe src/m5_stylize.py outputs/<recipe_id> --strength 0.3
"""
import json
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from src.m6_provenance import _font      # 复用字体（同 B4 的坑：中文字体必须显式 truetype）

# 两档强度
EXPLORE = 0.30     # 风格探索：好看，但元素会换
FAITHFUL = 0.85    # 轻度渲染：构图保住，风格化弱

MODEL = "wanx-v1"

LABEL = "AI 风格化 · 不可溯源"
DISCLAIMER = ("本图为扩散模型重绘结果，构图与元素可能与输入不一致，"
              "不参与元素级溯源；可溯源部分见 M4a 组合纹样图与溯源卡片。")


def build_prompt(recipe):
    """从配方构造风格化提示词。"""
    st = recipe.get("structure") or {}
    it = recipe.get("intent") or {}
    pal = recipe.get("palette") or {}
    cm = (st.get("center_motif") or {}).get("name") or ""
    bd = (st.get("border") or {}).get("pattern") or ""
    return (f"{it.get('style') or '传统'}风格纹样，"
            f"中心{cm}，周边{bd}边框，"
            f"主色{pal.get('primary') or ''}，辅色{pal.get('secondary') or ''}，"
            f"平涂，无渐变，传统纹样")


def _stamp(img, recipe_id, strength, drift):
    """在底部盖一条**醒目**的标注带 —— 防止截图外传后失去上下文。"""
    W, H = img.size
    band_h = 92
    out = Image.new("RGB", (W, H + band_h), (43, 35, 24))       # 墨色底
    out.paste(img, (0, 0))
    d = ImageDraw.Draw(out)
    f1, f2 = _font(26), _font(19)

    # 左侧：醒目标注
    d.rectangle([0, H, W, H + band_h], fill=(43, 35, 24))
    d.rectangle([0, H, 8, H + band_h], fill=(200, 16, 46))       # 正红竖条
    d.text((26, H + 12), LABEL, font=f1, fill=(200, 16, 46))
    d.text((26, H + 50), f"recipe {recipe_id}｜ref_strength={strength}｜"
                         f"构图漂移 phash={drift}｜模型 {MODEL}",
           font=f2, fill=(212, 175, 55))
    d.text((26, H + 70), "可溯源部分见同目录 composed_pattern.png 与溯源卡片",
           font=f2, fill=(200, 195, 185))
    return out


def stylize(ref_img, recipe, out_path, strength=EXPLORE, recipe_id=""):
    """把 M4a 的组合纹样图做 AI 风格化。

    返回 dict（含 drift / traceability / disclaimer）；失败时返回 None（**不抛异常**）。
    """
    from dashscope import ImageSynthesis
    import imagehash

    ref_img = Path(ref_img)
    if not ref_img.exists():
        print(f"[跳过] 参考图不存在：{ref_img}")
        return None

    prompt = build_prompt(recipe)
    print(f"  提示词：{prompt[:70]}…")
    try:
        rsp = ImageSynthesis.call(model=MODEL, prompt=prompt,
                                  ref_img=str(ref_img), ref_strength=strength,
                                  ref_mode="repaint", n=1, size="1024*1024")
    except Exception as e:
        print(f"  [失败] 调用异常：{type(e).__name__}: {e}")
        return None

    if rsp.status_code != 200:
        print(f"  [失败] {rsp.code}：{str(rsp.message)[:200]}")
        return None

    url = rsp.output.results[0].url
    raw = Path(str(out_path) + ".raw.png")
    # ⚠️ 返回的 URL 24 小时过期 → 必须立刻下载
    urllib.request.urlretrieve(url, raw)

    im = Image.open(raw).convert("RGB")
    drift = int(imagehash.phash(Image.open(ref_img)) - imagehash.phash(im))
    stamped = _stamp(im, recipe_id, strength, drift)
    stamped.save(out_path, "PNG")
    raw.unlink(missing_ok=True)

    info = {"file": str(out_path), "model": MODEL, "prompt": prompt,
            "ref_strength": strength, "phash_drift": drift,
            "traceability": "none", "label": LABEL, "disclaimer": DISCLAIMER}
    print(f"  ✅ {Path(out_path).name}  漂移 phash={drift}")
    return info


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    out_dir = Path(sys.argv[1])
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    ref = out_dir / "composed_pattern.png"
    rj = out_dir / "recipe.json"
    if not ref.exists() or not rj.exists():
        print(f"[FAIL] 缺 {ref.name} 或 {rj.name} —— 先跑一次管线（M4a 会生成它）")
        return 1
    recipe = json.loads(rj.read_text(encoding="utf-8"))
    rid = recipe.get("recipe_id", out_dir.name)

    strengths = [EXPLORE, FAITHFUL]
    if "--strength" in sys.argv:
        strengths = [float(sys.argv[sys.argv.index("--strength") + 1])]

    print(f"参考图：{ref}")
    print(f"将跑 {len(strengths)} 档强度，每档约 35 秒\n")
    records = []
    for s in strengths:
        tag = "explore" if abs(s - EXPLORE) < 1e-6 else (
            "faithful" if abs(s - FAITHFUL) < 1e-6 else f"s{s}")
        print(f"--- ref_strength={s} ({tag}) ---")
        r = stylize(ref, recipe, out_dir / f"stylized_{tag}.png", s, rid)
        if r:
            r["tag"] = tag
            records.append(r)

    (out_dir / "stylize.json").write_text(
        json.dumps({"recipe_id": rid, "results": records,
                    "note": "★ 本文件描述的输出**均不可溯源**，不参与元素级溯源"},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n落盘 → {out_dir / 'stylize.json'}")
    return 0 if records else 1


if __name__ == "__main__":
    sys.exit(main())