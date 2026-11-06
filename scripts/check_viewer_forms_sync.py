# scripts/check_viewer_forms_sync.py
"""形态集注册表一致性门卫（批次 2A，只读）。

★ 为什么必须有
    FORMS 在 `src/preview3d.py`，查看器是纯静态页，只能读 `forms.json`；
    还有一份 `static/viewer/` 运行时副本。任何一处漏改，页面照常打开、
    不报错，但「Python 里的形态」和「页面上的形态」不是同一套 —— 静默失效。

★ 断言
    ① `web/viewer.html` 与 `static/viewer/viewer.html` **字节全等**；
    ② `web/forms.json` 与 `static/viewer/forms.json` 字节全等；
    ③ 两份 html 的内置兜底键集合、forms.json 键集合、FORMS 键集合三者一致；
    ④ forms.json 内容与 `forms_registry()` 重算结果逐条一致（不许手写键值）；
    ⑤ `STRIP_ASPECT` / `FILL_MIN` 键集合也覆盖 FORMS 全部形态。

★ 反例注入（系统 temp，用完即删）
    `--static-html` 指向改过的副本 → ① FAIL；
    `--forms-json` 指向缺键的 JSON → ③ FAIL。
    本检查器纳入 3D 固定顺序的最后一步。

用法（工程根目录 work/ 下执行）：
    .venv/Scripts/python.exe scripts/check_viewer_forms_sync.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_WEB_HTML = ROOT / "web" / "viewer.html"
DEFAULT_STATIC_HTML = ROOT / "static" / "viewer" / "viewer.html"
DEFAULT_FORMS_JSON = ROOT / "web" / "forms.json"
DEFAULT_RUNTIME_JSON = ROOT / "static" / "viewer" / "forms.json"

_FALLBACK_BLOCK = re.compile(
    r"const\s+FALLBACK_FORMS\s*=\s*\[(.*?)\]\s*;", re.S)
_KEY = re.compile(r'key\s*:\s*"([A-Za-z0-9_]+)"')


def html_keys(text: str) -> tuple[str, ...] | None:
    """从查看器的内置兜底数组解析形态键；解析不到返回 None（不静默当通过）。"""
    m = _FALLBACK_BLOCK.search(text)
    if m is None:
        return None
    keys = tuple(_KEY.findall(m.group(1)))
    return keys or None


def json_keys(data: Any) -> tuple[str, ...] | None:
    """从注册表 JSON 解析形态键；结构非法返回 None。"""
    if not isinstance(data, list) or not data:
        return None
    if not all(isinstance(x, dict) and isinstance(x.get("key"), str) for x in data):
        return None
    return tuple(str(x["key"]) for x in data)


def _read(path: Path) -> bytes | None:
    """读字节；读不到返回 None，由调用方明确判失败。"""
    try:
        return Path(path).read_bytes()
    except OSError:
        return None


def verify(web_html: Path, static_html: Path,
           forms_json: Path, runtime_json: Path) -> tuple[bool, str]:
    """跑完五项断言，返回 (是否全过, 汇总说明)。"""
    problems: list[str] = []
    a, b = _read(web_html), _read(static_html)
    fj, rj = _read(forms_json), _read(runtime_json)

    if a is None or b is None:
        problems.append("viewer.html 缺文件")
    elif a != b:
        problems.append("两份 viewer.html 不再字节全等")
    if fj is None or rj is None:
        problems.append("forms.json 缺文件")
    elif fj != rj:
        problems.append("两份 forms.json 不再字节全等")

    from src.preview3d import FORMS, forms_registry

    expected = tuple(FORMS)
    parsed: dict[str, Any] = {}
    try:
        parsed = json.loads(fj.decode("utf-8")) if fj is not None else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        parsed = {}

    sources = (
        ("web/viewer.html 内置兜底", html_keys(a.decode("utf-8", "ignore")) if a else None),
        ("static/viewer/viewer.html 内置兜底",
         html_keys(b.decode("utf-8", "ignore")) if b else None),
        ("web/forms.json", json_keys(parsed)),
    )
    for label, keys in sources:
        if keys is None:
            problems.append(f"{label} 无法解析形态键")
        elif keys != expected:
            problems.append(f"{label} 键集合 {keys} ≠ FORMS {expected}")

    if parsed and parsed != forms_registry():
        problems.append("forms.json 内容与 FORMS 生成结果不一致（疑似手写/漏跑生成器）")

    from src.pattern_layout import STRIP_ASPECT
    from scripts.check_glb_uv import FILL_MIN

    for label, keys in (("STRIP_ASPECT", tuple(STRIP_ASPECT)),
                        ("FILL_MIN", tuple(FILL_MIN))):
        if set(keys) != set(expected):
            problems.append(f"{label} 键集合 {keys} 未覆盖 FORMS {expected}")

    if problems:
        return False, "；".join(problems[:8])
    return True, (f"{len(expected)} 个形态键一致（FORMS / 两份 viewer 兜底 / "
                  "两份 forms.json / STRIP_ASPECT / FILL_MIN）")


def main() -> int:
    ap = argparse.ArgumentParser(description="形态集注册表一致性门卫（只读）")
    ap.add_argument("--web-html", default=str(DEFAULT_WEB_HTML))
    ap.add_argument("--static-html", default=str(DEFAULT_STATIC_HTML))
    ap.add_argument("--forms-json", default=str(DEFAULT_FORMS_JSON))
    ap.add_argument("--runtime-forms-json", default=str(DEFAULT_RUNTIME_JSON))
    args = ap.parse_args()
    ok, msg = verify(Path(args.web_html), Path(args.static_html),
                     Path(args.forms_json), Path(args.runtime_forms_json))
    print("=" * 68)
    print("形态集注册表一致性 · 两份 viewer.html / forms.json / FORMS")
    print("=" * 68)
    print(f"[{'PASS' if ok else 'FAIL'}] {msg}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
