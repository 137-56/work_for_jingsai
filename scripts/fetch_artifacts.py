# scripts/fetch_artifacts.py
"""抓取 The Met 公版中国文物，作为纹样母题的「真实文物佐证」。

⚠️ 只写 data/artifacts/，**完全不碰 samples.json**（100 条纹样母题库保持不动）。

为什么是 The Met 而不是故宫：
    故宫数字文物库的授权规则**明确禁止**「利用画面进行 AI 创作」与「数字展示（小程序/APP/H5）」
    ——见《故宫博物院数字影像资源授权申请说明》「暂不提供授权」第 3、4 条。本课题两条全中。
    The Met 开放数据是 CC0：不限商用与非商用、免费、无需申请。二者的合规性不是一个量级。

为什么默认只收「器物」不收「书画」：
    本数据集的用途是**给纹样母题提供现实佐证**（"这个纹样在真实器物上长什么样"）。
    一件瓷器/织锦的表面承载纹样，一份手卷/册页是绘画作品，佐证力弱。
    → 默认剔除书画类（PAINTING_LIKE），可用 --include-paintings 收回。

数据口径（与 samples.json 的区别）：
    这里是**器物级**记录，**没有** occasion / elements / meaning 这些纹样知识字段。
    它**不参与 M2 检索**，只作为母题的现实佐证挂在溯源卡片上。

The Met API 的两个实测坑（别重复踩）：
    1. `q` 只匹配很窄的字段 —— 单个词普遍只命中 5–11 条，'blue and white' 是唯一高产词（1500+）
    2. 文档声称支持 `title:` / `tags:` 字段限定，**实测未生效**（`title:jar` 会返回画册和手卷）
    → 所以策略是「多词累加收集候选 + 逐件核验过滤」，不能靠一次精准检索

用法（在工程根目录 work/ 下执行）：
    .venv/Scripts/python.exe scripts/fetch_artifacts.py --dry-run        # 只探候选，不写盘不下图
    .venv/Scripts/python.exe scripts/fetch_artifacts.py --limit 60       # 抓 60 件器物
    .venv/Scripts/python.exe scripts/fetch_artifacts.py --limit 100      # 断点续抓（自动跳过已有）

产出：
    data/artifacts/index.json         索引：馆藏编号 / 朝代 / 材质 / 公版声明 / 来源链接
    data/artifacts/images/MET-*.jpg   文物图（web-large 档，约 600–1200px）
    data/artifacts/failed.json        抓取失败的 ID，便于复查，不静默吞掉
"""
import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE = "https://collectionapi.metmuseum.org/public/collection/v1"
DEPT_ASIAN_ART = 6                 # 经 /departments 实测确认
UA = "WenyangYouyuan/1.0 (academic competition)"
SLEEP = 0.05                       # 官方限速 80 req/s，这里压到 ~20 req/s

OUT_DIR = ROOT / "data" / "artifacts"
IMAGES_DIR = OUT_DIR / "images"
INDEX = OUT_DIR / "index.json"
FAILED = OUT_DIR / "failed.json"
RAW_CANDIDATES = OUT_DIR / "candidates.json"

# 高产词：中国青花瓷器，是唯一能给出上千候选的检索词
CORE_TERM = "blue and white"

# 其余检索词：单词命中数少（5–11），靠累加扩量
TERMS = [
    "dragon", "lotus", "peony", "chrysanthemum", "cloud", "waves", "phoenix",
    "crane", "butterfly", "bat", "deer", "fish", "bamboo", "plum", "pine",
    "vase", "bowl", "dish", "jar", "silk", "embroidery", "lacquer", "jade",
    "dragon robe", "porcelain", "celadon", "geometric", "textile", "floral scroll",
]

# 书画类：绘画/书法/拓本类载体，对「纹样佐证」价值低 → 默认剔除
PAINTING_LIKE = [
    "album", "handscroll", "hanging scroll", "scroll", "painting", "calligraphy",
    "thangka", "manuscript", "print", "rubbing", "fan", "sutra", "book",
]

# 组间权重（加权轮转）：青花 3 : 母题词 2 : 广度抽样 1
W_CORE, W_TERMS, W_DEPT = 3, 2, 1


def log(msg):
    print(msg, flush=True)


def get_json(url, tries=3, timeout=30):
    """取 JSON。404 返回 None（The Met 有已下架对象，属正常，不是错误）。"""
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if i == tries - 1:
                return None
            time.sleep(1)
        except Exception:
            if i == tries - 1:
                return None
            time.sleep(1)
    return None


def search_ids(term):
    q = urllib.parse.quote(term)
    d = get_json(f"{BASE}/search?q={q}&departmentId={DEPT_ASIAN_ART}&hasImages=true")
    return list((d or {}).get("objectIDs") or [])


