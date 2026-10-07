# scripts/make_arch_diagrams.py
"""生成技术报告配图：系统架构图 / 端到端流程图 / 三种溯源层次图。

★ 为什么单独写这个脚本（而不是手画）
    架构图与代码会一起演进。手画的图改了代码就失真，且没人记得改。
    脚本化后：改代码 → 重跑本脚本 → 图自动跟上。

★ 数据流以 src/pipeline.py 为准（画图前先读它，不凭印象）：
    run():  M1 parse_intent → M2 retrieve → M3 validate → 实物佐证层 → M6 build_card
    save_all(): M6 出图 → M4 compose_board → M4a compose_pattern
    M5（风格化）与 3D 由界面单独触发；M7、纹样谱系是独立入口。

用法：
    .venv/Scripts/python.exe scripts/make_arch_diagrams.py
    # 输出到 docs/figures/arch_*.png
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties, fontManager
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "figures"

# ---- 中文字体：matplotlib 必须显式注册，否则中文渲染成方块且不报错 ----
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

# ---- 项目配色（与溯源卡片 / 亲缘图一致）----
PAPER = "#F7F1E6"
INK = "#2B2318"
RED = "#C8102E"
GOLD = "#D4AF37"
GREY = "#7A7264"
LINE = "#DED4C0"
GREEN = "#1F5C4A"
BLUE = "#3B5F8A"
OCHRE = "#C88A2E"
PURPLE = "#7B4B7E"


# ------------------------------------------------------------------ 绘图原语
def box(ax, x, y, w, h, lines, fc, tc="#FCF9F3", fs=13, bold_first=True,
        ec=None, lw=1.6, radius=1.1, zorder=2, alpha=1.0):
    """圆角框。lines 为多行文字（第一行可视作标题，加粗略大）。"""
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        linewidth=lw, facecolor=fc, edgecolor=ec or fc,
        zorder=zorder, alpha=alpha))
    n = len(lines)
    if n == 0:
        return
    # 多行整体垂直居中；行距按框高与行数自适应
    lh = min(fs * 0.185, h / (n + 1) * 0.95)
    y0 = y + h / 2 + (n - 1) * lh / 2
    for i, ln in enumerate(lines):
        if i == 0 and bold_first and n > 1:
            ax.text(x + w / 2, y0 - i * lh, ln, ha="center", va="center",
                    fontsize=fs, color=tc, fontweight="bold", zorder=zorder + 1)
        else:
            ax.text(x + w / 2, y0 - i * lh, ln, ha="center", va="center",
                    fontsize=fs * (0.84 if i > 0 else 1.0), color=tc,
                    zorder=zorder + 1, alpha=0.95)


def arrow(ax, x1, y1, x2, y2, color=GREY, lw=2.0, style="-|>", ls="-",
          ms=16, zorder=1, connect=None):
    ax.add_patch(FancyArrowPatch(
        (x1, y1), (x2, y2), arrowstyle=style, mutation_scale=ms,
        linewidth=lw, color=color, zorder=zorder, linestyle=ls,
        shrinkA=0, shrinkB=0, connectionstyle=connect))


def label(ax, x, y, s, fs=12, color=GREY, ha="center", va="center",
          bold=False, zorder=6, rot=0, alpha=1.0):
    ax.text(x, y, s, ha=ha, va=va, fontsize=fs, color=color, zorder=zorder,
            fontweight="bold" if bold else "normal", rotation=rot, alpha=alpha)


def canvas(figsize):
    fig, ax = plt.subplots(figsize=figsize, dpi=150)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    return fig, ax


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    fig.tight_layout(pad=0.6)
    fig.savefig(p, facecolor=PAPER, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✅ {p}  ({p.stat().st_size / 1024:.0f} KB)")
    return p


# ================================================================ 图 1 架构
def fig_architecture():
    fig, ax = canvas((16.5, 10.2))

    label(ax, 4, 96.6, "纹初迹现 · 系统架构", fs=27, color=INK, ha="left", bold=True)
    label(ax, 4, 92.6, "七模块可溯源生成管线 ｜ 两层数据架构 ｜ 三种溯源层次",
          fs=13.5, color=GREY, ha="left")
    ax.plot([4, 96], [90.2, 90.2], color=GOLD, lw=3)

    # ---------- 交互层 ----------
    label(ax, 4, 86.4, "交互层", fs=13, color=GREY, ha="left", bold=True)
    tabs = [
        ("生成与溯源", "元素级 · 这张图的部件来自哪条母题", RED),
        ("版权相似度审查", "风险级 · 与本库是否雷同", BLUE),
        ("纹样谱系", "谱系级 · 这类纹样跟谁最近", GREEN),
    ]
    tw, gap = 29.0, 2.5
    tx = 4
    for name, sub, col in tabs:
        box(ax, tx, 76.6, tw, 8.4, [name, sub], col, fs=13)
        tx += tw + gap

    # ---------- 生成管线层 ----------
    label(ax, 4, 72.2, "生成管线（七模块）", fs=13, color=GREY, ha="left", bold=True)

    mods = [
        ("M1", "意图解析", "一句话 → 配方", RED),
        ("M2", "元素检索", "CLIP + faiss", RED),
        ("M3", "文化校验", "25 条规则", RED),
        ("M4", "设计依据板", "素材 → 板", OCHRE),
        ("M4a", "组合纹样合成", "真合成图案", OCHRE),
        ("M5", "AI 风格化", "可选 · 不可溯", PURPLE),
        ("M6", "溯源卡片", "元素级出处", RED),
        ("M7", "版权预警", "双路相似度", BLUE),
    ]
    mw, mg = 10.85, 1.35
    mx = 1.5
    for tag, name, sub, col in mods:
        box(ax, mx, 55.6, mw, 13.6, [tag, name, sub], col, fs=11.5)
        mx += mw + mg

    # 主链路箭头（M1→M2→M3→M4→M4a→M6）
    order = [0, 1, 2, 3, 4, 6]
    for a, b in zip(order, order[1:]):
        x1 = 1.5 + a * (mw + mg) + mw
        x2 = 1.5 + b * (mw + mg)
        if b == a + 1:
            arrow(ax, x1 + 0.3, 62.4, x2 - 0.3, 62.4, color=RED, lw=2.2)
        else:
            # 跨过 M5，走上方的绕行线
            xm = (x1 + x2) / 2
            ax.plot([x1 + 0.3, x1 + 0.3, x2 - 0.3, x2 - 0.3],
                    [62.4, 71.0, 71.0, 62.4], color=RED, lw=1.6,
                    linestyle=(0, (5, 3)), zorder=1)
            arrow(ax, x2 - 0.4, 71.0, x2 - 0.4, 62.6, color=RED, lw=1.6,
                  ls=(0, (5, 3)))

    label(ax, 50, 73.4, "主链路", fs=11, color=RED)
    label(ax, 84.0, 51.4, "▲ M5 可选、M7 独立入口（不参与生成主链路）",
          fs=10.5, color=GREY, ha="center")

    # ---------- 产出层 ----------
    label(ax, 4, 47.2, "产出", fs=13, color=GREY, ha="left", bold=True)
    outs = ["纹样设计图", "元素级溯源卡片", "3D 器物形态（GLB）", "版权风险报告"]
    ow, og = 22.0, 2.6
    ox = 4
    for o in outs:
        box(ax, ox, 37.6, ow, 7.4, [o], GOLD, tc=INK, fs=12.5, bold_first=False)
        ox += ow + og

    # ---------- 数据层 ----------
    label(ax, 4, 33.4, "数据层（两层，口径不可混称）", fs=13, color=GREY,
          ha="left", bold=True)
    # ★ 不用 ✅/❌ —— SimHei 无这两个字形，会渲染成方块（用 ★/◇ 代替）
    box(ax, 4, 15.0, 44.5, 15.6,
        ["语义层 · 纹样母题库", "Wényàng  100 条  CC BY-NC 4.0",
         "M2 检索依据 / M3 校验依据", "★ 参与元素级溯源"],
        GREEN, fs=13)
    box(ax, 51.5, 15.0, 44.5, 15.6,
        ["实物佐证层 · 文物藏品", "克利夫兰艺术博物馆  303 件  CC0",
         "仅提供织物肌理（材质层）", "◇ 不参与元素级溯源"],
        GREY, fs=13)

    label(ax, 50, 10.4,
          "★ 纹样层元素级可溯；材质层仅实物可溯。两者不得混称「100% 可溯源」。",
          fs=12.5, color=RED, bold=True)
    label(ax, 50, 6.2,
          "数据流以 src/pipeline.py 为准：run() = M1→M2→M3→实物佐证层→M6；"
          "save_all() = M6出图→M4→M4a",
          fs=10.5, color=GREY)
    label(ax, 50, 3.0,
          "M5 风格化与 3D 预览由界面单独触发，输出不可溯源，与溯源链严格分区。",
          fs=10.5, color=GREY)

    return save(fig, "arch_system.png")


# ================================================================ 图 2 流程图
def fig_flow():
    fig, ax = canvas((14.0, 17.0))

    label(ax, 50, 98.2, "端到端流程图 · 一句需求到可用成果",
          fs=22, color=INK, bold=True)
    label(ax, 50, 94.8, "左侧为处理环节，右侧为该环节产出的中间表示（数据形态）",
          fs=12, color=GREY)
    ax.plot([6, 94], [91.9, 91.9], color=GOLD, lw=2.5)

    # (环节, 说明, 产出形态, 颜色, 是否可选)
    steps = [
        ("M1  意图解析", "LLM + 规则兜底", "《纹样文化配方》\n场合 / 寓意 / 母题 / 配色", RED, False),
        ("M2  元素检索", "CLIP 向量 + faiss，三招调优", "候选命中 Top-K\n（含槽位保底命中）", RED, False),
        ("M3  文化校验", "25 条规则 · 四类约束", "违规告警 violations\n（寓意冲突 / 场合失配）", RED, False),
        ("实物佐证层", "按配色距离选一件织物", "织物肌理\n（材质层，不参与溯源）", GREY, False),
        ("M6  溯源卡片", "元素 → 出处 → 寓意 → 授权", "元素级溯源卡片\n（PNG + Markdown）", RED, False),
        ("M4 / M4a  设计依据板与组合合成", "素材拼版 + 真组合合成", "依据板 + 组合纹样图\n（供风格化 / 3D 使用）", OCHRE, False),
        ("M5  AI 风格化", "通义万相 wanx-v1", "风格化图\n★ 输出不可溯源", PURPLE, True),
        ("3D 器物形态", "分区贴图 + 光线投射", "三联效果图 + GLB\n（梅瓶 / 方盒 / 团扇）", OCHRE, True),
    ]

    # ★ y_top 是"第一个框的**顶部**"——必须低于金色分隔线(91.9)，
    #   否则框会盖住副标题（初版就踩了这个，标题被挡）。
    y_top = 88.4
    bh, gap = 7.4, 2.4
    for i, (name, desc, out, col, opt) in enumerate(steps):
        y = y_top - bh
        # 左：环节
        box(ax, 6, y, 46, bh, [name, desc], col, fs=12.5)
        if opt:
            label(ax, 7.6, y + bh - 1.6, "可选", fs=9.5, color="#FCF9F3",
                  ha="left", bold=True)
        # 箭头
        arrow(ax, 52, y + bh / 2, 57.6, y + bh / 2, color=col, lw=1.8, ms=13)
        # 右：产出
        box(ax, 57.6, y, 36.4, bh, out.split("\n"), "#FBF6EA",
            tc=INK, fs=11.5, bold_first=True, ec=LINE, lw=1.2)
        # 下行箭头
        if i < len(steps) - 1:
            arrow(ax, 29, y - 0.2, 29, y - gap + 0.2, color=GREY, lw=1.8, ms=13)
        y_top -= bh + gap

    label(ax, 50, 7.0, "★ 管线原则：任一单点失败不中断，降级并记录（演示稳定性优先）",
          fs=11.5, color=RED, bold=True)
    label(ax, 50, 3.2, "顺序以 src/pipeline.py 为准；M5 与 3D 为界面单独触发的可选延伸。",
          fs=10.5, color=GREY)
    return save(fig, "arch_flow.png")


# ================================================================ 图 3 三层次
def fig_provenance():
    fig, ax = canvas((15.0, 8.4))

    label(ax, 50, 93.5, "三种溯源层次 · 各回答一个不同的问题",
          fs=22, color=INK, bold=True)
    label(ax, 50, 89.4, "三者互补，不是同一件事的三个说法",
          fs=12.5, color=GREY)
    ax.plot([6, 94], [86.6, 86.6], color=GOLD, lw=2.5)

    cols = [
        (RED, "元素级", "生成与溯源页",
         "这张图的每个部件\n来自哪条母题？",
         "samples.json 的 elements 字段",
         "100% 覆盖\n（生成时即确定，非事后推测）"),
        (GREEN, "谱系级", "纹样谱系页",
         "这类纹样在谱系上\n跟谁最近？",
         "samples.json 的 related_motifs 字段\n100 母题 / 385 边 / 5 族",
         "全库级视图\n模块度 0.549，无孤立节点"),
        (BLUE, "风险级", "版权审查页",
         "这张设计图\n与本库是否雷同？",
         "感知哈希（结构层）\n+ CLIP 语义（语义层）",
         "任意上传图\n输出 高/中/低 风险分级"),
    ]

    cw, cg = 29.0, 3.5
    cx = 4
    for col, name, where, question, source, cover in cols:
        # 头部
        box(ax, cx, 74.0, cw, 10.0, [name, where], col, fs=15)
        # 问题
        box(ax, cx, 58.0, cw, 13.2, ["回答的问题"] + question.split("\n"),
            "#FBF6EA", tc=INK, fs=11.5, ec=LINE, lw=1.2)
        # 数据来源
        box(ax, cx, 38.6, cw, 16.2, ["数据来源"] + source.split("\n"),
            "#FBF6EA", tc=INK, fs=11.5, ec=LINE, lw=1.2)
        # 覆盖
        box(ax, cx, 22.0, cw, 13.4, ["覆盖范围"] + cover.split("\n"),
            "#FBF6EA", tc=INK, fs=11.5, ec=LINE, lw=1.2)
        cx += cw + cg

    box(ax, 4, 4.0, 92, 12.0,
        ["★ 谱系级不提升检索准确率 —— 消融实验：关联数据在三种输入下均无正收益",
         "expand（扩展候选）与 boost（关联加权）Top-1 普遍下降；它的价值在可解释性，不在准确率。"],
        "#F2E4E4", tc=INK, fs=12, ec=RED, lw=1.6, bold_first=True)
    return save(fig, "arch_provenance_layers.png")


def main():
    print("生成技术报告配图…")
    fig_architecture()
    fig_flow()
    fig_provenance()
    print("\n完成。输出目录：", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
