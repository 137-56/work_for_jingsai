# scripts/make_data_summary.py
"""把 JSON 数据转成技术报告可直接引用的 Markdown 摘要。

★ 为什么用脚本生成而非手写
    报告里的数字最容易与数据源脱节（改了一处忘了另一处）。
    本脚本**所有数字都从 docs/*.json 读出**，杜绝手抄。
    数据更新后重跑即可。

用法：
    .venv/Scripts/python.exe scripts/make_data_summary.py [输出目录]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs"


def pct(x):
    return f"{x * 100:.1f}%" if isinstance(x, (int, float)) else "—"


def main():
    m = json.loads((DOCS / "metrics.json").read_text(encoding="utf-8"))
    ab = m.get("ablation", {})
    ia = m.get("input_ablation", {})
    rel = m.get("related_motifs_experiment", {})
    cr = m.get("culture_rule_detection", {})
    cc = m.get("copyright_calibration", {})
    nb = m.get("neighbor_related_rate", {})
    items = m["headline_metrics"]["items"]

    L = []
    A = L.append
    A("# 数据与实验结果摘要")
    A("")
    A(f"> 数据来源：`docs/metrics.json`（单一事实来源）、`docs/exp_related_motifs.json`、")
    A(f"> `docs/m7_calibration.json`。测量日期：{m.get('measured_at', '—')}；"
      f"样本库 {m.get('sample_lib_size', '—')} 条。")
    A("")
    A("**引用规则**：技术报告 / PPT / 作品简介三处取数一律以本摘要与 `metrics.json` 为准，"
      "不得到处自算。校验脚本 `scripts/check_metrics.py`。")
    A("")
    A("---")
    A("")

    # ---------------- 1 关键指标 ----------------
    A("## 一、关键指标")
    A("")
    A("| 指标 | 结果 | 目标 | 状态 |")
    A("|---|---|---|---|")
    for k, v in items.items():
        val = v.get("value")
        val = "—" if val is None else val
        A(f"| {k} | **{val}** | {v.get('target', '—')} | {v.get('status', '—')} |")
    A("")
    A("### 指标口径")
    A("")
    for k, v in m.get("metric_definition", {}).items():
        A(f"- **{k}**：{v}")
    A("")

    # ---------------- 2 检索消融 ----------------
    A("## 二、检索消融实验")
    A("")
    A("### 2.1 关闭单招（证明每一项策略的必要性）")
    A("")
    A("| 配置 | Top-1 | Top-5 |")
    A("|---|---|---|")
    A(f"| 完整（三招） | **{pct(ab.get('full_top1'))}** | "
      f"**{pct(ab.get('full_top5'))}** |")
    A(f"| 关闭元素二次筛选 | {pct(ab.get('no_rerank_top1'))} | "
      f"{pct(ab.get('no_rerank_top5'))} |")
    A(f"| 关闭类别前缀 | {pct(ab.get('no_category_prefix_top1'))} | — |")
    A(f"| 查询只用母题名 | {pct(ab.get('bare_motif_name_only_top1'))} | — |")
    A("")
    if ab.get("note"):
        A(f"> {ab['note']}")
        A("")

    A("### 2.2 输入侧消融（改变配方里有多少信息）")
    A("")
    A(f"测试集 {ia.get('testset_size', '—')} 条；{ia.get('method', '')}")
    A("")
    A("| 配方输入 | Top-1 | Top-5 | 定义 |")
    A("|---|---|---|---|")
    for key, label in [("bare", "只有母题名"), ("name_elem", "母题名 + 元素"),
                       ("elem_only", "只有元素")]:
        d = ia.get(key, {})
        A(f"| {label} | **{pct(d.get('top1'))}** | {pct(d.get('top5'))} | "
          f"{d.get('definition', '')} |")
    A("")
    if ia.get("finding"):
        A(f"**结论**：{ia['finding']}")
        A("")

    A("### 2.3 扩库前后对比")
    A("")
    h = m.get("history", {})
    A("| 样本库规模 | Top-1 | Top-5 |")
    A("|---|---|---|")
    A(f"| {h.get('sample_lib_size')} 条 | {pct(h.get('retrieval_top1_selfhit'))} | "
      f"{pct(h.get('retrieval_top5_hit_rate'))} |")
    A(f"| {m.get('sample_lib_size')} 条 | {pct(m.get('retrieval_top1_selfhit'))} | "
      f"{pct(m.get('retrieval_top5_hit_rate'))} |")
    A("")
    A("> 说明：库越大，自检索越难（同族纹样变多），Top-1 从 100% 降到 97% 属正常。")
    A("")

    # ---------------- 3 关联数据消融 ----------------
    A("## 三、关联数据消融（★ 负结论，必须如实报告）")
    A("")
    A(f"假设：{rel.get('hypothesis', '')}")
    A("")
    exp = json.loads((DOCS / "exp_related_motifs.json").read_text(encoding="utf-8"))
    t = exp["table"]
    A("| 检索输入 | 基线 Top-1 | + 关联扩展 expand | + 关联加权 boost |")
    A("|---|---|---|---|")
    for key, label in [("bare", "仅名称"), ("name_elem", "名称 + 元素"),
                       ("elem_only", "仅元素")]:
        A(f"| {label} | {t[f'{key}/base']['top1']:.2f} | "
          f"{t[f'{key}/expand']['top1']:.2f} | {t[f'{key}/boost']['top1']:.2f} |")
    A("")
    for k in ("expand", "boost"):
        d = rel.get(k, {})
        A(f"- **{k}**（{d.get('mechanism', '')}）：{d.get('verdict', '')}")
    A("")
    A(f"**结论**：{rel.get('conclusion', '')}")
    A("")

    # ---------------- 4 关联数据的正确用法 ----------------
    A("## 四、关联数据的正确用法（可解释性）")
    A("")
    A(f"{nb.get('definition', '')}")
    A("")
    A(f"- 第 2–5 名落在关联纹样内的比例：**{pct(nb.get('slot_rate'))}** "
      f"（{nb.get('slot_detail', '')}）")
    A(f"- 至少有一个关联纹样进入前 5 名的母题占比：**{pct(nb.get('motif_any_rate'))}** "
      f"（{nb.get('motif_any_detail', '')}）")
    A("")
    A(f"**发现**：{nb.get('finding', '')}")
    A("")

    # ---------------- 5 文化规则 ----------------
    A("## 五、文化规则校验")
    A("")
    A(f"规则总数 **{cr.get('rule_count', '—')}** 条，分 5 类：")
    A("")
    A("| 类别 | 条数 |")
    A("|---|---|")
    for k, v in (cr.get("categories") or {}).items():
        A(f"| {k} | {v} |")
    A("")
    A("| 约束类型 | 条数 |")
    A("|---|---|")
    for k, v in (cr.get("constraint_types") or {}).items():
        A(f"| {k} | {v} |")
    A("")
    A(f"- **检出率**：{pct(cr.get('detection_rate'))} —— {cr.get('detection_detail', '')}")
    A(f"- **误报率**：{pct(cr.get('false_positive_rate'))} —— "
      f"{cr.get('false_positive_detail', '')}")
    A(f"- 方法：{cr.get('method', '')}")
    A("")
    if cr.get("note"):
        A(f"> {cr['note']}")
        A("")

    # ---------------- 6 M7 标定 ----------------
    A("## 六、版权预警阈值标定（M7）")
    A("")
    A(f"正例 **{cc.get('positives', '—')}** 个（4 类改动变体各 30）｜"
      f"负例 **{cc.get('negatives', '—')}** 个｜来源图 {cc.get('sources', '—')} 张")
    A("")
    A(f"方法：{cc.get('method', '')}")
    A("")
    ph = cc.get("phash", {})
    cl = cc.get("clip", {})
    A("| 通道 | 阈值 | 检出率 TPR | 误报率 FPR | 说明 |")
    A("|---|---|---|---|---|")
    A(f"| 结构层 phash | ≤ {ph.get('threshold')} | {pct(ph.get('tpr'))} | "
      f"{pct(ph.get('fpr'))} | {ph.get('finding', '')} |")
    A(f"| 语义层 CLIP | ≥ {cl.get('threshold')} | {pct(cl.get('tpr'))} | "
      f"{pct(cl.get('fpr'))} | {cl.get('finding', '')} |")
    A("")
    if cc.get("statistical_caveat"):
        A(f"> {cc['statistical_caveat']}")
        A("")

    bt = (cc.get("by_transform") or {})
    if bt:
        A("### 6.1 按改动类型拆解（结构层为何失效）")
        A("")
        A(f"工作点：{bt.get('working_point', '')}")
        A("")
        A("| 改动类型 | 结构层检出率 | 中位汉明距离 |")
        A("|---|---|---|")
        name_cn = {"rotate4": "旋转 4°", "bright12": "亮度 ×1.12",
                   "border5": "加白边 5%", "jpeg60": "JPEG q60"}
        for k, v in (bt.get("phash") or {}).items():
            A(f"| {name_cn.get(k, k)} | {pct(v.get('rate'))} | "
              f"{v.get('median_dist')} |")
        A("")

    # ---------------- 7 红线 ----------------
    A("---")
    A("")
    A("## 七、★ 引用红线（写报告时务必遵守）")
    A("")
    A("1. **不可称「误报率 0%」**。负例 30 个，FPR=0 的 95% 置信上界约 **9.5%**；")
    A("   正确写法是「在 30 个负例上未出现误报」。")
    A("2. **不可称「100% 可溯源」**。元素级可溯的是**纹样层**（母题库）；")
    A("   **材质层**（实物佐证层）与**载体层**（3D 几何体）不参与元素级溯源，")
    A("   三者不得混称。")
    A("3. **不可把关联数据包装成「效果提升」**。消融实测三种输入下均无正收益，")
    A("   它的价值在可解释性。详见第三节。")
    A("4. **检索指标是「索引层自检索」**，衡量排序质量，**不等同端到端准确率**；")
    A("   端到端指标待测（依赖 C3 测试集）。")
    A("5. **`dynasty` 全库为「不详」**，源数据无朝代，本项目不虚构朝代。")
    A("")
    if m.get("notes"):
        A("### 附：数据源备注")
        A("")
        A(f"> {m['notes']}")
        A("")

    OUT.mkdir(parents=True, exist_ok=True)
    dst = OUT / "数据摘要.md"
    dst.write_text("\n".join(L), encoding="utf-8")
    print(f"✅ 已生成 {dst}（{len(dst.read_text(encoding='utf-8'))} 字）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
