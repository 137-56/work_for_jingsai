# src/m1_intent.py
"""M1 意图解析：一句自然语言需求 → 结构化的《纹样文化配方》。

配方结构见 docs/schema.md §3。这个模块有两个关键设计（详细实现指南 1.5）：

  ① 母题白名单约束 —— LLM 会"编"出听着像、实际查不到的纹样名（比如"龙凤呈祥莲鹤纹"）。
     白名单把它的自由度限制在样本库里真实存在的母题上。这既是 M2 检索能命中的前提，
     也是"从源头抑制幻觉"这个卖点的技术落点。
  ② 三重容错 —— LLM 输出 JSON 不稳定（被 ```json 包住、前后带解释、字段缺失）。
     所以：正则提取 → 重试 3 次 → 兜底配方，任何一环失败都不让管线中断。

⚠️ 注意 intent.occasion 是**数组**（契约 §3.2），不是字符串。
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import dashscope
from dashscope import Generation

from src.utils import CFG

SAMPLES = Path(CFG["paths"]["samples"])

OCCASIONS = ["春节", "婚庆", "寿诞", "开业", "乔迁", "节庆通用", "日常陈设", "祭祀", "文人雅玩"]

SYSTEM_PROMPT = f"""你是中国传统纹样文化专家。用户会用一句话描述他想要的纹样，你要把它解析成一份结构化的《纹样文化配方》。

只输出 JSON，不要任何解释、不要 markdown 代码块。

JSON 结构（字段一个都不能少）：
{{
  "intent": {{
    "occasion": ["春节"],
    "purpose": "礼品包装",
    "blessing": ["连年有余", "吉祥"],
    "style": "传统窗花"
  }},
  "structure": {{
    "center_motif": {{ "name": "缠枝莲纹", "elements": ["莲花", "卷草", "藤蔓"] }},
    "border":   {{ "pattern": "回纹", "width_ratio": 0.15 }},
    "corner":   {{ "pattern": "如意角花" }},
    "symmetry": "四轴对称"
  }},
  "palette": {{
    "primary": "#C8102E",
    "secondary": "#F2A900",
    "scheme_basis": "传统点染配色"
  }}
}}

硬性要求：
1. center_motif.name 只能从下面给出的「可用母题」里选，禁止自创。
2. center_motif.elements 要与该母题在库中的构成元素一致。
3. intent.occasion 必须是数组，取值只能从：{'/'.join(OCCASIONS)}。
4. 每个寓意词都要能由中心母题推导出来（谐音、象征、典故）。
5. palette 用十六进制色值。
6. **选母题时，要看它的「适用场合」是否与用户需求匹配、「寓意」是否与用户诉求相符**
   —— 不要只按名字的字面联想。比如"祝寿"应该选场合含「寿诞」、寓意含「长寿」的母题。
7. border.pattern 和 corner.pattern **也必须从上面的「可用母题」里选**；
   如果找不到合适的，就留空字符串 ""，**不要自创**。

