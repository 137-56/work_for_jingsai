# scripts/fetch_cleveland.py
"""从克利夫兰艺术博物馆 Open Access 拉取「中国 · 织物 · CC0」藏品 —— **实物佐证层**。

★★ 定位（很重要，别搞混）：
    这批数据**不进母题库** `data/samples.json`。
    母题库要的是语义（母题名 / 构成元素 / 寓意 / 载体），而克利夫兰只给
    图片 + 英文标题 + 英文描述 + 朝代。**用 LLM 编语义 = 重蹈"AI 编文化依据"的覆辙。**
    所以它单独落 `data/artifacts_cle/`，作用是三件事：
      ① 佐证：证明"这类纹样确实存在于实物上"（回应"你样本库也是 AI 图"的质疑）
      ② 素材：平面织物纹样，M4a 可从中裁纹样块
      ③ 朝代：母题库全库"不详"，这批有 culture + creation_date

★ 授权：全部 CC0 (Public Domain)。可自由使用、改编、商用，无需授权。
    署名规范见 文档/数据来源署名规范.md

★ 图片版本：
    web    ≈ 889 px   ← **默认取这个**（303 件约 250MB，可接受）
    print  ≈ 3386 px  ← 质量远高于母题库，但全拉 3.6GB，网络扛不住；
                        地址照样存进索引，将来要高清可用 --size print 补拉
    full   TIFF 61MB/件，不取

用法：
    .venv/Scripts/python.exe scripts/fetch_cleveland.py              # 拉 web 版
    .venv/Scripts/python.exe scripts/fetch_cleveland.py --size print # 拉高清版
    .venv/Scripts/python.exe scripts/fetch_cleveland.py --limit 10   # 冒烟测试

★ 可续跑：已下载的会跳过（按 id 判断）。
"""
import argparse
import io
import json
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "artifacts_cle"
IMGDIR = OUT / "images"

API = "https://openaccess-api.clevelandart.org/api/artworks/"
QUERY = "culture=China&department=Textiles&cc0=1&has_image=1"
SOURCE = "Cleveland Museum of Art (Open Access)"
LICENSE = "CC0 (Public Domain)"

# 保留的字段（有就留，没有就跳过）
KEEP = [
    "id", "accession_number", "title", "type", "technique", "culture",
    "creation_date", "creation_date_earliest", "creation_date_latest",
    "department", "description", "url", "share_license_status",
    "tombstone", "creditline", "provenance", "copyright",
    "digital_description", "fun_fact", "inscription", "style",
]

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def _get(url, raw=False, timeout=60, retries=2):
    """★ 超时别设太长：单张图 timeout=180 × retries=3 最坏会挂 9 分钟，
    实测因此出现过「看起来停滞」的假象。60×2 最坏 2 分钟，够用。"""
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            r = urllib.request.urlopen(req, timeout=timeout, context=_CTX)
            return r.read() if raw else json.load(r)
        except Exception as e:
            last = e
            time.sleep(1.2 * (i + 1))
    raise last


def fetch_list(limit=None):
    """拉全部条目（分页）。"""
    items, skip, total = [], 0, None
    page = 100
    while True:
        url = f"{API}?{QUERY}&limit={page}&skip={skip}"
        r = _get(url)
        total = r["info"]["total"]
        data = r.get("data") or []
        if not data:
            break
        items.extend(data)
        skip += len(data)
        print(f"  已取列表 {len(items)}/{total}")
        if limit and len(items) >= limit:
            items = items[:limit]
            break
        if skip >= total:
            break
        time.sleep(0.3)
    return items, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", default="web", choices=["web", "print", "full"])
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    IMGDIR.mkdir(parents=True, exist_ok=True)

    idx_path = OUT / "index.json"
    old = {}
    if idx_path.exists():
        try:
            for x in json.loads(idx_path.read_text(encoding="utf-8")):
                old[x["id"]] = x
            print(f"续跑：已有 {len(old)} 条")
        except Exception:
            old = {}

    print(f"拉取列表：{QUERY}")
    raw_items, total = fetch_list(args.limit or None)
    print(f"列表共 {len(raw_items)} 件（API 报告总数 {total}）\n")

    records, failed, skipped = [], [], 0

    def flush():
        """★ 增量落盘：进程若中途死掉（实测发生过，停在 261/303），
        已完成的元数据不至于全丢。"""
        records.sort(key=lambda r: r["id"])
        idx_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    for i, a in enumerate(raw_items, 1):
        aid = a["id"]
        fn = f"CLE-{aid}.jpg"
        fpath = IMGDIR / fn

        if aid in old and fpath.exists():
            records.append(old[aid])
            skipped += 1
            continue

        imgs = a.get("images") or {}
        pick = None
        for pref in (args.size, "web", "print"):
            v = imgs.get(pref)
            if isinstance(v, dict) and v.get("url"):
                pick = (pref, v)
                break
        if pick is None:
            failed.append({"id": aid, "reason": "无可用图片"})
            continue

        ver, meta = pick
        # ★ 续跑判断按**图片文件是否存在**（不是索引）：
        #   进程死掉时索引可能没落盘，若只看索引会把 261 张已下载的图全部重下。
        need_download = not fpath.exists()
        try:
            if need_download:
                blob = _get(meta["url"], raw=True, timeout=60)
                im = Image.open(io.BytesIO(blob)).convert("RGB")
                # 长边压到 1600，控制体积（print 版原图 3386 太大）
                if max(im.size) > 1600:
                    k = 1600 / max(im.size)
                    im = im.resize((int(im.width * k), int(im.height * k)), Image.LANCZOS)
                im.save(fpath, "JPEG", quality=90)
            else:
                im = Image.open(fpath)

            rec = {k: a.get(k) for k in KEEP if a.get(k) not in (None, "", [], {})}
            rec.update({
                "image_filename": fn,
                "image_size": list(im.size),
                "image_version": ver,
                "image_url": meta["url"],
                "image_url_print": ((imgs.get("print") or {}) or {}).get("url"),
                "image_url_full": ((imgs.get("full") or {}) or {}).get("url"),
                "source": SOURCE,
                "source_query": QUERY,
                "license": LICENSE,
                "favorite_web_url": f"https://www.clevelandart.org/art/{a.get('accession_number')}",
            })
            records.append(rec)
            tag = "复用" if not need_download else "✅"
            print(f"  [{i}/{len(raw_items)}] {tag} {a.get('accession_number'):<12} "
                  f"{str(a.get('title'))[:38]:<40} {im.size}", flush=True)
        except Exception as e:
            failed.append({"id": aid, "reason": f"{type(e).__name__}: {str(e)[:70]}"})
            print(f"  [{i}/{len(raw_items)}] ❌ {a.get('accession_number')} {type(e).__name__}",
                  flush=True)

        if i % 25 == 0:
            flush()
            print(f"  ── 已落盘 {len(records)} 条 ──", flush=True)
        time.sleep(0.1)

    flush()
    (OUT / "failed.json").write_text(json.dumps(failed, ensure_ascii=False, indent=2),
                                     encoding="utf-8")

    print(f"\n{'='*66}")
    print(f"成功 {len(records)} 件（其中续跑跳过 {skipped}）｜失败 {len(failed)} 件")
    print(f"索引 → {idx_path}")
    if records:
        wn = [r["image_size"][0] for r in records]
        print(f"图片宽度：最小 {min(wn)} / 中位 {sorted(wn)[len(wn)//2]} / 最大 {max(wn)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
