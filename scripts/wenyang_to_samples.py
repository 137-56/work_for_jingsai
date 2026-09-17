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


def read_carriers(detail_path):
    """从详情页的「## 常见载体」段提取。
    ⚠️ 源数据有两种格式，都要支持：
        单行：  服饰、瓷器、屏风、刺绣。
        多行：  - 青铜器\\n- 瓷器\\n- 织锦
    只取单行的那版正则会漏掉多行格式（041–060 段就是列表格式）。
    """
    if not detail_path.exists():
        return []
    text = detail_path.read_text(encoding="utf-8")
    m = re.search(r"##\s*常见载体\s*\n(.*?)(?=\n##|\Z)", text, re.S)
    if not m:
        return []
    body = m.group(1)
    raw = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"^[-*+•]\s*", "", line)          # 去掉列表符号
        raw.extend([c.strip() for c in re.split(r"[、,，/]", line) if c.strip()])
    return [c.rstrip("。").strip() for c in raw if c.rstrip("。").strip()]

# 受控载体词表 —— 必须与 docs/schema.md §1.3、scripts/validate_samples.py 三处一致
# 判据：它是不是一个**具体的物 / 工艺门类**。"海报背景""游戏美术"不是物 → 不进词表。
CARRIERS = {
    "瓷器", "织锦", "刺绣", "家具", "屏风", "建筑装饰", "建筑彩画", "石雕", "木雕",
    "服饰", "壁画", "漆器", "玉器", "金银器", "剪纸", "民俗装饰",
    "青铜器", "陶器", "砖雕", "年画", "书画", "文房器物", "宗教法器", "首饰",
    "不详",
}

# 源数据的写法 → 词表里的规范词。**只做归并，不引入新的同义词。**
CARRIER_ALIAS = {
    "织物": "织锦", "织绣": "织锦", "织物边饰": "织锦", "织物花边": "织锦",
    "金属器": "金银器",
    "屏风壁画": "屏风", "寿屏": "屏风",
    "门窗装饰": "建筑装饰", "建筑纹样": "建筑装饰",
    "瓷器纹饰": "瓷器", "器物边饰": "瓷器", "器物底纹": "瓷器", "器物纹样": "瓷器",
    "服饰下摆": "服饰", "服饰边饰": "服饰",
    "家具雕饰": "家具",
    "民俗年画": "年画", "门贴": "年画",
    "佛教法器": "宗教法器", "宗教装饰": "宗教法器",
}


def split_carriers(raw):
    """把「常见载体」段的原始词分成两类：

      carriers     —— 落在受控词表内的传统载体（M3 的「载体—密度」规则要用）
      applications —— 其余词，多为现代应用场景或泛称

    为什么要分开：源数据后半段把「海报背景」「游戏美术」「网站视觉资料库」这类
    **现代应用场景**写进了「常见载体」段。它们对 M3 规则是噪声，但对报告
    （"本作品可应用于哪些场景"）有参考价值 —— 不能直接丢，要分开放。
    """
    carriers, apps = [], []
    for w in raw:
        norm = CARRIER_ALIAS.get(w, w)
        if norm in CARRIERS:
            if norm not in carriers:
                carriers.append(norm)
        elif w not in apps:
            apps.append(w)
    return (carriers or ["不详"]), apps



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
    ap.add_argument("--append", action="store_true",
                    help="增量模式：只追加新条目，已存在的原样保留（不会覆盖人工清洗过的 occasion/elements）")
    args = ap.parse_args()

    src_root = Path(args.src)
    src_json = src_root / "data" / "patterns.json"
    if not src_json.exists():
        sys.exit(f"[FAIL] 找不到数据源：{src_json}\n       用 --src 指定 Wényàng 仓库根目录")

    # ---- 保护：samples.json 非空时拒绝覆盖 ----
    # ---- 读现有数据 ----
    existing = []
    if OUT_JSON.exists():
        try:
            existing = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        except Exception:
            existing = []

    # ---- 保护（三种情形）----
    #   --append → 只追加，已有条目不动（安全，扩库用这个）
    #   --force  → 全量覆盖（危险）
    #   都没有且文件非空 → 拒绝运行
    if existing and not args.append and not args.force:
        sys.exit(f"[FAIL] {OUT_JSON.relative_to(ROOT)} 已有 {len(existing)} 条数据。\n"
                 f"       想追加请加 --append；想覆盖请加 --force（建议先 git commit 一次）")

    seen = {s["id"]: s for s in existing}
    skipped = []


    records = json.loads(src_json.read_text(encoding="utf-8"))[: args.limit]
    OUT_IMG_DIR.mkdir(parents=True, exist_ok=True)

    samples, no_carrier, missing_img = [], [], []
    for r in records:
        sid = f"WENYANG-{r['id']}"

        # ★ 增量模式：已存在的一律不动 —— 连同 phash 也不重算，
        #    因为人工清洗过的 occasion / elements 都在这条记录里，重算就是覆盖
        if args.append and sid in seen:
            skipped.append(sid)
            continue


        # 1) 图片 PNG → JPG（顺带垫白底），并当场算 phash
        src_img = src_root / r["card_image"]
        dst_img = OUT_IMG_DIR / f"{sid}.jpg"
        if src_img.exists():
            to_jpg(src_img, dst_img)
            phash = str(imagehash.phash(Image.open(dst_img)))
        else:
            missing_img.append(sid)
            phash = ""

        # 2) 载体：从详情页「常见载体」段取，再拆成
        #    carrier（受控词表内，供 M3 规则用）/ applications（应用场景，供报告引用）
        carriers, applications = split_carriers(read_carriers(src_root / r["detail_page"]))
        if not carriers or carriers == ["不详"]:
            no_carrier.append(sid)

        # 3) 组装记录（字段口径见《执行总纲》§4.1）
        samples.append({
            "id": sid,
            "name": r["name_cn"],
            "category": r["category"],
            "dynasty": "不详",
            "carrier": carriers,
            "applications": applications,
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

    # 增量模式：已有条目在前，新增条目追加在后
    merged = (existing + samples) if args.append else samples
    OUT_JSON.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")


    print(f"[OK] 写出 {len(samples)} 条 → {OUT_JSON.relative_to(ROOT)}")
    if skipped:
        print(f"[OK] 跳过已存在 {len(skipped)} 条（原样保留，未覆盖）")
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