def interleave(groups):
    """加权轮转合并多来源，避免前 N 个候选被单一来源占满。"""
    out, seen = [], set()
    idx = [0] * len(groups)
    while True:
        consumed = False
        for gi, (_tag, ids, weight) in enumerate(groups):
            for _ in range(weight):
                if idx[gi] < len(ids):
                    oid = ids[idx[gi]]
                    idx[gi] += 1
                    consumed = True
                    if oid not in seen:
                        seen.add(oid)
                        out.append((oid, _tag))
        if not consumed:
            break
    return out


def collect_candidates(dept_cap, seed):
    rng = random.Random(seed)
    groups = []

    core = search_ids(CORE_TERM)
    rng.shuffle(core)
    if core:
        groups.append((f"q:{CORE_TERM}", core, W_CORE))
    time.sleep(SLEEP)

    term_ids = []
    terms = TERMS[:]
    rng.shuffle(terms)
    for t in terms:
        term_ids.extend(search_ids(t))
        time.sleep(SLEEP)
    rng.shuffle(term_ids)
    if term_ids:
        groups.append(("q:motifs", term_ids, W_TERMS))

    dept = list((get_json(f"{BASE}/objects?departmentIds={DEPT_ASIAN_ART}") or {}).get("objectIDs") or [])
    rng.shuffle(dept)
    log(f"  Asian Art 全部对象 {len(dept)} 个，取样 {min(dept_cap, len(dept))} 个作广度来源")
    if dept:
        groups.append(("dept-sample", dept[:dept_cap], W_DEPT))

    out = interleave(groups)
    for tag, ids, _w in groups:
        log(f"    来源 {tag:18s} {len(ids)} 个")
    log(f"  候选去重后 {len(out)} 个")
    return out


def kind_of(object_name):
    n = (object_name or "").lower()
    return "painting" if any(k in n for k in PAINTING_LIKE) else "object"


def year_label(y):
    """The Met 用负数表示公元前。"""
    return f"公元前 {abs(int(y))}" if int(y) < 0 else str(int(y))


def date_str(obj):
    """取年代。The Met 有约一成的记录 objectDate 为空（实测 7/60），
    此时用 objectBeginDate / objectEndDate 合成，别让字段空着。"""
    s = (obj.get("objectDate") or "").strip()
    if s:
        return s
    b, e = obj.get("objectBeginDate"), obj.get("objectEndDate")
    if b is None and e is None:
        return ""
    if b is None:
        return year_label(e)
    if e is None:
        return year_label(b)
    return year_label(b) if int(b) == int(e) else f"{year_label(b)}–{year_label(e)}"


def check(obj):
    """返回 (是否合格, 不合格原因)"""
    if not obj:
        return False, "请求失败或已下架"
    if not obj.get("isPublicDomain"):
        return False, "非公版"
    if not obj.get("primaryImage"):
        return False, "无图"
    blob = f"{obj.get('culture') or ''} {obj.get('country') or ''}"
    if "China" not in blob:
        return False, "非中国"
    return True, ""


def to_record(obj, tag):
    oid = obj["objectID"]
    oname = obj.get("objectName") or ""
    return {
        "id": f"MET-{oid}",
        "object_id": oid,
        "kind": kind_of(oname),
        "source": "The Metropolitan Museum of Art",
        "source_url": obj.get("objectURL") or f"https://www.metmuseum.org/art/collection/search/{oid}",
        "license": "CC0 (Public Domain)",
        "accession_number": obj.get("accessionNumber") or "",
        "title": obj.get("title") or "",
        "object_name": oname,
        "culture": obj.get("culture") or "",
        "dynasty": obj.get("dynasty") or "",
        "period": obj.get("period") or "",
        "object_date": date_str(obj),
        "medium": obj.get("medium") or "",
        "department": obj.get("department") or "",
        "credit_line": obj.get("creditLine") or "",
        "repository": obj.get("repository") or "",
        "tags": [t.get("term") for t in (obj.get("tags") or []) if t.get("term")],
        "image_url": obj.get("primaryImageSmall") or obj.get("primaryImage") or "",
        "image_hires_url": obj.get("primaryImage") or "",
        "image_path": f"data/artifacts/images/MET-{oid}.jpg",
        "source_query": tag,
    }


