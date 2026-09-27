# src/pattern_layout.py
"""把配方的**语义结构**翻译成器物的**装饰结构** —— 3D 贴图布局。

★★ 为什么需要这个模块（这是"3D 很鸡肋"的真正病根）

    旧做法：把 `composed_pattern.png`（1 张 1024×1024 的方图）直接贴满器物全身，
    `tile_x=2.0` 横向绕两圈、纵向 0→1 拉满。后果：

      · 画幅是**方形**、器物是**瘦高**的 → 纹样必然被纵向拉长、横向压扁
      · 瓶腹那只蝙蝠被拉成扁的、上下顶到脖子，方盒上被面与面的接缝**劈成两半**
      · 一眼就看得出"贴上去的"，不是"画上去的"

★★ 改法：分区贴料 —— 让每一段器物表面用**合适的那一种**纹样素材

    清代瓷器（以及绝大多数中国传统器物）的装饰本来就是**分层**的：

        口沿 → 边饰带（回纹等连续纹）
        颈部 → 留白或素色
        腹部 → 主题纹（团花 / 蝙蝠 / 如意，**独立、不重复**）
        胫部 → 第二条边饰带
        底部 → 角花收边

    这个分层结构与 `recipe` 里的槽位**一一对应**：

        recipe.structure.border.pattern            → 边饰带
        recipe.structure.center_motif.name         → 腹部主题
        recipe.structure.corner.pattern            → 底部角花

    所以这不是"为了好看耍的花招"——它恰恰是**把配方的语义结构，忠实地
    翻译成了器物的装饰结构**。立论上比旧做法更硬：
    旧做法只能声明"纹样来自母题库"，新做法还能说清"哪一段来自哪一个母题"。

★★ 溯源口径（与旧版一致，未变）
    · 每一段贴图都裁自母题库某一条 `image_path` 的纹样区 → **元素级可溯**
    · 分区布局的规则在代码里写死、可复现 → 不是 AI 生成、不引入新溯源问题

用法：
    from src.pattern_layout import build_strip, layout_for
    strip = build_strip(recipe, hits, height=1024)      # 一张"展开图"
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 素色留白（颈部/间隔带）：取纸色系，与合成图主色相合
NEUTRAL = (247, 241, 230)


# ---------------------------------------------------------------- 地子（底色层）
#
# ★ 为什么要有"地子"这个概念
#   原来所有分区的地色统一是 NEUTRAL 纯色。实测下来整体**偏素**：
#   白底占比太大（方盒四周、团扇扇面、梅瓶肩颈），像贴纸不像器物。
#
#   所以引入一个可选的**地子图**：一张低饱和、低对比、带细腻肌理的底纹，
#   覆盖 NEUTRAL 的角色。它可以从 M5 的 AI 风格化图抽取（见 `style_ground`），
#   也可以完全没有（= 退回原来的纯色行为）。
#
# ★ 为什么用模块级上下文而不是加参数
#   `_band` / `_neutral_tile` / `build_strip` / `build_fan_face` /
#   `build_box_lid` / `_ring_band` / `_soften_bands` 全都用到地色，
#   逐个加参数会改动面很大、且容易漏。用 `use_ground()` 上下文管理器
#   一次性切换，调用方（preview3d / glb_export）只需包一层 with。
#
# ★ 线程安全说明：本模块全流程是单线程同步调用（Streamlit 每次 rerun 单线程），
#   不引入并发；若将来要并发，须改成显式传参。
_GROUND = {"img": None, "rgb": None}


def current_ground():
    """返回 (地子图 or None, 主色 rgb)。主色在无地子时等于 NEUTRAL。"""
    return _GROUND["img"], (_GROUND["rgb"] or NEUTRAL)


@contextmanager
def use_ground(img, rgb=None):
    """在 with 块内启用一块地子图（None = 退回纯色 NEUTRAL）。

    用法：
        from src.style_ground import make_ground, ground_rgb
        g = make_ground(".../stylized_30.png")
        with use_ground(g, ground_rgb(...)):
            strip, meta = build_strip(recipe, hits, kind="vase")
    """
    old = (_GROUND["img"], _GROUND["rgb"])
    _GROUND["img"] = img
    _GROUND["rgb"] = tuple(rgb) if rgb else None
    try:
        yield
    finally:
        _GROUND["img"], _GROUND["rgb"] = old


def ground_tile(w, h):
    """按需取一块 (w,h) 的地子图。无地子 → 纯色 NEUTRAL。

    ★ 地子图是**模糊过的氛围图**，直接缩放铺满即可，不需要真平铺 ——
      它本身没有可辨识的图案，缩放不产生"接缝"问题。

    （对外公开名；模块内部短名 `_ground_tile` 指同一函数。）
    """
    g = _GROUND["img"]
    if g is None:
        return Image.new("RGB", (max(1, w), max(1, h)), NEUTRAL)
    return g.convert("RGB").resize((max(1, w), max(1, h)), Image.LANCZOS)


_ground_tile = ground_tile


# ---------------------------------------------------------------- 素材获取

def _hits_by_name(hits):
    """把 hits 整理成 {母题名: 样本}。同名只留第一条（与 m4_compose 一致）。"""
    by = {}
    for h in hits or []:
        s = h.get("sample") or {}
        n = (s.get("name") or "").strip()
        if n and n not in by:
            by[n] = s
    return by


def _load_tile(sample, clean=True):
    """读一条母题样本的**纯纹样块**（复用 M4a 已验证的自动裁切）。

    ★ 直接复用 `m4_compose.crop_pattern`，不另写一套裁切逻辑 ——
      那套裁切是踩了五次坑才定下来的（见 m4_compose.pattern_crop_box 的注释），
      这里必须共用，否则两处会出现不一致的裁切结果。
    """
    from src.m4_compose import crop_pattern
    p = ROOT / sample["image_path"]
    if not p.exists():
        return None
    return crop_pattern(p, clean=clean)


def _load_motif_centered(sample, out=384):
    """为中心**单体**纹样取一块"恰好一个母题"的方形素材。

    ★★ 为什么不能用 crop_pattern 的那块（这是实测发现的真问题）
      `crop_pattern` 的框 = 包围盒中心 + 边长 min(宽,高)×**0.62**。
      它当初是为**平铺成边饰带**设计的 —— 大一点小一点都能平铺，
      边界蹭到邻位纹样也无所谓（平铺后根本看不出来）。

      但腹部主题纹是**单独展示**的。0.62 这块在「蝙蝠纹」上会框到
      **一只完整蝙蝠 + 右下角另外半只蝙蝠**（我把框画回原图确认过）。
      单独摆出来就是半只蝙蝠，很假 —— 这才是"蝙蝠被劈成两半"的**真正根因**，
      不是拼接逻辑写错了。

    ★★ 做法：**按"有没有独立地子"分两路**（判据是用全库数据反推出来的）

      判据：`|地色 − 海报纸色| > 200`

        ① 有独立地子（蝙蝠纹石青 8/40/72、福寿纹朱红 168/72/24、
           麒麟纹 40/56/40 …）
           → 用「与地色的距离」做前景分割，取**最大连通块的外接矩形**。
             实测：蝙蝠纹最大块 x[466,901] y[433,890]，正是画面中央**那只完整蝙蝠**
             （占前景 75%，剩下 18% 就是右下角那半只，被自然排除了）。

        ② 地色 ≈ 纸色（回纹 041: Δ=6、如意纹 076: Δ=18、祥云纹 061: Δ=51）
           → 这类是**连续纹**（二方/四方连续），根本没有"一个母题"这回事，
             正确用法就是平铺。退回 `pattern_crop_box` 的居中框。

      为什么这个判据可信：Δ 的分布是**双峰**的 ——
      有地子的都在 400~570，连续纹都在 6~51，中间**空着**（没有 60~200 的样本）。
      所以阈值取 200 落在空档里，对全库都稳。

    ⚠️ 试过"模板匹配找周期"这条更聪明的路，放弃了：
      纹样是非刚性重复（大小、朝向都有变化），NCC 峰值不稳，跑出来时对时错 ——
      不可复现的东西不能进交付物。
    """
    from src.m4_compose import pattern_crop_box
    p = ROOT / sample["image_path"]
    if not p.exists():
        return None
    im = Image.open(p).convert("RGB")
    a = np.asarray(im).astype(np.int16)
    H, W, _ = a.shape

    anchor = pattern_crop_box(p, fill_ratio=0.62)
    x0, y0, x1, y1 = anchor
    m = np.zeros((H, W), bool)
    m[y0:y1, x0:x1] = True

    # 纹样区地色 = 锚点框内出现最多的颜色（量化到 16 级）
    sel = a[m]
    q = sel // 16
    key = q[:, 0] * 256 + q[:, 1] * 16 + q[:, 2]
    vals, counts = np.unique(key, return_counts=True)
    bgq = vals[int(np.argmax(counts))]
    bg = np.array([(bgq // 256) * 16 + 8, ((bgq // 16) % 16) * 16 + 8,
                   (bgq % 16) * 16 + 8], np.int16)
    paper = a[5:25, 5:25].reshape(-1, 3).mean(0).astype(np.int16)

    if int(np.abs(bg - paper).sum()) > 200:
        from scipy import ndimage
        from src.m4_compose import pattern_region_mask

        # ★★ 第一步也是最重要的一步：**只在前景 = 纹样区内部**找母题。
        #   纹样区是个**弧边形状**，弧线外面就是海报的纸色。
        #   如果直接在矩形里找，母题的外接框会一路扩到弧线上、
        #   把纸色和弧线一起框进来（实测：蝙蝠纹裁块左下角一块米白 + 一道金弧）。
        #   取交集之后，弧线外一律不算，外接框自然收进纹样区。
        region, _ = pattern_region_mask(p)
        m = m & region

        dist = np.abs(a - bg).sum(2)
        fg = (dist > 100) & m
        # ★ 清理两步（顺序不能反）：
        #  ① 开运算去掉**细长条**：弧线宽约 2~4px，母题最细的翼展也有 20+px，
        #     7×7 开运算能干掉残留的弧线、留住母题。
        #  ② 闭运算补小孔：**只能用 3×3**。7×7 会把"蝙蝠—云—邻位蝙蝠"
        #     连成一整片、外接框罩住整个纹样区（已试错）。
        fg = ndimage.binary_opening(fg, np.ones((7, 7)))
        fg = ndimage.binary_closing(fg, np.ones((3, 3)))
        lab, n = ndimage.label(fg)
        if n:
            sizes = ndimage.sum(fg, lab, range(1, n + 1))
            ys, xs = np.where(lab == int(np.argmax(sizes)) + 1)
            mx0, my0, mx1, my1 = int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
            # ★ 再内缩 6%：外接框的边界上**一定粘着邻位母题伸进来的那一点点**
            #   （蝙蝠翼展很宽，相邻那只的翼尖会探进这一只的框里）。
            #   不外扩、且内缩一刀，是唯一能保证"框里只有一只完整母题"的做法。
            #   ⚠️ 代价：翼尖会被削掉一点点（约 6%），但比"多出半只"好得多。
            ix = int((mx1 - mx0) * 0.06); iy = int((my1 - my0) * 0.06)
            mx0, my0, mx1, my1 = mx0 + ix, my0 + iy, mx1 - ix, my1 - iy
            box = (max(0, mx0), max(0, my0), min(W, mx1), min(H, my1))
            if min(box[2] - box[0], box[3] - box[1]) >= 96:
                _MOTIF_META[str(p)] = {"mode": "blob", "bg": bg.tolist(),
                                       "paper": paper.tolist(),
                                       "delta": int(np.abs(bg - paper).sum()),
                                       "box": list(box)}
                t = im.crop(box)
                return ImageOps.fit(t, (out, out), method=Image.LANCZOS)

    _MOTIF_META[str(p)] = {"mode": "tile", "bg": bg.tolist(),
                           "paper": paper.tolist(),
                           "delta": int(np.abs(bg - paper).sum()),
                           "box": list(anchor)}
    t = im.crop(anchor)
    return ImageOps.fit(t, (out, out), method=Image.LANCZOS)


# 记录每个素材走的是哪一路（供调试与报告说明；不影响渲染结果）
_MOTIF_META: dict = {}


def motif_meta():
    """返回各素材的主题纹取框决策记录（调试/报告用）。"""
    return dict(_MOTIF_META)


def _neutral_tile(size, rgb=None):
    """素色块（做颈部留白与过渡带）。

    ★ 有地子时返回**地子切片**而不是纯色 —— 这是"去素"的关键一环：
      颈部/间隔带原本是一大片死白，换成带肌理的暖色底立刻有器物感。
    """
    if rgb is None and _GROUND["img"] is not None:
        return _ground_tile(size, size)
    return Image.new("RGB", (size, size), tuple(rgb or NEUTRAL))


def _band(tile, w, h, n_repeat=None, keep_ratio=True):
    """把纹样块铺满一条 w×h 的带。

    ★ 与 m4_compose._tile_band 的关键差别：
      那里"缩到高度再横向重复"，重复次数由宽度被动决定 ——
      于是常出现 **2.3 个单元**，最右边是一个被切断的纹样，很显廉价。
      这里允许**指定整数重复次数** n_repeat，宁可轻微缩放也要凑整。

    ★★ 但不只是"凑整"就够：如果带子高 h 本身**不是单元高的整数倍**，
      纵向同样会被切断（回纹看起来上下各缺一条边）。
      所以这里先按 n_repeat 推出"单元理想高 = h"，再把单元宽设为 w/n，
      最后**以单元为单位**填满 —— 只要 n 是整数，横向就不会切；
      纵向由 h 决定、单元高就是 h，也不切。这是唯一自洽的解法：
      **让整个带子恰好等于 n 个单元。**
    """
    if n_repeat and n_repeat >= 1:
        uw = max(1, int(round(w / n_repeat)))
    elif keep_ratio:
        uw = max(1, int(round(tile.width * h / max(1, tile.height))))
    else:
        uw = h
    unit = tile.resize((uw, h), Image.LANCZOS)
    out = _ground_tile(w, h)
    x = 0
    while x < w:
        out.paste(unit, (x, 0))
        x += uw
    return out


def _rule_band(w, h, rgb=(238, 231, 218), ink=(206, 194, 172)):
    """窄弦纹（两条细横线）—— 用作分区之间的过渡，替代整条素色留白。

    ★ 为什么不能用纯素色留白：一条米白横带在深色纹样之间**过于扎眼**，
      看起来像"夹心饼干"，一眼假。
      真实瓷器的分层之间用的是**弦纹**（凸起/描画的一条或两条细线），
      宽度极窄、颜色比地色略深 —— 既分隔了层次，又不会抢戏。

    ★★ 配色讲究（实测两版才对）：
      第一版用 (228,218,199) 做地色 → 在深蓝、墨绿的纹样之间**仍然是一条亮带**，
      因为纹样的地子都偏深，任何"浅米色"都跳。
      第二版改成**紧贴 NEUTRAL 但略亮**、且把弦线做**很细**（h//10），
      视觉上就只剩"两道线"，不再是"一条带"。
    """
    out = Image.new("RGB", (w, h), tuple(rgb))
    dr = ImageDraw.Draw(out)
    lin = max(1, h // 10)
    off = max(1, (h - lin * 2) // 3)
    dr.rectangle([0, off, w, off + lin - 1], fill=tuple(ink))
    dr.rectangle([0, h - off - lin, w, h - off - 1], fill=tuple(ink))
    return out


# ---------------------------------------------------------------- 展开图

# 各形态的 (周长 : 高) —— 实测值，决定展开图的宽高比。
#
# ★★ 为什么这个比例必须对（这是"方盒上的蝙蝠被压扁糊满一面"的根因）
#   展开图是"**把器物表面剪开摊平**"：横向 = 环一圈的周长，纵向 = 器物的高。
#   所以它的宽高比**必须等于器物的 周长:高**，否则贴上去就是拉伸/压缩。
#
#   实测（scripts/check_strip_ratio.py 会重新打印）：
#     陶瓶 高 1.150、最大周长 2.212 → 1.923
#     方盒 → 按"一个面"算（见下），不按整圈周长
#     （曾有过"赏盘"形态，近平面、周长高比 17:1，无法用展开图 —— 已移除。
#       教训：**布局几何必须匹配载体几何**，平面载体不该套"环一圈"的逻辑。
#       现在平面圆形载体走 `build_fan_face` 的极坐标同心布局。）
STRIP_ASPECT = {
    "vase": 1.92,      # 实测 1.923
    # ★ 方盒：**不是按整圈周长**，而是按"**一个面**"的宽高比。
    #   理由：方盒的四个面在视觉上是**四个独立的画面**（人看盒子是"看一面"），
    #   不是"绕一圈的连续画卷"。按周长 4.4 生成会把每个面压到 1/4 宽，
    #   主画面里的蝙蝠被横向压缩 1.1 倍以上、还被切成半只（实测就是
    #   "盒面上一排小蝙蝠 + 大量白带"）。
    #   按面来算：面宽 0.958 / 盒高 0.958 ≈ 1.0 → 但主画面区只占面的 74%，
    #   为了让主体在面上撑满，取 1.15（略宽，给左右留一点边）。
    "box": 1.15,
    "fan": 1.00,       # 团扇/平面方形载体走方形图
}


def strip_size(kind, height=1024):
    """按器型算展开图的 (宽, 高)。宽 = 高 × 该器型的「宽高比」。"""
    ar = STRIP_ASPECT.get(kind, 1.92)
    return int(round(height * ar)), height


# ★ 这些数字是**清代梅瓶一类器物的常见装饰分层**，做法上：
#   · 腹部占最大份额（0.46），因为主题纹是主角
#   · 过渡带**故意做窄**（0.03~0.05），只当弦纹用，不做整条留白
DEFAULT_BANDS = [
    # (v0, v1, 槽位, 说明)
    (0.00, 0.08, "corner", "底部边饰（角花）"),
    (0.08, 0.12, "rule", "弦纹"),
    (0.12, 0.30, "border", "胫部边饰带"),
    (0.30, 0.34, "rule", "弦纹"),
    (0.34, 0.82, "center", "腹部主题纹"),
    (0.82, 0.86, "rule", "弦纹"),
    (0.86, 0.94, "border2", "口沿边饰带"),
    (0.94, 1.00, "rule", "弦纹"),
]


def layout_for(kind):
    """按器型给出分区（比例可微调：盘类腹部更大、盒类更均匀）。"""
    if kind == "box":
        # ★ 方盒的装饰结构与瓶不同：**盒子四面是一个连续的"面"**，
        #   上去就分 7 段会把弦纹（米白）放大成宽条，看起来像"贴了几条白胶带"。
        #   实测就是这样 —— 盒面上出现三整条白带。
        #   所以方盒用**更少的层次**：底边一条窄边饰 + 大面主题 + 顶边一条窄边饰。
        #   这也更像真实包装盒的做法（大面积画面 + 上下压边）。
        return [
            (0.00, 0.09, "border", "下边饰带"),
            (0.09, 0.13, "rule", "弦纹"),
            (0.13, 0.87, "center", "主画面"),
            (0.87, 0.91, "rule", "弦纹"),
            (0.91, 1.00, "border2", "上边饰带"),
        ]
    return list(DEFAULT_BANDS)          # vase / 默认


def build_fan_face(recipe, hits, size=1024, ring_ratio=0.30, core_ratio=0.56,
                   spread_ratio=0.86):
    """给**圆形的平面载体**（团扇）拼一张正方形贴图 —— 用**极坐标同心布局**。

    ★★★ 为什么不能用 `build_face_square` 那套（实测踩得很惨）

        那一版走的是"方图 + 四条直边带"：
            外圈四条**直的**回纹带  →  贴到圆扇上，弧边把带子切成四段，
                                      四个角露出"带斜边的方框"（像贴了四张邮票）
            中心主题纹做成**方形的**    →  扇面上一块米白色方块，边角明显

        根因：载体是**圆的**，布局却是**方的** —— 两套几何对不上。
        这和"赏盘用带状展开图"是同一类错误：**布局的几何必须匹配载体的几何**。

    ★ 正解：极坐标。
        贴图本身是正方形（因为扇面的 UV 是 (x,y) 平面映射），
        但图里的内容**全部按同心圆构造**：

            圆内半径 r：
              r < core_ratio/2·s        → 主题纹（圆形放置，主画面）
              core_ratio/2·s ~ ring 内   → 弦纹 + 一圈地色
              外圈 ring_ratio·s 宽       → 边饰带，用 `_ring_band` **沿圆周铺**
              r > 0.5·s                 → 扇面之外，**不落位**（贴图这块随便填地色，
                                          反正 UV 只采样圆内）

        这样每个环带都是真圆环，贴到圆扇上**严丝合缝**，四角不再露方框。

    ★ 外圈怎么"沿圆周铺"：用 `_ring_band` —— 把边饰单元按**极坐标**采样：
        对环内每个像素求 (θ, r)，θ 换算成 u、r 换算成 v，再双线性采样边饰条。
      等价于把一条直带"卷"成圆环。回纹这类二方连续纹卷起来正好接得上
      （只要沿圆周重复整数次就无缝）。

    ⚠️ 角花槽位：平面圆形载体**没有转角**，角花不落位（同上版结论）。

    ▓ 第二轮实测修正（两个小坑）
      ① **中圈出现一条死板的纯色环**：主题圆与边饰带之间那块地色直勾勾
         空着，像没画完。→ 引入 `spread_ratio<1`：让主题纹的**地子盘**
         （不是主题纹本身）外溢到边饰带下面，被边饰盖掉。
         视觉上就是"主纹的地子一直铺到边饰带底下"，中圈不再光秃秃。
      ② **两道弦纹里主题圆那道糊成一圈白晕**：羽化半径 `d//64≈11px` 太大，
         弦纹又正好压在羽化边上。→ 羽化收到 ~2.7px，主题圆外缘**不画弦纹**，
         只留边饰带内缘往里一点的那一道。
      ③ 地色改用**主题素材自己的边色**（不是边饰素材的）：否则主题圆
         周围会有一圈"深绿压墨蓝"的双色带，很脏。
    """
    s = int(size)
    cx = cy = (s - 1) / 2.0
    out = _ground_tile(s, s)
    by = _hits_by_name(hits)
    st = (recipe.get("structure") or {})
    cm = (st.get("center_motif") or {}).get("name", "").strip()
    bd = (st.get("border") or {}).get("pattern", "").strip()
    cn = (st.get("corner") or {}).get("pattern", "").strip()

    meta = {"layout": "fan_radial", "size": [s, s], "bands": []}

    r_out = s / 2.0                          # 扇面外半径（贴图边界）
    r_ring_in = r_out * (1.0 - ring_ratio)   # 边饰带内半径
    r_ring_mid = (r_out + r_ring_in) / 2.0
    r_core = s * core_ratio / 2.0            # 主题纹圆半径
    # ★ 地子盘至少比主题圆大 8%，否则主题圆外侧没有过渡色，
    #   蝙蝠的翼尖会直接怼到弦纹/边饰带上。
    r_disc = max(r_ring_in * spread_ratio, r_core * 1.08)

    tb = _load_tile(by[bd]) if bd in by else None
    tc = _load_motif_centered(by[cm]) if cm in by else None

    # ---- ① 地色盘：取**主题素材自己的地色**，铺到 r_disc ----
    ground = None
    if tc is not None:
        a = np.asarray(tc.convert("RGB"), np.int16)
        edge = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
        ground = tuple(int(v) for v in np.median(edge, axis=0))
    if ground is None:
        # 没有主题素材：用模块地子的主色（有肌理时取平均；无地子即 NEUTRAL）
        ground = current_ground()[1]
    elif tb is not None:
        ground = tuple(int(v) for v in np.median(
            np.asarray(tb, np.int16).reshape(-1, 3), axis=0))
    ImageDraw.Draw(out).ellipse(
        [cx - r_disc, cy - r_disc, cx + r_disc, cy + r_disc], fill=ground)

    # ---- ② 外圈边饰：卷成圆环 ----
    if tb is not None:
        # 沿圆周的重复次数：让**弧长**上的单元宽度 ≈ 素材的原单元宽度
        unit_w = max(8, tb.width)
        circ = 2 * np.pi * r_ring_mid
        n_rep = max(6, int(round(circ / unit_w)))
        ring = _ring_band(tb, s, r_ring_in, r_out, n_rep=n_rep)
        out.paste(ring, (0, 0), ring)

    # ---- ③ 主题纹：圆形放置（外溢部分被 ② 盖掉）----
    if tc is not None:
        d = int(2 * r_core)
        # ★ 内缩 6% 再 fit：`_load_motif_centered` 已经把框收到母题外接矩形，
        #   再直接 fit 到圆里 → 蝙蝠的耳尖/翼尖**贴到圆边**，视觉上"顶格"。
        #   先按 0.94 缩一点留出呼吸空间。
        tcx = tc.copy()
        k = 0.94
        tcx = tcx.resize((max(1, int(tc.width * k)), max(1, int(tc.height * k))),
                         Image.LANCZOS)
        unit = ImageOps.fit(tcx, (d, d), method=Image.LANCZOS,
                            centering=(0.5, 0.5))
        # 用主题素材自己的地色补边（fit 后的空处）
        unit = ImageOps.pad(unit, (d, d), color=ground, method=Image.LANCZOS)
        mask = Image.new("L", (d, d), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, d - 1, d - 1], fill=255)
        # ★ 羽化只留 2~3px：上一版 d//64≈11px，主题圆边糊成一圈光晕。
        mask = mask.filter(ImageFilter.GaussianBlur(max(1.5, s / 380)))
        out.paste(unit, (int(cx - r_core), int(cy - r_core)), mask)

    # ---- ④ 同心弦纹：只留一道（边饰带内缘往里一点）----
    # ★ 主题圆外缘不画线 —— 那里正好是羽化边，叠一道线会变成突兀的白圈。
    dr = ImageDraw.Draw(out)
    lw = max(2, s // 200)
    r_rule = r_ring_in * 0.955
    dr.ellipse([cx - r_rule, cy - r_rule, cx + r_rule, cy + r_rule],
               outline=(226, 215, 196), width=lw)

    meta["bands"] = [
        {"slot": "center", "label": "扇面主题纹", "motif": cm},
        {"slot": "border", "label": "外圈边饰（沿圆周铺）", "motif": bd},
        {"slot": "corner", "label": "四角角花（平面圆形载体无转角，未落位）",
         "motif": cn, "applied": False},
    ]
    return out, meta


def build_box_lid(recipe, hits, size=1024, ring_ratio=0.20):
    """给方盒**顶/底盖**一张方形图：外圈边饰框 + 中心主题纹。

    ★★ 为什么顶盖不能直接采展开图的某一段（实测踩到）
        最初把顶盖 UV 固定映射到展开图上边饰带那条线（v≈0.95），
        想当然以为"顶盖印边饰"就行。结果是：**正上方的顶盖与侧面之间
        出现一道深色横带** —— 因为 u 是沿 x 线性映射的，而顶盖的 x 范围
        与侧面的 x 范围**不同**（顶盖边长 = 2·hx，侧面同样 2·hx，其实一样，
        但顶盖的 v 只取了一条**线**，等于把只有几个像素高的边饰带
        横向拉伸铺满整个顶盖 → 完全糊掉，只剩深色）。

      正解：**给顶盖单独生成一张图**，它是一张**方的画面**：
        外圈：四条边饰带围成方框
        中心：主题纹（方形放置）
      这正是真实礼盒盒盖的做法（边框 + 中心主图）。

    ⚠️ 与团扇的区别：团扇是**圆的**平面，所以走极坐标同心；
      盒盖是**方的**平面，所以走"方框 + 方块"。**布局几何匹配载体几何**，
      这一条是贯穿始终的原则。
    """
    s = int(size)
    out = _ground_tile(s, s)
    by = _hits_by_name(hits)
    st = (recipe.get("structure") or {})
    cm = (st.get("center_motif") or {}).get("name", "").strip()
    bd = (st.get("border") or {}).get("pattern", "").strip()

    tb = _load_tile(by[bd]) if bd in by else None
    tc = _load_motif_centered(by[cm]) if cm in by else None

    bw = max(8, int(s * ring_ratio))
    # ★ 主题方块的地色：优先用主题素材自己的边色（保证主题圆周围不"脏"），
    #   没有素材时退回模块地子 —— 后者自带肌理，比纯色好看。
    ground = None
    if tc is not None:
        a = np.asarray(tc.convert("RGB"), np.int16)
        edge = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
        ground = tuple(int(v) for v in np.median(edge, axis=0))
    if ground is None:
        # 没有主题素材：用模块地子的主色（有肌理时取平均；无地子即 NEUTRAL）
        ground = current_ground()[1]

    # 中心方块铺主题地色
    ImageDraw.Draw(out).rectangle([bw, bw, s - bw, s - bw], fill=ground)

    # ① 主题纹：方形放置（缩到中心区，留出方框宽度）
    if tc is not None:
        inner = s - 2 * bw
        k = 0.86
        unit = tc.resize((max(1, int(tc.width * k)), max(1, int(tc.height * k))),
                         Image.LANCZOS)
        unit = ImageOps.pad(unit, (inner, inner), color=ground,
                            method=Image.LANCZOS)
        out.paste(unit, (bw, bw))

    # ② 四条边饰带围成方框（每条按**自身长度**算重复次数，不纵向拉伸）
    if tb is not None:
        top = _band(tb, s, bw, n_repeat=_auto_repeat(tb, s, bw))
        out.paste(top, (0, 0))                                    # 上
        out.paste(top.transpose(Image.ROTATE_180), (0, s - bw))   # 下
        left = _band(tb, s, bw, n_repeat=_auto_repeat(tb, s, bw)) \
            .transpose(Image.ROTATE_90)
        out.paste(left.resize((bw, s), Image.LANCZOS), (0, 0))
        out.paste(left.resize((bw, s), Image.LANCZOS), (s - bw, 0))

    # ③ 方框内侧一道细弦纹
    dr = ImageDraw.Draw(out)
    lw = max(2, s // 200)
    dr.rectangle([bw, bw, s - bw - 1, s - bw - 1],
                 outline=(226, 215, 196), width=lw)

    meta = {"layout": "box_lid", "size": [s, s], "bands": [
        {"slot": "center", "label": "盒盖主题纹", "motif": cm},
        {"slot": "border", "label": "盒盖边框边饰", "motif": bd},
    ]}
    return out, meta


def _ring_band(tile, s, r_in, r_out, n_rep=12):
    """把一条二方连续纹样"卷"成圆环，返回 s×s 的 RGBA（环外 alpha=0）。

    ★ 做法：对整个方形画布求极坐标 (θ, r)，把
        u = θ/2π · n_rep   （沿圆周重复 n_rep 个单元）
        v = (r - r_in) / (r_out - r_in) · tile_h   （沿环宽映射到素材高度）
      再对 tile 双线性采样。环外 alpha 置 0。

    ★ 为什么 u 用 `θ/2π·n_rep` 而不是 `θ/2π`：
        直接用 θ/2π 会让**整条**素材绕整整一圈 —— 环宽方向 v 是
        "素材高度"，但素材宽度 1 圈下来会把回纹单元横向拉伸。
        乘 n_rep 才能保持单元的长宽比。
    ★ 为什么 n_rep 要取整数：θ=0 与 θ=2π 必须采到同一个 u，
        否则圆的合缝处会出现一条**错位的接缝**（肉眼很明显）。
    """
    tile = tile.convert("RGB")
    tw, th = tile.size
    ta = np.asarray(tile, np.float32)

    yy, xx = np.mgrid[0:s, 0:s].astype(np.float32)
    cx = cy = (s - 1) / 2.0
    dx, dy = xx - cx, cy - yy
    rr = np.hypot(dx, dy)
    th_ = np.arctan2(dy, dx)                     # -π..π

    u = np.mod(th_ / (2 * np.pi), 1.0) * n_rep  # 0..n_rep
    v = np.clip((rr - r_in) / max(r_out - r_in, 1e-6), 0, 1)

    # 双线性采样（u 周期性 wrap）
    fx = np.mod(u, 1.0) * (tw - 1)
    fy = v * (th - 1)
    x0 = np.floor(fx).astype(np.int32); y0 = np.floor(fy).astype(np.int32)
    x1 = np.minimum(x0 + 1, tw - 1); y1 = np.minimum(y0 + 1, th - 1)
    tx = (fx - x0)[..., None]; ty = (fy - y0)[..., None]
    c = (ta[y0, x0] * (1 - tx) * (1 - ty) + ta[y0, x1] * tx * (1 - ty) +
         ta[y1, x0] * (1 - tx) * ty + ta[y1, x1] * tx * ty)

    rgba = np.zeros((s, s, 4), np.uint8)
    rgba[..., :3] = np.clip(c, 0, 255).astype(np.uint8)
    inside = (rr >= r_in) & (rr <= r_out)
    rgba[..., 3] = np.where(inside, 255, 0).astype(np.uint8)
    # 内外各留 1px 羽化，避开硬边锯齿
    return Image.fromarray(rgba, "RGBA").filter(ImageFilter.GaussianBlur(0.6))


def build_strip(recipe, hits, height=1024, kind="vase"):
    """按分区拼出一张**展开图**（横向 = 环绕器物一圈，纵向 = 从底到口）。

    ★ 尺寸：**宽 = 高 × 该器型的「周长:高」**（见 STRIP_ASPECT）。
      这一步是"不拉伸"的前提 —— 展开图的宽高比必须等于器物表面的宽高比。
      之前固定用 1024×1024，方盒（周长:高 = 4.8）贴上去横向被压缩 4.8 倍，
      蝙蝠就"胖得糊满整面"。现在方盒的展开图是 4915×1024，比例才对。

    ★ 横向可无缝环绕：所有贴进去的素材都是"连续纹样"（回纹、如意卷草
      本来就是二方连续），横向平铺到正好铺满即可。

    返回 (strip: Image, meta: dict)。meta 记录**每一段来自哪条母题**，供溯源引用。
    """
    w, h = strip_size(kind, height)
    by = _hits_by_name(hits)

    st = (recipe.get("structure") or {})
    cm_name = ((st.get("center_motif") or {}).get("name") or "").strip()
    bd_name = ((st.get("border") or {}).get("pattern") or "").strip()
    cn_name = ((st.get("corner") or {}).get("pattern") or "").strip()

    src = {
        "center": (by.get(cm_name), "center_motif", cm_name),
        "border": (by.get(bd_name), "border", bd_name),
        "border2": (by.get(bd_name), "border", bd_name),
        "corner": (by.get(cn_name), "corner", cn_name),
    }
    tiles = {}
    for k, (s, _, _) in src.items():
        if not s:
            tiles[k] = None
        elif k == "center":
            # ★ 主题纹用**收紧的居中框**（避免出现"半个母题"），
            #   与边饰带的框不同 —— 两者用途不同，不能共用一套参数。
            tiles[k] = _load_motif_centered(s)
        else:
            tiles[k] = _load_tile(s)

    strip = _ground_tile(w, h)
    meta = {"bands": [], "layout": kind, "strip_size": [w, h]}

    for v0, v1, slot, label in layout_for(kind):
        # v 的定义：0 = 底（profile 起点），1 = 顶
        y1 = int(round(h * (1 - v1)))       # 图里 y 向下，所以顶在小的 y
        y0 = int(round(h * (1 - v0)))
        bh = max(1, y0 - y1)
        tile = tiles.get(slot)

        if slot == "rule":
            band = _rule_band(w, bh)
        elif tile is None:
            band = _rule_band(w, bh)                     # 缺素材 → 退化为弦纹，不留白
        elif slot == "center":
            band = _center_band(tile, w, bh)
        else:
            band = _band(tile, w, bh, n_repeat=_auto_repeat(tile, w, bh))
        strip.paste(band, (0, y1))

        s_rec = src.get(slot)
        meta["bands"].append({
            "slot": slot, "label": label, "v": [round(v0, 3), round(v1, 3)],
            "sample": (s_rec[0].get("id") if s_rec and s_rec[0] else None),
            "motif": (s_rec[2] if s_rec else None),
        })

    strip = _soften_bands(strip, layout_for(kind), h)
    return strip, meta


def _center_band(tile, w, h, max_repeat=2):
    """腹部主题纹带：**等比**缩放，横向摆整数个，两侧留白补齐。

    ★ 为什么要整数个、且要重复
      主题纹（蝙蝠、团花）是**单体**纹样：横向被切断就是"半只蝙蝠"，一眼假。
      但**完全不重复**又会让两侧空出大片素地（中心区宽 491px、母题素材是方的），
      看起来像"贴了张画片"。

      所以取"**整数个单元、尽量接近正方形**"：
        · 单元宽 = w/n，取 n 使得 (w/n)/h 最接近 1 —— 母题保持原比例、不被拉伸
        · n 的上限由"单元不能小于母题的 60%"约束，避免出现密密麻麻一排小蝙蝠

      ★ 重要的是：这样得到的是 **n 只完整的母题**，不是"半只 + 半只"。
        这正是真实器物的做法（清代器物腹部常见两只 / 四只团花环绕）。
        与旧做法的**本质区别**不在"重不重复"，而在**单元是不是完整的**。
    """
    out = _ground_tile(w, h)
    if tile is None:
        return out

    # 单元高度 = 区高的 92%（留一点呼吸；顶格会切掉翼尖/尾部 —— 实测）
    uh = max(1, int(round(h * 0.92)))
    uw = max(1, int(round(tile.width * uh / tile.height)))
    # ★ n 取"能填满宽度、且单元数最少"的那个 ——
    #   宁可单元稍宽（母题保持原比例、不被拉伸），也不要排成一长串小图。
    #   `max(1, ...)` 保证至少 1 个。
    n = max(1, int(w // max(uw, 1)))
    # ★ 上限 4：超过 4 个就已经不像"主题纹"而像"边饰带"了。
    #   清代器物腹部的团花通常是 2 / 4 只环绕。
    n = min(n, 4)
    # 单元数定了之后再微调宽度，让 n 个正好铺满（最多 ±12% 的轻微缩放，
    # 视觉上察觉不到，但避免了末尾留一条空当）
    uw_fit = max(1, int(round(w / n)))
    if abs(uw_fit / uw - 1.0) <= 0.12:
        uw = uw_fit
    unit = tile.resize((uw, uh), Image.LANCZOS)
    off = (w - uw * n) // 2
    for i in range(n):
        out.paste(unit, (off + i * uw, (h - uh) // 2))
    return out


def _auto_repeat(tile, w, band_h):
    """给边饰带估算"整数个单元"的重复次数。

    目标是单元尽量接近正方形（连续纹样按原比例走），
    同时限制在 1..12 之间，避免出现细如发丝或大到只剩半个单元的情况。
    """
    if tile is None:
        return None
    ideal = w / max(1e-6, (tile.width * band_h / tile.height))
    n = int(round(ideal))
    return max(1, min(12, n))


def _soften_bands(strip, bands, h, feather=3):
    """把分区边界处的横向接缝做轻微羽化。

    ★ 为什么需要：分区是"硬切"的，两条带之间会留下一条锐利的色差横线，
      在细长的瓶身上看起来就是一道**明显的水波纹**。
      做法：在边界上下各 feather 像素内，沿纵向做一次 1-2-1 平滑。
      只动边界、不动带内部，因此不会把纹样糊掉。
    """
    a = np.asarray(strip, np.float32).copy()
    for v0, v1, _, _ in bands:
        for vv in (v0, v1):
            y = int(round(h * (1 - vv)))
            lo, hi = max(1, y - feather), min(h - 2, y + feather)
            if hi <= lo:
                continue
            seg = a[lo - 1:hi + 2]
            sm = seg.copy()
            sm[1:-1] = (seg[:-2] + 2.0 * seg[1:-1] + seg[2:]) / 4.0
            a[lo - 1:hi + 2] = sm
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


# ---------------------------------------------------------------- 预览/调试

def save_strip(recipe, hits, out_path, height=1024, kind="vase"):
    """出图（调试与报告用）。"""
    strip, meta = build_strip(recipe, hits, height=height, kind=kind)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    strip.save(out_path, "PNG")
    return out_path, meta
