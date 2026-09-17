# scripts/smoke_m1.py
"""A7 验收：跑 20 个不同请求，统计三项指标。

  ① 结构完整率 —— 配方里有 occasion 也有母题名
  ② 白名单合规率 —— 母题必须是样本库里真实存在的
  ③ 场合匹配率 —— 选中母题在库内标注的 occasion，是否与请求期望的场合有交集
                  ★ 这一项才是真正反映 M1 好坏的指标

为什么不用同一个请求跑 20 遍：temperature=0.2 下 LLM 输出是确定的，
同一请求跑 N 遍得到的是同一个结果，等于只测了 1 个输入。

用法（在工程根目录 work/ 下执行）：
    .venv/Scripts/python.exe scripts/smoke_m1.py          # 全部 20 条
    .venv/Scripts/python.exe scripts/smoke_m1.py 5        # 只跑前 5 条（省 token）
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.m1_intent import build_whitelist, parse_intent

# 「节庆通用」在契约词表里的含义就是"各类节庆场合都适用"，
# 所以库内标了它的母题，应该与任何节庆类场合都算匹配（但不含祭祀/文人雅玩/日常陈设）。
FESTIVE = {"春节", "婚庆", "寿诞", "开业", "乔迁", "节庆通用"}

# (请求, 期望场合) —— 期望场合用于第 ③ 项检查
REQUESTS = [
    ("做一个有吉祥寓意的窗花，用于春节礼品包装", {"春节"}),
    ("设计一款适合婚礼的喜服刺绣纹样",           {"婚庆"}),
    ("给长辈做一张祝寿的贺卡纹样",               {"寿诞"}),
    ("需要一套适合茶饮包装的古典花纹",           {"节庆通用", "日常陈设"}),
    ("家里客厅想挂一幅清雅的装饰画纹样",         {"文人雅玩", "日常陈设"}),
    ("做一款新年红包上的烫金纹样",               {"春节"}),
    ("婚庆请柬的背景底纹",                       {"婚庆"}),
    ("寿宴餐具的环绕边饰",                       {"寿诞"}),
    ("新店开业的门头装饰纹样",                   {"开业"}),
    ("搬新家送礼的包装纸图案",                   {"乔迁"}),
    ("中秋礼盒的盖面纹样",                       {"节庆通用"}),
    ("祠堂牌位的边饰纹样",                       {"祭祀"}),
    ("书房笔筒的刻花纹样",                       {"文人雅玩"}),
    ("冬季围巾的提花图案",                       {"日常陈设"}),
    ("春节灯笼上的剪纸纹样",                     {"春节"}),
    ("嫁衣领口的金线纹样",                       {"婚庆"}),
    ("生日蛋糕包装的寿字纹样",                   {"寿诞"}),
    ("开业花篮卡片上的吉祥纹",                   {"开业"}),
    ("端午香囊的绣花纹样",                       {"节庆通用"}),
    ("文人扇面上的折枝花卉",                     {"文人雅玩"}),
]


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else len(REQUESTS)
    cases = REQUESTS[:n]
    wl = build_whitelist()          # dict: 母题名 -> {category, elements, occasion, meaning}

    ok_struct = ok_wl = ok_occ = 0
    for i, (req, want_occ) in enumerate(cases, 1):
        r = parse_intent(req)
        name = ((r.get("structure") or {}).get("center_motif") or {}).get("name") or ""
        occ = (r.get("intent") or {}).get("occasion") or []
        lib_occ = set(wl.get(name, {}).get("occasion") or [])

        s_ok = bool(occ) and bool(name)                 # ① 结构完整
        w_ok = name in wl                               # ② 白名单合规
        # ③ 场合匹配：库内场合与期望有交集；若库内标了「节庆通用」，
        #    则与任何节庆类期望都算匹配（这就是"通用"的意思）
        if lib_occ & want_occ:
            o_ok = True
        elif "节庆通用" in lib_occ and (want_occ & FESTIVE):
            o_ok = True
        else:
            o_ok = False
        ok_struct += s_ok
        ok_wl += w_ok
        ok_occ += o_ok

        mark = "✅" if (s_ok and w_ok and o_ok) else ("⚠️" if (s_ok and w_ok) else "❌")
        warn = ("  ⚠ " + "；".join(r["warnings"])) if r.get("warnings") else ""
        print(f"  {i:>2}. {mark} 母题={name:<9}"
              f"│配方场合={'/'.join(occ):<16}"
              f"│库内场合={'/'.join(sorted(lib_occ)):<16}"
              f"│期望={'/'.join(sorted(want_occ))}{warn}")

    N = len(cases)
    print(f"\n=== ① 结构完整率 {ok_struct}/{N} = {ok_struct/N:.0%}"
          f"｜② 白名单合规率 {ok_wl}/{N} = {ok_wl/N:.0%}"
          f"｜③ 场合匹配率 {ok_occ}/{N} = {ok_occ/N:.0%} ===")

    ok = ok_struct / N >= 0.9 and ok_wl / N >= 1.0
    print("[PASS] A7 通过（结构 + 白名单）" if ok
          else "[FAIL] 结构完整率或白名单合规率不达标")

    if ok and ok_occ / N < 0.8:
        print(f"\n[注意] 场合匹配率偏低（{ok_occ/N:.0%}）。两种可能，先分清是哪一种：")
        print("       · 母题选错了 → 改 m1_intent.py 的 SYSTEM_PROMPT / render_user_prompt")
        print("       · 库里没有适配该场合的母题 → 是样本库覆盖问题，不是 M1 的问题（扩库可解）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