def download_image(url, dest):
    if dest.exists() and dest.stat().st_size > 0:
        return True
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        if not data:
            return False
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(dest)                 # 原子落盘：中途失败不会留半个文件
        return True
    except Exception:
        return False


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60, help="目标【器物类】条数（默认 60）")
    ap.add_argument("--max-fetch", type=int, default=2000, help="详情请求数上限（默认 2000）")
    ap.add_argument("--dept-cap", type=int, default=600, help="广度来源取样上限")
    ap.add_argument("--max-paintings", type=int, default=0, help="允许保留的书画条数（默认 0）")
    ap.add_argument("--seed", type=int, default=20260918)
    ap.add_argument("--dry-run", action="store_true", help="只探候选，不写盘、不下图")
    ap.add_argument("--repair", action="store_true",
                    help="只补已有记录里缺失的 object_date（用 begin/end 年份合成），不新增抓取")
    ap.add_argument("--redo", action="store_true", help="忽略已有 index.json，从头抓")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    existing = []
    if INDEX.exists() and not args.redo:
        try:
            existing = json.loads(INDEX.read_text(encoding="utf-8"))
            existing = [r for r in existing if isinstance(r, dict) and r.get("id")]
        except Exception as e:
            log(f"[WARN] 已有 index.json 读不动（{e}），当作空处理")
            existing = []
    have = {r["id"] for r in existing}
    n_obj_have = sum(1 for r in existing if r.get("kind") != "painting")
    log(f"[1/4] 已有 {len(existing)} 条（器物 {n_obj_have}）")

    if args.repair:
        todo = [r for r in existing if not r.get("object_date")]
        if not todo:
            log("[OK] 没有缺 object_date 的记录，无需修补")
            return 0
        log(f"[repair] 需补年代 {len(todo)} 条")
        n_ok = 0
        for r in todo:
            obj = get_json(f"{BASE}/objects/{r['object_id']}")
            time.sleep(SLEEP)
            if not obj:
                log(f"    {r['id']} 取不到，跳过")
                continue
            ds = date_str(obj)
            if ds:
                r["object_date"] = ds
                n_ok += 1
                log(f"    {r['id']}  →  {ds}")
            else:
                log(f"    {r['id']}  该记录确实没有年代信息（源数据缺失）")
        write_json(INDEX, existing)
        log(f"[OK] 补上 {n_ok} 条，index.json 已更新")
        return 0

    if n_obj_have >= args.limit and not args.redo:
        log(f"[OK] 器物类已有 {n_obj_have} ≥ 目标 {args.limit}，无需抓取")
        return 0

    log("[2/4] 收集候选…")
    cands = collect_candidates(args.dept_cap, args.seed)
    if args.dry_run:
        write_json(RAW_CANDIDATES, [{"object_id": o, "source_query": t} for o, t in cands])
        log(f"[dry-run] 候选已落 {RAW_CANDIDATES.name}，未请求任何详情")
        return 0

    log("[3/4] 逐件核验（公版 + 有图 + 中国 + 器物）…")
    results = list(existing)
    failed = []
    n_fetch = n_reject = n_img_fail = n_nonobj = 0
    n_obj = n_obj_have

    for oid, tag in cands:
        if n_obj >= args.limit or n_fetch >= args.max_fetch:
            break
        if f"MET-{oid}" in have:
            continue
        n_fetch += 1
        obj = get_json(f"{BASE}/objects/{oid}")
        time.sleep(SLEEP)
        ok, why = check(obj)
        if not ok:
            n_reject += 1
            if obj is None:
                failed.append({"object_id": oid, "reason": why})
            continue

        rec = to_record(obj, tag)
        if rec["kind"] == "painting":
            n_nonobj += 1
            if sum(1 for r in results if r.get("kind") == "painting") >= args.max_paintings:
                continue

        if not download_image(rec["image_url"], IMAGES_DIR / f"MET-{oid}.jpg"):
            n_img_fail += 1
            failed.append({"object_id": oid, "reason": "图片下载失败"})
            continue

        results.append(rec)
        have.add(rec["id"])
        if rec["kind"] != "painting":
            n_obj += 1
        if n_obj % 10 == 0 and n_obj != n_obj_have:
            log(f"    …器物 {n_obj}/{args.limit}（已请求 {n_fetch}，剔除非中国/非公版 {n_reject}）")

    log("[4/4] 排序并落盘…")
    results.sort(key=lambda r: (0 if r.get("kind") != "painting" else 1))
    write_json(INDEX, results)
    write_json(FAILED, failed)

    n_p = sum(1 for r in results if r.get("kind") == "painting")
    log("")
    log("=" * 60)
    log(f"[OK] 器物类       {n_obj}  （目标 {args.limit}）")
    log(f"     书画类       {n_p}")
    log(f"     详情请求     {n_fetch}  ｜ 剔除(非中国/非公版/无图) {n_reject}  ｜ 图片失败 {n_img_fail}")
    log(f"     索引         {INDEX}")
    log(f"     图片         {IMAGES_DIR}")
    if failed:
        log(f"     失败清单     {FAILED}（{len(failed)} 条，需复查）")
    log("=" * 60)
    if n_obj < args.limit:
        log("[提示] 未达目标。加大 --max-fetch 后重跑（自动续抓，不重复下载）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
