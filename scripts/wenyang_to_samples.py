# scripts/wenyang_to_samples.py
"""把 Wényàng 的 patterns.json 转成工程的 data/samples.json，参考图转 JPG 存进 data/images/。

字段口径见《执行总纲》§4.1。这里只做「机械转换」+「能自动判定的部分」：
  - dynasty 固定 "不详"    —— 源数据没有朝代，且该图集是原创再设计，本无朝代（契约允许）
  - occasion 留空数组      —— 源数据没有，必须人工编纂（下一步）
  - elements 只做粗过滤    —— 颜色/构图/风格词先滤掉，细清仍需人工
  - phash 当场算好         —— 别留到以后再补，那时要重跑全库

用法（在工程根目录 work/ 下执行）：
    .venv/Scripts/python.exe scripts/wenyang_to_samples.py
    .venv/Scripts/python.exe scripts/wenyang_to_samples.py --limit 150
    .venv/Scripts/python.exe scripts/wenyang_to_samples.py --force    # 覆盖已有数据
"""
"""

测试用例:
cd "/d/work/work_space/DeskTop/DeskBox/竞赛/work"
git add -A && git commit -m "chore: 空脚本占位"        # 先留个回滚点
.venv/Scripts/python.exe scripts/wenyang_to_samples.py

"""
import argparse
import json
import re
import sys
from pathlib import Path

import imagehash
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent

# 默认数据源：与 work/ 同级的 Wényàng 目录
DEFAULT_SRC = ROOT.parent / "Wényàng" / "chinese-traditional-patterns-main"

OUT_JSON = ROOT / "data" / "samples.json"
OUT_IMG_DIR = ROOT / "data" / "images"

# ---- 全批一致的固定元数据 ----
SOURCE_NAME = "中国传统纹样图鉴 Wényàng"
SOURCE_URL = "https://github.com/dososo/chinese-traditional-patterns"
LICENSE = "CC BY-NC 4.0（署名 · 限非商业用途）"

# ---- 详情页里出现、但不属于「载体」的词 ----
# 「文创产品」「包装设计」是现代应用场景，不是载体，放进 carrier 会污染 M3「载体—密度」规则
CARRIER_BLACKLIST = {"文创产品", "包装设计"}

# ---- elements 粗过滤用的噪声词（颜色 / 构图 / 风格）----
ELEMENT_NOISE = [
    "墨绿", "墨色", "朱砂", "鎏金", "青绿", "淡彩", "配色", "白描", "线条",
    "对称", "构图", "留白", "团花", "几何化", "石刻感", "玉雕感", "青铜",
    "威严", "祥瑞", "唐风", "感", "排列", "粗线", "细线",
]


def read_carriers(detail_path: Path):
    """从详情页的「## 常见载体」段提取载体列表。
    详情页形如：
        ## 常见载体
        瓷器、织锦、刺绣、家具、屏风、建筑装饰、包装设计、文创产品。
    """
    if not detail_path.exists():
        return []
    text = detail_path.read_text(encoding="utf-8")
    m = re.search(r"##\s*常见载体\s*\n+(.+)", text)
    if not m:
        return []
    raw = [c.strip() for c in re.split(r"[、,，]", m.group(1).strip().rstrip("。")) if c.strip()]
    return [c for c in raw if c not in CARRIER_BLACKLIST]


def clean_elements(keywords):
    """粗过滤 visual_keywords 里明显的颜色/构图/风格词。**细清仍需人工，别省。**"""
    return [k for k in (keywords or []) if not any(n in k for n in ELEMENT_NOISE)]


def to_jpg(src: Path, dst: Path, quality: int = 88):
    """PNG → JPG。
    坑：PNG 可能带透明通道，直接 convert("RGB") 会把透明区域变成黑色。
    正确做法是先转 RGBA，垫一层白底，用 alpha 通道当遮罩贴上去。"""
    img = Image.open(src)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "JPEG", quality=quality)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30, help="转换多少条（默认 30）")
    ap.add_argument("--src", default=str(DEFAULT_SRC), help="Wényàng 仓库根目录")
    ap.add_argument("--force", action="store_true", help="允许覆盖已有的 samples.json")
    args = ap.parse_args()

    src_root = Path(args.src)
    src_json = src_root / "data" / "patterns.json"
    if not src_json.exists():
        sys.exit(f"[FAIL] 找不到数据源：{src_json}\n       用 --src 指定 Wényàng 仓库根目录")

    # ---- 保护：samples.json 非空时拒绝覆盖 ----
    if OUT_JSON.exists():
        try:
            existing = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        except Exception:
            existing = []
        if existing and not args.force:
            sys.exit(f"[FAIL] {OUT_JSON.relative_to(ROOT)} 已有 {len(existing)} 条数据。\n"
                     f"       确认要覆盖请加 --force（建议先 git commit，出问题能回滚）")

    records = json.loads(src_json.read_text(encoding="utf-8"))[: args.limit]
    OUT_IMG_DIR.mkdir(parents=True, exist_ok=True)

    samples, no_carrier, missing_img = [], [], []
    for r in records:
        sid = f"WENYANG-{r['id']}"

        # 1) 图片 PNG → JPG（顺带垫白底），并当场算 phash
        src_img = src_root / r["card_image"]
        dst_img = OUT_IMG_DIR / f"{sid}.jpg"
        if src_img.exists():
            to_jpg(src_img, dst_img)
            phash = str(imagehash.phash(Image.open(dst_img)))
        else:
            missing_img.append(sid)
            phash = ""

        # 2) 载体：从详情页「常见载体」段取
        carriers = read_carriers(src_root / r["detail_page"])
        if not carriers:
            no_carrier.append(sid)

        # 3) 组装记录（字段口径见《执行总纲》§4.1）
        samples.append({
            "id": sid,
            "name": r["name_cn"],
            "category": r["category"],
            "dynasty": "不详",
            "carrier": carriers,
            "meaning": f"{r.get('summary', '')}寓意{r['meaning']}。",
            "occasion": [],                       # ← 下一步人工填
            "elements": clean_elements(r.get("visual_keywords")),
            "source": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "license": LICENSE,
            "image_path": f"data/images/{sid}.jpg",
            "phash": phash,
            "clip_vec_index": None,
        })

    OUT_JSON.write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] 写出 {len(samples)} 条 → {OUT_JSON.relative_to(ROOT)}")
    print(f"[OK] 图片 {len(samples) - len(missing_img)} 张 → {OUT_IMG_DIR.relative_to(ROOT)}")
    print("\n=== 仍需人工处理 ===")
    print(f"  occasion : 全部 {len(samples)} 条（现在是空数组）")
    print(f"  elements : 全部 {len(samples)} 条（只做了粗过滤，要逐条复核）")
    if missing_img:
        print(f"  [警告] 图片缺失 {len(missing_img)} 条：{', '.join(missing_img)}")
    if no_carrier:
        print(f"  [警告] 详情页没解析出载体 {len(no_carrier)} 条：{', '.join(no_carrier)}")
    if not missing_img and not no_carrier:
        print("  （图片与载体均无缺失）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
