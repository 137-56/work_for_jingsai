# tests/test_retrieval.py
"""M2 元素检索（src/m2_retrieve.py）的单元测试。

被测对象是 retrieve() 的「多查询融合 → 二次筛选重排 → 槽位保底 → 截断」链路。
这一层是纯逻辑；真实 CLIP 编码与 faiss 索引属于外部重依赖（模型权重、建索引
产物，换机不一定齐备），因此用 unittest.mock 把它们替换成确定性替身：

  * ``_load_index``  → 返回由真实样本 id 组成的候选池 + 固定分数；
  * ``encode_text``  → 返回占位向量（替身索引不读它的内容）。

替身里的 id **全部取自 data/samples.json 的真实 100 条**，所以「命中 id 都在
库内」是对真实数据的断言，不是自造数据自验。导入统一走 ``from src.m2_retrieve
import ...``，patch 目标也用同一模块路径，避免混用导入加载出两份模块对象。

覆盖三类契约：
  1. top_k=10 时返回条数恰好 10（不传 top_k 时默认配置同样是 10）；
  2. 每条命中的 id 都属于 data/samples.json 的 100 条，且带 name/source/license；
  3. 槽位保底：border/corner 命中的样本即便分数最低，也一定出现在结果里并带
     slot 标记；并用对照用例证明「不保底就会被挤出」。

运行（在工程根目录 work/ 下）：
    .venv/Scripts/python.exe -m unittest tests.test_retrieval -v
    .venv/Scripts/python.exe tests/test_retrieval.py
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:                      # 允许从任意工作目录运行
    sys.path.insert(0, str(ROOT))

from src.m2_retrieve import (                      # noqa: E402
    build_queries,
    retrieve,
    _load_samples,
)

SAMPLES_PATH = ROOT / "data" / "samples.json"


class _FakeTensor:
    """encode_text() 返回值的替身：只需 .numpy() 给出 float32 数组。"""

    def numpy(self) -> np.ndarray:
        """返回全零占位向量；替身索引不读取它的内容。"""
        return np.zeros((1, 512), dtype="float32")


class _FakeIndex:
    """faiss 索引替身：忽略查询向量，返回构造时给定的 (D, I)。"""

    def __init__(self, scores: list, indices: list) -> None:
        self._distances = np.array([scores], dtype="float32")
        self._indices = np.array([indices], dtype="int64")

    def search(self, vec, k: int):
        """模拟 index.search：固定返回 (1, n) 的距离与下标矩阵。"""
        return self._distances, self._indices


class _RetrieveFixture:
    """把 12 个真实样本装进候选池：前 10 个高分，后 2 个分数极低。

    低分的两条用作 border / corner 槽位命中项；按分数排序它们必然排在
    第 11、12 位，正好验证槽位保底「把被挤掉的槽位捞回来」的行为。
    """

    def __init__(self) -> None:
        with SAMPLES_PATH.open(encoding="utf-8") as f:
            self.samples = json.load(f)
        self.all_ids = {s["id"] for s in self.samples}
        picked = self.samples[:12]
        self.high = picked[:10]
        self.border = picked[10]
        self.corner = picked[11]
        self.id_order = [s["id"] for s in picked]
        # 前 10 条分数递减，两条槽位样本给极低分 —— 无保底时必被挤出前 10。
        scores = [0.90 - 0.01 * i for i in range(10)] + [0.10, 0.09]
        self.index = _FakeIndex(scores, list(range(len(picked))))

    def patches(self):
        """返回两个 patcher：替换外部重依赖，保持其它逻辑真实。"""
        return (
            patch("src.m2_retrieve._load_index",
                  return_value=(self.index, list(self.id_order))),
            patch("src.m2_retrieve.encode_text", return_value=_FakeTensor()),
        )

    def recipe(self, with_slots: bool) -> dict:
        """构造配方：中心母题取真实样本名，elements 留空以关闭重排加分干扰。"""
        motif = self.high[0]
        recipe = {
            "intent": {"occasion": list(motif.get("occasion") or [])[:1],
                       "purpose": "单元测试"},
            "structure": {"center_motif": {"name": motif["name"], "elements": []}},
        }
        if with_slots:
            recipe["structure"]["border"] = {"pattern": self.border["name"]}
            recipe["structure"]["corner"] = {"pattern": self.corner["name"]}
        return recipe


class RetrievalContractTest(unittest.TestCase):
    """M2 检索的三类契约断言。"""

    def setUp(self) -> None:
        self.fx = _RetrieveFixture()
        p_index, p_encode = self.fx.patches()
        p_index.start()
        p_encode.start()
        self.addCleanup(p_index.stop)
        self.addCleanup(p_encode.stop)

    # ---- 契约 1：返回条数 ----

    def test_top_k_10_returns_exactly_10_rows(self):
        rows = retrieve(self.fx.recipe(with_slots=False), top_k=10)
        self.assertEqual(len(rows), 10,
                         f"top_k=10 应恰好返回 10 条，实际 {len(rows)} 条")

    def test_default_top_k_from_config_is_10(self):
        rows = retrieve(self.fx.recipe(with_slots=False))
        self.assertEqual(len(rows), 10,
                         f"默认 top_k 应取 config.yaml 的 10，实际 {len(rows)} 条")

    # ---- 契约 2：命中 id 都在 100 条样本内 ----

    def test_fixture_samples_are_exactly_100(self):
        # 防止测试样本本身随数据变动而静默失真
        self.assertEqual(len(self.fx.samples), 100)
        self.assertEqual(len(self.fx.all_ids), 100, "样本 id 必须全局唯一")

    def test_every_hit_id_belongs_to_the_100_samples(self):
        rows = retrieve(self.fx.recipe(with_slots=True), top_k=10, debug=True)
        self.assertTrue(rows)
        for r in rows:
            self.assertIn(r["sample"]["id"], self.fx.all_ids,
                          f"检索返回了样本库之外的 id：{r['sample']['id']}")
            self.assertEqual(r["name"], r["sample"]["name"])
            self.assertTrue(r["source"], "每条结果必须带出处")
            self.assertTrue(r["license"], "每条结果必须带授权")

    # ---- 契约 3：槽位保底 ----

    def test_slot_guarantee_keeps_low_score_border_and_corner(self):
        rows = retrieve(self.fx.recipe(with_slots=True), top_k=10, debug=True)
        by_id = {r["sample"]["id"]: r for r in rows}
        self.assertIn(self.fx.border["id"], by_id, "border 命中项被挤掉了")
        self.assertIn(self.fx.corner["id"], by_id, "corner 命中项被挤掉了")
        self.assertEqual(by_id[self.fx.border["id"]].get("slot"), "border")
        self.assertEqual(by_id[self.fx.corner["id"]].get("slot"), "corner")

    def test_slot_guarantee_overrides_score_ranking(self):
        # 保底之所以必要：被保底的槽位项分数明明低于榜上所有其它项。
        rows = retrieve(self.fx.recipe(with_slots=True), top_k=10, debug=True)
        pinned = [r for r in rows if r.get("slot") in ("border", "corner")]
        others = [r for r in rows if r.get("slot") not in ("border", "corner")]
        self.assertEqual(len(pinned), 2)
        self.assertTrue(others)
        self.assertLess(max(r["clip_similarity"] for r in pinned),
                        min(r["clip_similarity"] for r in others),
                        "槽位项分数并未更低，保底机制没有被真正触发")

    def test_without_slot_guarantee_low_score_slots_are_dropped(self):
        # 对照组：不声明 border/corner 时，两条低分项确实进不了前 10。
        # 与上一条合起来证明「低分项出现在结果里」是保底机制的效果，而非巧合。
        rows = retrieve(self.fx.recipe(with_slots=False), top_k=10, debug=True)
        ids = {r["sample"]["id"] for r in rows}
        self.assertNotIn(self.fx.border["id"], ids)
        self.assertNotIn(self.fx.corner["id"], ids)

    # ---- 补充：查询构造与空配方 ----

    def test_build_queries_prepends_category(self):
        _, _, by_name = _load_samples()
        recipe = self.fx.recipe(with_slots=False)
        queries = build_queries(recipe, by_name)
        name = recipe["structure"]["center_motif"]["name"]
        cat = by_name[name]["category"]
        self.assertTrue(queries)
        self.assertEqual(queries[0], f"{cat}：{name}",
                         "首条查询必须带类别前缀（M2 第 ① 招）")

    def test_empty_recipe_returns_no_rows(self):
        empty = {"intent": {}, "structure": {"center_motif": {}}}
        self.assertEqual(build_queries(empty, {}), [])
        self.assertEqual(retrieve(empty, top_k=10), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
