# scripts/build_kinship_graph.py
"""纹样亲缘图 —— 把「单个纹样的溯源」升级为「纹样谱系」。

★ 为什么值得做
    本作品原有的溯源是"逐元素"的：这张图的每个部件来自哪条母题。
    但母题库本身还带有一张**纹样关系网**（源数据的「关联纹样」字段，
    100 条共 524 个关联，其中本库内去重后 385 条无向边，**无孤立点**）。
    把它画出来，就能回答一个更上位的问题：
    **「这类纹样在谱系上跟谁最近？」** —— 这是元素级溯源给不出的信息。

★ 产出两张图
    ① 母题关联网络（100 节点 / 385 边）—— 按度数定大小、按社群着色
    ② 构成元素共现网络      —— 两个元素若出现在同一条母题里则连边

★ 数据完全来自 samples.json 的既有字段（related_motifs / elements），
   **不引入任何新数据、不新增标注、不做推测**。

用法：
    .venv/Scripts/python.exe scripts/build_kinship_graph.py
    .venv/Scripts/python.exe scripts/build_kinship_graph.py --top-label 30
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")                    # 无界面后端，脚本化出图
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
from matplotlib.font_manager import FontProperties, fontManager

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))          # 让 "from src.xxx import" 可用（与本项目其他脚本一致）
OUT = ROOT / "docs" / "figures"

# ---- 中文字体：matplotlib 必须显式注册，否则中文渲染成方块且不报错 ----
# 用 simhei.ttf（单体 TTF）；msyh.ttc 是字体集合，matplotlib 支持不稳。
_FONT_FILE = None
for _p in [r"C:/Windows/Fonts/simhei.ttf", r"C:/Windows/Fonts/msyh.ttc",
           r"C:/Windows/Fonts/simsun.ttc",
           "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]:
    if Path(_p).exists():
        _FONT_FILE = _p
        break
if _FONT_FILE is None:
    raise RuntimeError("找不到中文字体，中文会渲染成方块")
fontManager.addfont(_FONT_FILE)
_FP = FontProperties(fname=_FONT_FILE)
plt.rcParams["font.family"] = _FP.get_name()
plt.rcParams["axes.unicode_minus"] = False

# ---- 项目配色（与溯源卡片一致）----
PAPER = "#F7F1E6"
INK = "#2B2318"
RED = "#C8102E"
GOLD = "#D4AF37"
GREY = "#7A7264"
LINE = "#DED4C0"

# 社群配色（中式色系，循环使用）
PALETTE = ["#C8102E", "#1F5C4A", "#C88A2E", "#3B5F8A", "#7B4B7E",
           "#A8572B", "#4A7C59", "#8C3B4A", "#5B6E8C", "#9C7A3C",
           "#2E6E6A", "#A0522D"]


def load_graph():
    """读 samples.json，建两张图。返回 (母题图 G, 元素图 H, 统计 dict)。"""
    S = json.loads((ROOT / "data" / "samples.json").read_text(encoding="utf-8"))
    names = {x["name"] for x in S if x.get("name")}

    # ---- ① 母题关联网络 ----
    G = nx.Graph()
    for x in S:
        G.add_node(x["name"], elements=x.get("elements") or [],
                   carrier=x.get("carrier"), meaning=x.get("meaning"))
    raw = 0
    for x in S:
        for y in x.get("related_motifs") or []:
            if y in names and y != x["name"]:
                raw += 1
                G.add_edge(x["name"], y)      # nx.Graph 自动去重无向边

    # ---- ② 构成元素共现网络 ----
    H = nx.Graph()
    co = Counter()
    for x in S:
        els = [e for e in (x.get("elements") or []) if e]
        for e in set(els):
            H.add_node(e)
        for i in range(len(els)):
            for j in range(i + 1, len(els)):
                co[tuple(sorted([els[i], els[j]]))] += 1
    for (a, b), w in co.items():
        if a != b:
            H.add_edge(a, b, weight=w)

    stats = dict(n_motif=G.number_of_nodes(), n_edge=G.number_of_edges(),
                 raw_refs=raw,
                 n_elem=H.number_of_nodes(), n_co=H.number_of_edges())
    return G, H, stats


def draw_motif_graph(G, pos, out, top_label=28, stats_extra=None):
    """画母题关联网络。"""
    deg = dict(G.degree())
    fig, ax = plt.subplots(figsize=(18, 14), dpi=110)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)

    # 边
    nx.draw_networkx_edges(G, pos, ax=ax, edge_color=LINE, width=0.9, alpha=0.85)

    # 社群（决定颜色）；取不到就全用红色
    try:
        from networkx.algorithms.community import greedy_modularity_communities
        comms = list(greedy_modularity_communities(G))
    except Exception:
        comms = [set(G.nodes())]
    color_of = {}
    for i, c in enumerate(comms):
        for n in c:
            color_of[n] = PALETTE[i % len(PALETTE)]
    n_comm = len(comms)

    xs = [pos[n][0] for n in G.nodes()]
    ys = [pos[n][1] for n in G.nodes()]
    dmax = max(deg.values()) or 1
    sizes = [140 + 2600 * (deg[n] / dmax) ** 1.6 for n in G.nodes()]
    colors = [color_of.get(n, RED) for n in G.nodes()]
    ax.scatter(xs, ys, s=sizes, c=colors, edgecolors=PAPER, linewidths=2.0, zorder=3)

    # 只标度数最高的若干个，避免糊成一团
    hubs = sorted(deg, key=lambda n: -deg[n])[:top_label]
    for n in hubs:
        x, y = pos[n]
        # 标签按度数错开半径，度数越大越靠外，减少重叠
        r = 0.045 + 0.03 * (deg[n] / dmax)
        ax.text(x, y + r, n, ha="center", va="bottom", fontsize=15 if deg[n] >= 12 else 12,
                color=INK, fontweight="bold" if deg[n] >= 12 else "normal",
                zorder=4, fontproperties=_FP)

    ax.set_title(f"纹样亲缘图 · 母题关联网络\n"
                 f"{G.number_of_nodes()} 条母题 / {G.number_of_edges()} 条关联边 "
                 f"/ {n_comm} 个社群 / 无孤立节点",
                 fontsize=26, color=INK, pad=22, fontproperties=_FP)
    ax.axis("off")
    ax.text(0.5, -0.02, "数据来源：中国传统纹样图鉴 Wényàng「关联纹样」字段　"
                        "（本库内去重后统计，未作任何推测性补充）",
            transform=ax.transAxes, ha="center", fontsize=14, color=GREY,
            fontproperties=_FP)
    fig.tight_layout()
    fig.savefig(out, facecolor=PAPER, bbox_inches="tight")
    plt.close(fig)
    return n_comm


def draw_element_graph(H, out, min_w=2, min_deg=3, top_label=40):
    """画构成元素共现网络（只保留共现≥min_w、度数≥min_deg 的部分，否则太密）。"""
    H2 = nx.Graph()
    for a, b, d in H.edges(data=True):
        if d.get("weight", 1) >= min_w:
            H2.add_edge(a, b, weight=d["weight"])
    H2.remove_nodes_from([n for n in list(H2) if H2.degree(n) < min_deg])
    H2.remove_nodes_from(list(nx.isolates(H2)))
    if H2.number_of_nodes() == 0:
        print("  ⚠️ 元素共现网络在阈值下为空，跳过")
        return 0

    pos = nx.spring_layout(H2, seed=42, k=0.9, iterations=400)
    deg = dict(H2.degree())
    fig, ax = plt.subplots(figsize=(17, 13), dpi=110)
    fig.patch.set_facecolor(PAPER); ax.set_facecolor(PAPER)

    ws = [H2[a][b]["weight"] for a, b in H2.edges()]
    wmax = max(ws) if ws else 1
    nx.draw_networkx_edges(H2, pos, ax=ax, edge_color=LINE,
                           width=[0.7 + 3.0 * (w / wmax) for w in ws], alpha=0.85)
    xs = [pos[n][0] for n in H2]; ys = [pos[n][1] for n in H2]
    dmax = max(deg.values()) or 1
    ax.scatter(xs, ys, s=[120 + 1500 * (deg[n] / dmax) ** 1.5 for n in H2],
               c=[GOLD if deg[n] >= 4 else "#1F5C4A" for n in H2],
               edgecolors=INK, linewidths=1.4, zorder=3)
    for n in sorted(deg, key=lambda n: -deg[n])[:top_label]:
        x, y = pos[n]
        ax.text(x, y + 0.035, n, ha="center", va="bottom", fontsize=12.5, color=INK,
                zorder=4, fontproperties=_FP)
    ax.set_title(f"纹样亲缘图 · 构成元素共现网络\n"
                 f"{H2.number_of_nodes()} 个元素 / {H2.number_of_edges()} 条共现关系 "
                 f"（共现 ≥{min_w} 次）",
                 fontsize=26, color=INK, pad=22, fontproperties=_FP)
    ax.axis("off")
    ax.text(0.5, -0.02, "数据来源：母题库「构成元素」字段　"
                        "连边 = 两个元素出现在同一条母题中",
            transform=ax.transAxes, ha="center", fontsize=14, color=GREY,
            fontproperties=_FP)
    fig.tight_layout()
    fig.savefig(out, facecolor=PAPER, bbox_inches="tight")
    plt.close(fig)
    return H2.number_of_nodes()


def draw_family_tree(G, out, stats):
    """画「五族谱系图」—— 把母题网络的社群结构落成一张可读的族谱。

    ★ 为什么单独做这张：母题网络图适合 PPT 主视觉，
      但评委想快速看懂"谱系在哪"时，需要一张**把族群列成名单**的图。
      族名归类是**人工按成员构成元素读的**（算法只分群，不命名），此处如实标注。
    """
    from PIL import Image, ImageDraw
    from src.m6_provenance import _font, wrap_cjk, INK as PINK, RED as PRED, GOLD as PGOLD, GREY as PGREY

    comms = list(__import__("networkx").algorithms.community.greedy_modularity_communities(G))
    deg = dict(G.degree())
    comms = sorted(comms, key=lambda c: -len(c))

    # ★ 族名是人工读"成员构成"后的归类，不是算法输出 —— 图上必须写清这一点
    NAMES = ["花卉草木族", "几何锦纹族", "云水自然族", "吉祥字符族", "瑞兽神物族"]
    CC = [RED, "#1F5C4A", "#C88A2E", "#3B5F8A", "#7B4B7E"]

    N = len(comms)
    COLW, M = 340, 46
    TOP = 300
    W = M * 2 + COLW * N + 30 * (N - 1)
    img = Image.new("RGB", (W, TOP + 1500), (247, 241, 230))
    d = ImageDraw.Draw(img)
    f_t = _font(64); f_h = _font(34); f_s = _font(24); f_b = _font(26); f_f = _font(20)

    # 标题
    d.text((M, 52), "纹样谱系 · 五族图", font=f_t, fill=PINK)
    d.text((M, 140), f"{G.number_of_nodes()} 条母题 ｜ {G.number_of_edges()} 条关联边 ｜ "
                     f"{N} 族 ｜ 模块度 {stats.get('modularity')} ｜ 无孤立节点",
           font=f_h, fill=PGREY)
    d.text((M, 196), "分群由 modularity 社群检测算法得出；族名是人工按成员构成元素读出的归类。",
           font=f_s, fill=PGREY)
    d.line([M, 250, W - M, 250], fill=PGOLD, width=4)

    for i, c in enumerate(comms):
        x = M + i * (COLW + 30)
        col = CC[i % len(CC)]
        mem = sorted(c, key=lambda n: -deg[n])
        hub = mem[0]
        # 族头
        d.rectangle([x, TOP, x + COLW, TOP + 120], fill=col)
        d.text((x + 18, TOP + 14), f"{NAMES[i]}", font=_font(34), fill=(252, 249, 243))
        d.text((x + 18, TOP + 62), f"{len(c)} 条 ｜ 枢纽：{hub}", font=_font(22),
               fill=(247, 241, 230))
        # 成员（按度数排序）
        y = TOP + 150
        for n in mem:
            is_hub = n == hub
            tag = "◆ " if is_hub else "· "
            try:
                lines = wrap_cjk(tag + n, _font(26), COLW - 24, d)
            except Exception:
                lines = [tag + n]
            for ln in lines:
                d.text((x + 14, y), ln, font=_font(26),
                       fill=PINK if not is_hub else (200, 16, 46))
                y += 40
            y += 2

    # 底注
    d.line([M, TOP + 1460, W - M, TOP + 1460], fill=LINE_HEX, width=2)
    d.text((M, TOP + 1480), "数据来源：中国传统纹样图鉴 Wényàng「关联纹样」字段（本库内去重，未作推测性补充）",
           font=f_f, fill=PGREY)
    img = img.crop((0, 0, W, TOP + 1540))
    img.save(out, "PNG")


LINE_HEX = (222, 212, 192)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-label", type=int, default=28)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    print("读取 samples.json…")
    G, H, stats = load_graph()
    print(f"  母题图：{stats['n_motif']} 节点 / {stats['n_edge']} 边"
          f"（原始关联引用 {stats['raw_refs']} 次，去重后 {stats['n_edge']} 条）")
    print(f"  元素图：{stats['n_elem']} 节点 / {stats['n_co']} 条共现")
    print(f"  孤立母题：{len(list(nx.isolates(G)))} 个")

    # ★ 先把社群/模块度算出来，后面的两张图都要用
    #   （一开始写在最后，族谱图拿到了 modularity=None 的占位）
    try:
        from networkx.algorithms.community import modularity, greedy_modularity_communities
        _comms = list(greedy_modularity_communities(G))
        stats["modularity"] = round(float(modularity(G, _comms)), 3)
        stats["n_community"] = len(_comms)
    except Exception:
        stats["modularity"] = None

    print("\n计算布局（spring）…")
    pos = nx.spring_layout(G, seed=args.seed, k=0.62, iterations=600)

    print("绘制母题关联网络…")
    n_comm = draw_motif_graph(G, pos, OUT / "kinship_motif_network.png",
                              top_label=args.top_label)

    print("绘制元素共现网络…")
    n_el = draw_element_graph(H, OUT / "kinship_element_network.png")

    print("绘制五族谱系图…")
    draw_family_tree(G, OUT / "kinship_family_tree.png", stats)

    # 统计落盘（报告可直接引用）—— 补上布局相关字段
    deg = dict(G.degree())
    stats.update(isolated=len(list(nx.isolates(G))),
                 max_degree_node=max(deg, key=deg.get), max_degree=max(deg.values()))
    (OUT / "kinship_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"✅ 母题网络 → {OUT/'kinship_motif_network.png'}")
    print(f"✅ 元素网络 → {OUT/'kinship_element_network.png'}")
    print(f"✅ 族谱图   → {OUT/'kinship_family_tree.png'}")
    print(f"✅ 统计     → {OUT/'kinship_stats.json'}")
    print(f"   社群数 {n_comm}｜模块度 {stats.get('modularity')}"
          f"｜最大度 {stats['max_degree_node']}({stats['max_degree']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
