# src/m7_copyright.py
"""M7 版权风险预警：双路相似度比对（感知哈希 + CLIP 语义相似度）。

★ 为什么是"预警"而不是"判定"：
    相似度高 ≠ 侵权。侵权认定需要就独创性表达、接触可能性、实质性相似等要件依法判断，
    属法律判断。本模块只做**相似度风险分级**，并在输出中**强制携带免责声明**，
    对外一律表述为"风险预警"。

双路互补：
    结构层（phash）—— 感知哈希对缩放 / 轻微旋转 / 调色 / 压缩稳健，捕捉"近乎复刻"
    语义层（CLIP）—— 余弦相似度捕捉"构图与风格高度雷同"（像素层面已大改，phash 抓不到）

★ 输入是**任意一张图片**，不是"生成图"——
  因为 M4（组合式合成）尚未实现，且"审查任意设计稿与本库的相似度"本身更通用。
"""
import json
import sys
from functools import lru_cache
from pathlib import Path

import imagehash
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.clip_model import encode_image
from src.utils import CFG

SAMPLES = Path(CFG["paths"]["samples"])
NPZ = Path(CFG["paths"]["index"]) / "clip_vectors.npz"

DISCLAIMER = (
    "本结果为基于相似度的风险预警，不构成侵权判定。"
    "是否构成侵权须由权利人与专业机构就独创性表达、接触可能性与实质性相似等要件依法认定。"
)


def _phash(img):
    """★ 必须用与建库时**相同**的参数，否则与库内 phash 不可比。
    建库用的是 imagehash 默认值 hash_size=8 / highfreq_factor=4（见 config.yaml）。"""
    c = CFG["copyright"]
    return imagehash.phash(img,
                           hash_size=int(c.get("phash_size", 8)),
                           highfreq_factor=int(c.get("phash_highfreq", 4)))


@lru_cache(maxsize=1)
def _library():
    """返回 (samples, by_id, vecs(100,512), id_order)。向量直接读建库产物，不重算。"""
    samples = json.loads(SAMPLES.read_text(encoding="utf-8"))
    data = np.load(NPZ, allow_pickle=False)
    vecs = data["vectors"].astype("float32")
    id_order = [str(x) for x in data["id_order"]]
    return samples, {s["id"]: s for s in samples}, vecs, id_order


def _min_dist_and_max_sim(img, qvec, exclude_category=None, exclude_id=None):
    """对库内每条算 结构距离 与 语义相似度，返回各自的最值。
    exclude_category: 只与**该类之外**的库内图比较（标定负例用）
    exclude_id:       跳过指定条目"""
    _, by_id, vecs, id_order = _library()
    qh = _phash(img)
    best_d, best_d_id = 10 ** 6, None
    best_s, best_s_id = -1.0, None
    for i, sid in enumerate(id_order):
        if sid == exclude_id:
            continue
        s = by_id.get(sid)
        if not s or not s.get("phash"):
            continue
        if exclude_category is not None and s.get("category") == exclude_category:
            continue
        d = int(qh - imagehash.hex_to_hash(s["phash"]))     # phash 对象相减 = 汉明距离
        if d < best_d:
            best_d, best_d_id = d, sid
        sim = float(np.dot(qvec[0], vecs[i]))               # 两侧都已 L2 归一化 → 点积即余弦
        if sim > best_s:
            best_s, best_s_id = sim, sid
    return (best_d, best_d_id), (best_s, best_s_id)


def assess(image_path, exclude_category=None, exclude_id=None):
    """对一张图片做双路相似度审查。返回风险分级结果（含免责声明）。"""
    c = CFG["copyright"]
    ph_hi = float(c.get("phash_threshold", 6))
    ph_md = float(c.get("phash_threshold_medium", 10))
    cs_hi = float(c.get("clip_sim_threshold", 0.92))
    cs_md = float(c.get("clip_sim_threshold_medium", 0.88))

    img = Image.open(image_path).convert("RGB")
    qvec = encode_image(image_path).numpy().astype("float32")

    (d, d_id), (s, s_id) = _min_dist_and_max_sim(
        img, qvec, exclude_category=exclude_category, exclude_id=exclude_id)

    _, by_id, _, _ = _library()
    reasons = []
    if d <= ph_hi:
        reasons.append(f"结构层：与库内「{by_id[d_id]['name']}」的感知哈希距离为 {d}，"
                       f"未超过阈值 {ph_hi:g} —— 疑似近乎复刻")
    if s >= cs_hi:
        reasons.append(f"语义层：与库内「{by_id[s_id]['name']}」的 CLIP 相似度为 {s:.3f}，"
                       f"不低于阈值 {cs_hi:g} —— 构图与风格高度雷同")

    if reasons:
        level = "high"
    elif d <= ph_md or s >= cs_md:
        level = "medium"
        reasons.append(f"接近判定阈值（结构距离 {d}，语义相似度 {s:.3f}），建议人工复核")
    else:
        level = "low"
        reasons.append("未检出与本库作品显著相似的内容")

    return {
        "image": str(image_path),
        "risk_level": level,
        "phash": {"min_distance": None if d > 10 ** 5 else d,
                  "threshold_high": ph_hi, "threshold_medium": ph_md,
                  "matched_id": d_id,
                  "matched_name": by_id[d_id]["name"] if d_id else None},
        "semantic": {"max_similarity": round(s, 4) if s > -1 else None,
                     "threshold_high": cs_hi, "threshold_medium": cs_md,
                     "matched_id": s_id,
                     "matched_name": by_id[s_id]["name"] if s_id else None},
        "reasons": reasons,
        "disclaimer": DISCLAIMER,
    }


def to_markdown(r):
    """给人看的简版报告。"""
    L = [f"### 版权风险预警 · {r.get('risk_level', '').upper()}",
         f"- 受检图片：`{r.get('image', '')}`",
         f"- 结构层：最近距离 **{r['phash']['min_distance']}**"
         f"（阈值 ≤{r['phash']['threshold_high']:g}）"
         f"｜最近似：{r['phash']['matched_name']}",
         f"- 语义层：最高相似度 **{r['semantic']['max_similarity']}**"
         f"（阈值 ≥{r['semantic']['threshold_high']:g}）"
         f"｜最近似：{r['semantic']['matched_name']}",
         "", "**判定依据**"]
    L += [f"- {x}" for x in r.get("reasons", [])]
    L += ["", f"> ⚠️ {r.get('disclaimer', '')}"]
    return "\n".join(L)