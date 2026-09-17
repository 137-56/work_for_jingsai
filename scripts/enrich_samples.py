# scripts/enrich_samples.py
"""把 Wényàng 源数据里**还没被用上**的字段补进 samples.json。

⚠️ 只增补，**不改动** name / category / meaning / occasion / elements / phash / carrier。
   跑之前自动备份到 data/samples.json.enrich.bak。

为什么需要这个脚本：
    现用 14 个源字段里的 8 个，详情页 11 个段落里只用了 3 个（简介 / 寓意 / 常见载体）。
    实测 100/100 条都有内容、却被丢掉的段落有三个，而且都能直接用：

    1. **关联纹样** → `related_motifs`
       源数据自己标注的纹样间语义关系。价值最大的一条：
       B2 的 5 条「同族混淆」在源数据里全都有明确的关联记录
       （菱格↔方胜、连环↔锁子、祥云↔卷云、如意云↔祥云、团寿↔福寿）
       → 可直接做检索增强，也是"排序结果可解释"的硬证据

    2. **色彩建议** → `palette`
       每组「颜色 + 风格名」。M4 设计依据板现在**没有配色依据**，用上它就是有依据的。

    3. **常见载体**段的「应用场景」部分 → `applications`
       B1-1b 已拆出该字段，但当时只重跑了 031+，**前 30 条仍是空的** → 补齐到 100/100 一致

源数据的三个坑（都要处理）：
    · 段落格式不统一：关联纹样 80 条用顿号（A、B、C），20 条用列表（- A\\n- B）
    · **自指**：061 祥云纹的关联纹样里列了"祥云纹"自己 → 必须过滤，否则检索时自指
    · 结尾句号：有的段落末尾带「。」

用法（在工程根目录 work/ 下执行）：
    .venv/Scripts/python.exe scripts/enrich_samples.py --dry-run   # 只看差异，不写盘
    .venv/Scripts/python.exe scripts/enrich_samples.py             # 正式增补
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ★ 复用已有的载体解析，不重写一份 —— 两份逻辑必然漂移
from scripts.wenyang_to_samples import DEFAULT_SRC, read_carriers, split_carriers

SAMPLES = ROOT / "data" / "samples.json"
BACKUP = ROOT / "data" / "samples.json.enrich.bak"


def read_section(detail_path, section):
    """取详情页某个 `## 段落` 的正文。"""
    if not detail_path.exists():
        return ""
    text = detail_path.read_text(encoding="utf-8")
    m = re.search(r"##\s*" + re.escape(section) + r"\s*\n(.*?)(?=\n##|\Z)", text, re.S)
    return m.group(1).strip() if m else ""


def _items(body):
    """把段落正文拆成条目：兼容 `- A` 列表与 `A、B、C` 顿号两种格式。"""
    out = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"^[-*+•]\s*", "", line)
        line = line.rstrip("。").strip()
        if not line:
            continue
        for x in re.split(r"[、,，/]", line):
            x = x.strip().rstrip("。").strip()
            if x:
                out.append(x)
    return out


def parse_related(body, self_name):
    """关联纹样。**必须剔除自指** —— 源数据里 061 祥云纹把自己写进了关联列表。"""
    out = []
    for x in _items(body):
        if x == self_name:
            continue
        if x not in out:
            out.append(x)
    return out


def build_color_vocab(bodies):
    """从**格式干净**的条目里学出颜色词表，再去匹配格式脏的条目。

    为什么不能硬写正则：「色彩建议」段实测有 6 种格式 ——
        40 条  列表 3 组 + 风格名      `- 青绿 + 米白 + 浅金：清雅古典`
        25 条  列表 3 组无风格名        `- 黑白 + 梅红 + 青绿`
        10 条  列表 4 行每行一个颜色    `- 冰蓝` / `- 米白` / `- 灰青` / `- 墨线`
        10 条  列表 4 组 + 风格名
         8 条  单行 prose，分号分隔     `朱砂 + 金色：喜庆；米白 + 墨金：雅致`
         7 条  单行 prose，用「配」     `米白配墨黑表现清雅；青绿配浅金适合图录风`
    按某一种格式写的正则，必然在其余五种上出错。所以从干净格式反向学词表。
    """
    vocab = set()
    for body in bodies:
        for line in (body or "").splitlines():
            line = re.sub(r"^[-*+•]\s*", "", line.strip()).rstrip("。").strip()
            if not line:
                continue
            left = re.split(r"[：:]", line, maxsplit=1)[0]
            for p in re.split(r"[+＋]", left):
                p = p.strip()
                if 2 <= len(p) <= 5:
                    vocab.add(p)
    return vocab


def parse_palette(body, vocab):
    """色彩建议 → [{"colors": [...], "style": "清雅古典"}, ...]

    统一走「词表匹配」而不是「按分隔符切」：
    颜色词在句中的位置是确定的，按词表扫描既能拿到颜色、剩下的自然就是风格描述。
    这样 6 种格式走同一段代码，不需要 if/elif 分派。
    """
    if not body:
        return []
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    if len(lines) == 1:
        parts = [x for x in re.split(r"[；;]", lines[0]) if x.strip()]
        if len(parts) > 1:
            lines = parts

    out = []
    for line in lines:
        line = re.sub(r"^[-*+•]\s*", "", line.strip()).rstrip("。").strip()
        if not line:
            continue
        # 按词表扫出颜色词，长词优先避免「青」抢走「青绿」
        hits = []
        for c in vocab:
            start = 0
            while True:
                i = line.find(c, start)
                if i < 0:
                    break
                hits.append((i, c))
                start = i + len(c)
        hits.sort(key=lambda x: (x[0], -len(x[1])))
        picked = []
        for pos, c in hits:
            if any(p <= pos < p + len(cc) for p, cc in picked):
                continue
            picked.append((pos, c))
        picked.sort()
        colors = [c for _, c in picked]

        # 颜色剥掉后的剩余文字 = 风格描述（去掉连接词与标点）
        rest = line
        for _, c in picked:
            rest = rest.replace(c, "\u0000", 1)
        style = rest.replace("\u0000", "")
        style = re.sub(r"^[+＋、,，/\s]+", "", style)
        style = re.split(r"[：:]", style, maxsplit=1)[-1] if "：" in style or ":" in style else style
        style = re.sub(r"^[配和与及、,，/\s]+", "", style).strip().rstrip("。，；;").strip()

        if colors:
            out.append({"colors": colors, "style": style})

    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(DEFAULT_SRC), help="Wényàng 仓库根目录")
    ap.add_argument("--dry-run", action="store_true", help="只打印差异，不写盘")
    args = ap.parse_args()

    src_root = Path(args.src)
    src_json = src_root / "data" / "patterns.json"
    if not src_json.exists():
        sys.exit(f"[FAIL] 找不到数据源：{src_json}")
    if not SAMPLES.exists():
        sys.exit(f"[FAIL] 找不到 {SAMPLES}")

    src_by_id = {f"WENYANG-{r['id']}": r for r in json.loads(src_json.read_text(encoding="utf-8"))}
    samples = json.loads(SAMPLES.read_text(encoding="utf-8"))
    print(f"[1/4] 读入 {len(samples)} 条样本 / {len(src_by_id)} 条源数据")

    lib_names = {s["name"] for s in samples}

    # 先扫一遍所有「色彩建议」段，学出颜色词表（见 build_color_vocab 的说明）
    all_palette_bodies = [
        read_section(src_root / src_by_id[s["id"]]["detail_page"], "色彩建议")
        for s in samples if s["id"] in src_by_id
    ]
    vocab = build_color_vocab(all_palette_bodies)
    print(f"    颜色词表：{len(vocab)} 个（从格式干净的条目里学出）")
    print(f"    例：{'、'.join(sorted(vocab)[:14])}")

    stats = {"related": 0, "palette": 0, "apps_new": 0, "apps_changed": 0, "selfref": 0}
    in_lib_total = 0
    n_related_total = 0

    print("[2/4] 逐条增补…")
    for s in samples:
        rec = src_by_id.get(s["id"])
        if not rec:
            print(f"    [警告] {s['id']} 在源数据里找不到，跳过")
            continue
        detail = src_root / rec["detail_page"]

        # ---- 1) 关联纹样 ----
        body = read_section(detail, "关联纹样")
        related = parse_related(body, s["name"])
        if s["name"] in _items(body):
            stats["selfref"] += 1
        if related:
            s["related_motifs"] = related
            stats["related"] += 1
            n_related_total += len(related)
            in_lib_total += sum(1 for x in related if x in lib_names)

        # ---- 2) 色彩建议 ----
        pal = parse_palette(read_section(detail, "色彩建议"), vocab)
        if pal:
            s["palette"] = pal
            stats["palette"] += 1

        # ---- 3) applications 补齐（复用 B1-1b 的拆分逻辑）----
        _c, apps = split_carriers(read_carriers(detail))
        old = s.get("applications") or []
        if apps != old:
            if not old:
                stats["apps_new"] += 1
            else:
                stats["apps_changed"] += 1
            s["applications"] = apps

    # ---- 自检 ----
    print("[3/4] 自检…")
    problems = []
    for s in samples:
        if not s.get("related_motifs"):
            problems.append(f"{s['id']} 关联纹样为空")
        elif s["name"] in s["related_motifs"]:
            problems.append(f"{s['id']} 关联纹样含自身")
        if not s.get("palette"):
            problems.append(f"{s['id']} 色彩建议为空")
        for p in s.get("palette", []):
            if not p.get("colors"):
                problems.append(f"{s['id']} 色彩建议有条目缺颜色")
    if problems:
        print(f"    [警告] {len(problems)} 处：{problems[:8]}{' …' if len(problems) > 8 else ''}")
    else:
        print("    无问题")

    print("[4/4] 落盘…")
    print("")
    print("=" * 60)
    print(f"  related_motifs  {stats['related']:>3}/100 条  共 {n_related_total} 个关联")
    print(f"                  其中落在本库 100 个母题内的：{in_lib_total} 个")
    print(f"                  源数据自指的条目（已剔除）：{stats['selfref']} 条")
    print(f"  palette         {stats['palette']:>3}/100 条")
    print(f"  applications    新增 {stats['apps_new']} 条，变更 {stats['apps_changed']} 条")
    print("=" * 60)

    if args.dry_run:
        print("[dry-run] 未写盘")
        return 0

    shutil.copy2(SAMPLES, BACKUP)
    tmp = SAMPLES.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SAMPLES)
    print(f"[OK] 已写回 {SAMPLES.relative_to(ROOT)}（备份 {BACKUP.name}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