"""


# ---------------------------------------------------------------- 白名单
def build_whitelist():
    """从样本库提取真实母题名。除了类别和构成元素，还要带上
    「适用场合」和「寓意」—— 只有这样 LLM 才能按语义选母题，而不是靠名字字面猜。"""
    samples = json.loads(SAMPLES.read_text(encoding="utf-8"))
    return {s["name"]: {
        "category": s["category"],
        "elements": s.get("elements", []),
        "occasion": s.get("occasion", []),
        "meaning": s.get("meaning", ""),
    } for s in samples}


def render_user_prompt(user_request, whitelist):
    lines = []
    for n, v in whitelist.items():
        lines.append(
            f"- {n}（{v['category']}）｜适用场合：{'/'.join(v['occasion'])}"
            f"｜构成元素：{'、'.join(v['elements'])}\n"
            f"    寓意：{v['meaning']}"
        )
    return (f"用户需求：{user_request}\n\n"
            f"可用母题（**只能从中选择，不得自创**）：\n"
            + "\n".join(lines) + "\n\n请输出 JSON 配方。")



# ---------------------------------------------------------------- JSON 提取
def extract_json(text):
    """从 LLM 输出里抠出 JSON 对象。
    不要直接 json.loads —— 它可能被 ```json 包住，或前后带解释文字。"""
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)      # 去掉代码块包裹
    if m:
        text = m.group(1).strip()
    i, j = text.find("{"), text.rfind("}")                     # 截取第一个 { 到最后一个 }
    if i == -1 or j == -1 or j < i:
        raise ValueError("未找到 JSON 对象")
    return json.loads(text[i:j + 1])


# ---------------------------------------------------------------- 白名单事后校验
def _closest(name, whitelist):
    """在候选母题里找最像的。用「公共字符数 / 较长者长度」，不引入额外依赖。"""
    if not name:
        return None
    best, best_score = None, 0.0
    for cand in whitelist:
        inter = len(set(name) & set(cand))
        score = inter / max(len(set(name)), len(set(cand)))
        if score > best_score:
            best, best_score = cand, score
    return best if best_score >= 0.5 else None


def fix_motif(recipe, whitelist):
    """白名单事后校验：LLM 仍可能编母题，这里强制拉回真实值。
    同时用库里的真实 elements 覆盖 LLM 写的（它可能写近义词，会让 M2 的二次筛选失效）。"""
    st = recipe.setdefault("structure", {})
    cm = st.setdefault("center_motif", {})

    # ★ border / corner 必须在任何 return 之前校验：
    #   母题命中白名单时下面会提前 return，若把这段放在函数末尾就永远跑不到。
    for slot in ("border", "corner"):
        obj = st.setdefault(slot, {})
        pat = str(obj.get("pattern") or "").strip()
        if pat and pat not in whitelist:
            obj["pattern"] = ""
            recipe.setdefault("warnings", []).append(f"{slot}.pattern「{pat}」不在库中，已清空")

    name = str(cm.get("name") or "").strip()

    if name in whitelist:
        cm["elements"] = list(whitelist[name]["elements"])
        cm["confidence"] = 1.0
        return recipe

    best = _closest(name, whitelist)
    if best is None:
        best = next(iter(whitelist))
        cm["confidence"] = 0.0
        recipe.setdefault("warnings", []).append(f"母题「{name}」不在库中且无法修正，已回退到「{best}」")
    else:
        cm["confidence"] = 0.5
        recipe.setdefault("warnings", []).append(f"母题已修正：「{name}」→「{best}」（不在白名单内）")

    cm["name"] = best
    cm["elements"] = list(whitelist[best]["elements"])
    return recipe


# ---------------------------------------------------------------- 兜底
def fallback_recipe(user_request):
    """LLM 彻底失败时用它，保证管线不中断（指南 8.2 的降级要求）。"""
    return {
        "intent": {"occasion": ["节庆通用"], "purpose": "通用装饰",
                   "blessing": ["吉祥"], "style": "传统纹样"},
        "structure": {"center_motif": {"name": "", "elements": [], "confidence": 0.0},
                      "border": {}, "corner": {}, "symmetry": "四轴对称"},
        "palette": {"primary": "#C8102E", "secondary": "#F2A900",
                    "scheme_basis": "传统配色"},
        "user_request": user_request,
        "parsed_by": "fallback",
    }


# ---------------------------------------------------------------- 主入口
def parse_intent(user_request):
    """一句话 → 配方 dict。永远返回一个可用对象，不抛异常。"""
    whitelist = build_whitelist()
    cfg = CFG["llm"]
    dashscope.api_key = os.environ.get("DASHSCOPE_API_KEY", "")

    for attempt in range(1, cfg["max_retries"] + 1):
        try:
            resp = Generation.call(
                model=cfg["model"],
                messages=[{"role": "system", "content": SYSTEM_PROMPT},
                          {"role": "user", "content": render_user_prompt(user_request, whitelist)}],
                temperature=cfg["temperature"],      # 0.2：需要稳定 JSON，不能高
                result_format="message",
                timeout=cfg["timeout"],
            )
            if resp.status_code != 200:
                print(f"  [M1] 第 {attempt} 次失败：status={resp.status_code} {getattr(resp, 'message', '')}")
                continue
            raw = resp.output.choices[0].message.content
            recipe = extract_json(raw)
            recipe = fix_motif(recipe, whitelist)     # ★ 事后校验修正
            recipe["user_request"] = user_request     # 原样保存，用于报告展示与问题复现
            recipe["parsed_by"] = "llm"
            return recipe
        except Exception as e:
            print(f"  [M1] 第 {attempt} 次失败：{type(e).__name__}: {e}")

    r = fallback_recipe(user_request)
    r["warnings"] = [f"LLM 重试 {cfg['max_retries']} 次仍失败，已使用兜底配方"]
    return r


if __name__ == "__main__":
    req = " ".join(sys.argv[1:]) or "做一个有吉祥寓意的窗花，用于春节礼品包装"
    out = parse_intent(req)
    print(json.dumps(out, ensure_ascii=False, indent=2))
