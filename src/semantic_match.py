# src/semantic_match.py
"""确定性语义匹配（整合点 ①）：用主工程 100 条真源给出可复现、可解释的匹配理由。

设计前提（架构师方案 v2「合能力、不合实现；合机制、不合数据」）：
  * 本模块**不参与** M2 主检索排序 —— m2_retrieve.py 仍是 encode_text +
    index.search + 槽位保底。它只在两处旁路消费：M1 全部重试失败时的兜底，
    以及对已产出 hits 补一列「理由」，不覆盖 score、不改动 matched_by、不重排。
  * 候选池、以及类别 / 载体 / 寓意等各维度候选词，全部从 data/samples.json
    的现值域现算，不引入任何外部词表、也不引入任何人工同义映射。
  * 全流程不使用任何随机化手段、不对候选做顺序打乱；相同输入恒得相同输出，
    因此可作为回归断言（scripts/check_merge_contract.py 第 ⑧ 项）的对象。
  * 真源 dynasty 字段全为「不详」，无区分度，故不纳入匹配维度。

五个维度的权重见 _WEIGHTS；候选词切分见 _cjk_ngrams / _dimension_tokens。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from src.run_source import load_samples

# 主工程真源 id 形态统一为 WENYANG-<数字>；用它过滤候选池。
_ID_RE = re.compile(r"WENYANG-\d+")

# 五维权重：名称最重、寓意最轻。命中该维度即计入对应整数权重。
_WEIGHTS: dict[str, int] = {
    "name": 60,
    "element": 30,
    "category": 15,
    "carrier": 20,
    "meaning": 8,
}
_DIM_CN: dict[str, str] = {
    "name": "母题名", "element": "构成元素", "category": "类别",
    "carrier": "载体", "meaning": "寓意",
}
_NO_HIT_REASON = "未直接命中语义维度；按真源候选池顺序保底"

# 中文串切分：按非汉字字符断开，取 2~4 字连续片段。所有片段都源自真源文本。
_NON_CJK = re.compile(r"[^\u4e00-\u9fff]+")

# 兜底配方的默认传统色值（与基线兜底配方一致；界面层的色板约束由
# CFG.traditional_palette 提供，见 app.py 的配方编辑表单）。
_DEFAULT_PRIMARY = "#C8102E"
_DEFAULT_SECONDARY = "#F2A900"


@dataclass(frozen=True)
class MatchHit:
    """一条确定性语义匹配结果。

    Attributes:
        id: 真源样本 id（恒为 WENYANG-<数字>）。
        name: 真源母题名。
        score: 五维权重命中的整数和。
        reasons: 命中理由的不可变快照，保证结果可比较、可哈希。
    """

    id: str
    name: str
    score: int
    reasons: tuple[str, ...]


def _cjk_ngrams(text: str) -> set[str]:
    """把一段真源文本切成 2~4 字连续汉字片段，作为候选词集合。

    不依赖任何分词库或外部词表；切分结果完全由输入文本决定，因而确定。
    """
    out: set[str] = set()
    for seg in _NON_CJK.split(text or ""):
        n = len(seg)
        if n < 2:
            continue
        out.add(seg)
        for size in (2, 3, 4):
            if size <= n:
                for i in range(n - size + 1):
                    out.add(seg[i:i + size])
    return out


def _field_values(sample: dict[str, Any], dim: str) -> list[str]:
    """取单条样本在某维度的原始字段值（真源现值），不做任何人工补词。"""
    if dim == "name":
        raw = [sample.get("name")]
    elif dim == "category":
        raw = [sample.get("category")]
    elif dim == "meaning":
        raw = [sample.get("meaning")]
    elif dim == "element":
        raw = list(sample.get("elements") or [])
    elif dim == "carrier":
        raw = list(sample.get("carrier") or [])
    else:
        raw = []
    return [str(x) for x in raw if x]


def _dimension_tokens(sample: dict[str, Any], dim: str) -> set[str]:
    """单条样本在某维度的候选词：字段值本身 + 从字段值现算的汉字片段。"""
    out: set[str] = set()
    for v in _field_values(sample, dim):
        out.add(v)
        out |= _cjk_ngrams(v)
    return out


@lru_cache(maxsize=1)
def _pool() -> tuple[dict[str, Any], ...]:
    """真源候选池：data/samples.json 中 id 形态为 WENYANG-<数字> 的条目。"""
    data = load_samples()
    return tuple(
        s for s in data
        if isinstance(s, dict) and _ID_RE.fullmatch(str(s.get("id") or ""))
    )


def _domain_from(pool: tuple[dict[str, Any], ...]) -> dict[str, set[str]]:
    """从候选池现算各维度全局值域（候选词全集），绝不硬编码词表。"""
    dom: dict[str, set[str]] = {d: set() for d in _WEIGHTS}
    for s in pool:
        for d in _WEIGHTS:
            dom[d] |= _dimension_tokens(s, d)
    return dom


@lru_cache(maxsize=1)
def _domain() -> dict[str, set[str]]:
    """真源候选池的全局值域（缓存）。"""
    return _domain_from(_pool())


def _hit_tokens(req: str, domain: dict[str, set[str]]) -> dict[str, frozenset[str]]:
    """请求命中了值域里的哪些候选词 —— 值域现算、命中集合确定。"""
    return {
        d: frozenset(t for t in domain[d] if t and t in req)
        for d in _WEIGHTS
    }


def score_request(req: str, samples: list | None = None) -> list[MatchHit]:
    """对候选池做确定性语义打分，返回按 (分数降序, id 升序) 排序的全量结果。

    Args:
        req: 用户的一句自然语言需求。
        samples: 可选的候选池注入，仅用于测试 / 反例；默认 None 表示读真源
            data/samples.json（经 src.run_source.load_samples）。

    Returns:
        全量 MatchHit 列表；id 升序作为同分时的确定性 tie-break，
        因此相同输入两次调用结果恒等。
    """
    query = str(req or "")
    if samples is None:
        pool = _pool()
        domain = _domain()
    else:
        pool = tuple(
            s for s in (samples or [])
            if isinstance(s, dict) and _ID_RE.fullmatch(str(s.get("id") or ""))
        )
        domain = _domain_from(pool)
    req_hits = _hit_tokens(query, domain)

    out: list[MatchHit] = []
    for s in pool:
        score = 0
        reasons: list[str] = []
        for dim, weight in _WEIGHTS.items():
            common = sorted(_dimension_tokens(s, dim) & req_hits[dim])
            if not common:
                continue
            score += weight
            shown = common[:3]
            suffix = f" 等 {len(common)} 项" if len(common) > 3 else ""
            reasons.append(f"{_DIM_CN[dim]}命中「{'、'.join(shown)}」{suffix}")
        if not reasons:
            reasons.append(_NO_HIT_REASON)
        out.append(MatchHit(
            id=str(s["id"]),
            name=str(s.get("name") or ""),
            score=score,
            reasons=tuple(reasons),
        ))
    out.sort(key=lambda h: (-h.score, h.id))
    return out


def explain_hits(req: str, hits: list) -> list[dict[str, Any]]:
    """给每条检索命中新增一个 ``semantic`` 键（理由列表），仅此而已。

    逐条浅拷贝，不改动入参、不改动 score、不改动 matched_by、不改动顺序；
    返回的列表与原 hits 等长且同序。

    Args:
        req: 用于计算理由的用户需求。
        hits: m2_retrieve.retrieve() 产出的 dict 列表。

    Returns:
        每条都带 ``semantic`` 键的新 dict 列表。
    """
    by_id = {h.id: list(h.reasons) for h in score_request(req)}
    out: list[dict[str, Any]] = []
    for h in hits or []:
        row = dict(h)
        sid = str((h.get("sample") or {}).get("id") or "")
        row["semantic"] = list(by_id.get(sid, [_NO_HIT_REASON]))
        out.append(row)
    return out


def semantic_fallback_recipe(user_request: str, whitelist: dict) -> dict:
    """M1 全部重试失败时的确定性兜底配方。

    取 score_request 的 Top1 真源，填 center_motif.name / elements /
    intent.occasion；center_motif.name 强制落在白名单内；并写入
    ``parsed_by="fallback_semantic"`` 与 ``match_trace`` 以便追溯。

    Args:
        user_request: 原始需求。
        whitelist: m1_intent.build_whitelist() 的母题白名单（调用方传入，
            本模块不反向依赖 m1_intent，避免循环导入）。

    Returns:
        结构完整的配方 dict，可直接交给 M2→M3→M6 消费。
    """
    hits = score_request(user_request)
    top = hits[0] if hits else None
    by_id = {str(s["id"]): s for s in _pool()}
    top_sample = by_id.get(top.id) if top else None

    name = top.name if top else ""
    if name not in whitelist:
        name = next(iter(whitelist)) if whitelist else ""

    if top_sample is not None:
        elements = list(top_sample.get("elements") or [])
        occasion = list(top_sample.get("occasion") or []) or ["节庆通用"]
    else:
        elements = list((whitelist.get(name) or {}).get("elements") or [])
        occasion = list((whitelist.get(name) or {}).get("occasion") or []) or ["节庆通用"]

    return {
        "intent": {"occasion": occasion, "purpose": "通用装饰",
                   "blessing": ["吉祥"], "style": "传统纹样"},
        "structure": {
            "center_motif": {"name": name, "elements": elements, "confidence": 0.0},
            "border": {}, "corner": {}, "symmetry": "四轴对称",
        },
        "palette": {"primary": _DEFAULT_PRIMARY, "secondary": _DEFAULT_SECONDARY,
                    "scheme_basis": "传统配色"},
        "user_request": user_request,
        "parsed_by": "fallback_semantic",
        "match_trace": {
            "engine": "semantic_match.score_request",
            "pool_size": len(_pool()),
            "top_id": top.id if top else "",
            "top_name": top.name if top else "",
            "top_score": top.score if top else 0,
            "top_reasons": list(top.reasons) if top else [],
            "whitelist_applied": bool(name in whitelist),
        },
    }
