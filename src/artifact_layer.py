# src/artifact_layer.py
"""实物佐证层（克利夫兰艺术博物馆 + 大都会艺术博物馆）的读取与选用。

★★ 定位 —— 这一层在生成里只干一件事：**提供织物肌理（材质层）**

    它**不参与语义检索与文化校验**，因为它没有 `name`（中文母题名）/
    `elements`（构成元素）/ `meaning`（寓意）字段。用模型去编这些字段
    等于重蹈「用 AI 生成的内容充当文化依据」的覆辙。

    所以本模块**只取它的"织物纹理"，不取它的"纹样内容"**：
    从筛过的 97 件里挑一件**主色与配方配色最接近**的，整幅低透明度叠上去，
    让合成图有真实的织物肌理感。

★★ 因此对外表述必须**分区**（与 M5 的处理原则一致）
    · 纹理层（中心母题 / 边饰 / 角花）→ 元素级可溯（母题库 Wényàng）
    · 材质层（织物肌理）             → 实物可溯（克利夫兰，CC0，附馆藏号）
    **不得混成一句"100% 可溯源"。**

数据落位：`data/artifacts_cle/`（index.json + quality.json + images/）
版权：CC0（公有领域），署名规范见 文档/数据来源署名规范.md §四
"""
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "artifacts_cle"

_LAYER_CACHE = None
_TEX_CACHE = {}


def load_layer(usable_only=True, min_score=None):
    """读实物佐证层。返回 list[dict]，每条已合并 index 与 quality 的字段。

    usable_only=True 时只返回通过内容筛选（纹理清晰）的那些（默认阈值下 97 件）。
    """
    global _LAYER_CACHE
    if _LAYER_CACHE is None:
        import json
        idx = json.loads((DATA / "index.json").read_text(encoding="utf-8"))
        qp = DATA / "quality.json"
        q = json.loads(qp.read_text(encoding="utf-8")) if qp.exists() else {}
        for a in idx:
            r = q.get(str(a["id"]))
            if r:
                a["texture_score"] = r.get("texture_score")
                a["usable_as_pattern"] = r.get("usable_as_pattern")
                a["cut_used"] = r.get("cut_used")
        _LAYER_CACHE = idx

    out = _LAYER_CACHE
    if usable_only:
        out = [a for a in out if a.get("usable_as_pattern")]
    if min_score is not None:
        out = [a for a in out if (a.get("texture_score") or -99) >= min_score]
    return out


def dominant_rgb(path, size=64):
    """取一张图的「主色」：缩到 64px、剔掉近白与近黑后的中位色。

    为什么要剔近白/近黑：博物馆图常有白色/灰色背景板与黑色衬底，
    它们不代表织物本身的颜色，留着会把主色带偏。
    """
    key = str(path)
    if key in _TEX_CACHE:
        return _TEX_CACHE[key][1]
    im = Image.open(path).convert("RGB")
    im.thumbnail((size, size), Image.LANCZOS)
    a = np.asarray(im).reshape(-1, 3).astype(np.float32)
    lum = a.mean(1)
    keep = (lum > 30) & (lum < 235)          # 剔近黑与近白
    if keep.sum() < 20:
        keep = np.ones(len(a), bool)          # 全被剔了就不过滤
    return tuple(int(v) for v in np.median(a[keep], axis=0))


def _hex_to_rgb(h):
    h = str(h or "").lstrip("#")
    if len(h) != 6:
        return None
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def pick_texture(recipe, layer=None, avoid=None):
    """按配方配色挑一件织物质感最协调的。

    ★ 选用规则（可解释、可复现）：
        计算每件的主色与配方 `palette` 各色的 RGB 距离，取**最小距离**最小的一件。
        即"颜色与配方最协调的实物织物"。
      不用随机，也不用模型打分 —— 规则简单、结果稳定、可说清。

    avoid: 已用过的 id 集合（避免同一配方多次生成取到同一件）。
    返回 (条目, 距离)；层为空时返回 (None, None)。
    """
    layer = layer if layer is not None else load_layer()
    if not layer:
        return None, None

    pal = recipe.get("palette") or {}
    targets = [c for c in (_hex_to_rgb(pal.get("primary")), _hex_to_rgb(pal.get("secondary")))
               if c]
    if not targets:                            # 配方没给配色 → 退化为取纹理分最高的
        return max(layer, key=lambda a: a.get("texture_score") or -99), None

    best, best_d = None, 1e9
    for a in layer:
        if avoid and str(a["id"]) in avoid:
            continue
        p = DATA / "images" / a["image_filename"]
        if not p.exists():
            continue
        c = np.array(dominant_rgb(p), np.float32)
        d = min(float(np.linalg.norm(c - np.array(t, np.float32))) for t in targets)
        if d < best_d:
            best, best_d = a, d
    return best, best_d


def texture_image(item, size):
    """把选中实物图读成 size×size 的纹理图（供叠加）。"""
    key = (str(item["id"]), size)
    if key not in _TEX_CACHE:
        p = DATA / "images" / item["image_filename"]
        im = Image.open(p).convert("RGB")
        # 居中裁成正方形再缩放，避免拉伸变形
        w, h = im.size
        s = min(w, h)
        im = im.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))
        _TEX_CACHE[key] = im.resize((size, size), Image.LANCZOS)
    return _TEX_CACHE[key]


def attribution(item):
    """单件标注（CC0 无义务，但我们主动标；三要素：馆藏号 + 来源馆 + 链接）。"""
    if not item:
        return ""
    return (f"Cleveland Museum of Art｜馆藏号 {item.get('accession_number')}"
            f"｜{desc_era(item)}｜CC0")
    # ★ 不用 f-string 里的括号包多行，保持可读


def desc_era(item):
    """朝代/年代的可读描述，优先取 culture 里的朝代名。"""
    import re
    s = str(item.get("culture") or "")
    m = re.search(r"([A-Z][a-z]+ dynasty)", s)
    if m:
        return m.group(1)
    return str(item.get("creation_date") or "年代不详")
