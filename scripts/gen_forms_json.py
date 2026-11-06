# scripts/gen_forms_json.py
"""由 `src.preview3d.FORMS` **生成**形态集注册表，禁止手写键值。

★ 为什么必须有生成器
    查看器是纯静态页，import 不了 Python；而 FORMS 又是唯一的形态真源。
    若让人手抄一份 JSON，形态集一变就会出现「Python 有三个形态、页面只有两个」
    的静默失效。这里只把 `forms_registry()` 的返回值落盘，不写任何形态名。

★ 两份产物
    web/forms.json              —— 双击 web/viewer.html 的离线展廊用；
    static/viewer/forms.json    —— Streamlit iframe 的运行时副本。
    两者**字节全等**，由 scripts/check_viewer_forms_sync.py 断言。

用法（工程根目录 work/ 下执行）：
    .venv/Scripts/python.exe scripts/gen_forms_json.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.preview3d import FORMS, forms_registry   # noqa: E402

WEB_FORMS = ROOT / "web" / "forms.json"
STATIC_FORMS = ROOT / "static" / "viewer" / "forms.json"


def build_payload() -> bytes:
    """从唯一真源构造 JSON 字节；键集合与 FORMS 不一致直接抛错。"""
    registry = forms_registry()
    keys = tuple(item["key"] for item in registry)
    if keys != tuple(FORMS):
        raise ValueError(
            f"注册表键集合 {keys} 与 FORMS {tuple(FORMS)} 不一致")
    return (json.dumps(registry, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def main() -> int:
    try:
        payload = build_payload()
    except (KeyError, ValueError) as e:
        print(f"[FAIL] 形态注册表生成失败：{type(e).__name__}: {e}")
        return 1
    for path in (WEB_FORMS, STATIC_FORMS):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)        # 同一份字节，保证两份全等
    print(f"[PASS] 形态注册表已由 FORMS 生成：{len(json.loads(payload))} 个形态")
    for item in json.loads(payload):
        print(f"  {item['key']:<8} {item['label']}  elev={item['elev']} dist={item['dist']}")
    print(f"  → {WEB_FORMS.relative_to(ROOT).as_posix()}")
    print(f"  → {STATIC_FORMS.relative_to(ROOT).as_posix()}（字节全等）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
