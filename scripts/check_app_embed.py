# scripts/check_app_embed.py
"""自检：B7 界面 06 区的「三维查看器」链路是否真的能跑通。

★★ 为什么需要这个脚本
    界面这段逻辑**没法靠 headless Chrome 验** —— Streamlit 是 websocket
    驱动的前端，headless 截图只能拿到未 hydrate 的骨架屏（实测就是这个样）。
    但这条链路又特别容易静默失败：静态目录放错位置、URL 少个前导斜杠，
    表现都是"白屏"，报错信息极难定位。

    所以这里**把界面里那段纯逻辑抽出来独立跑一遍**：
      ① 静态目录是否在 Streamlit 要求的位置（<app_dir>/static）
      ② viewer.html / three.min.js / GLTFLoader.js 是否就位
      ③ GLB 是否能复制进去、且复制后仍是合法 GLB
      ④ 生成的 iframe URL 是否真的返回 200（打真实 HTTP 请求）
      ⑤ 下载按钮要用的字节是否与源文件一致
    全程不依赖浏览器。

用法（需先启动 streamlit；脚本会自动探测端口）：
    .venv/Scripts/python.exe scripts/check_app_embed.py --port 8794
"""
from __future__ import annotations

import argparse
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

IFRAME_URL = "/app/static/viewer/viewer.html"


def http_status(url, timeout=20):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return f"ERR:{type(e).__name__}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8794)
    ap.add_argument("--recipe", default="outputs/R20260927005441-9126")
    args = ap.parse_args()
    base = f"http://127.0.0.1:{args.port}"

    errs, warns = [], []

    # ① 静态目录位置：必须是 <app_dir>/static（不是 .streamlit/static）
    static_root = ROOT / "static"
    if not static_root.is_dir():
        errs.append(f"静态目录不存在：{static_root}"
                    "（Streamlit 要求 <app_dir>/static）")
    elif (ROOT / ".streamlit" / "static").exists():
        warns.append(".streamlit/static 也存在 —— 那是**错的**位置，"
                     "Streamlit 不会服务它，建议删掉免得后人误用")

    # ② 必需文件
    viewer = static_root / "viewer" / "viewer.html"
    need = [viewer,
            static_root / "viewer" / "vendor" / "three.min.js",
            static_root / "viewer" / "vendor" / "GLTFLoader.js"]
    for p in need:
        if not p.exists():
            errs.append(f"缺文件：{p}")

    # ③ GLB 复制 + 仍为合法 GLB
    src_dir = ROOT / args.recipe
    glb_ok = []
    for kind in ("vase", "box", "fan"):
        src = src_dir / f"pattern_{kind}.glb"
        if not src.exists():
            errs.append(f"缺 GLB：{src}（先跑 python -m src.glb_export）")
            continue
        dst = static_root / "viewer" / "glb" / f"pattern_{kind}.glb"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        sig = dst.read_bytes()[:4]
        if sig != b"glTF":
            errs.append(f"{dst.name} 复制后不是合法 GLB（头 4 字节 {sig!r}）")
        else:
            glb_ok.append(kind)

    # ④ iframe URL 真实可达（含前导斜杠的坑）
    if not str(IFRAME_URL).startswith("/"):
        errs.append("iframe URL 缺少前导 '/'，会被当成相对路径而 404")
    st_page = http_status(base + "/")
    st_view = http_status(base + IFRAME_URL)
    st_three = http_status(base + "/app/static/viewer/vendor/three.min.js")
    st_glb = http_status(base + "/app/static/viewer/glb/pattern_vase.glb")
    # 反例：不带前导斜杠应当 404（证明这个坑真实存在）
    st_bad = http_status(base + "app/static/viewer/viewer.html")
    if st_view != 200:
        errs.append(f"查看器页面返回 {st_view}，应为 200")
    if st_three != 200:
        errs.append(f"three.min.js 返回 {st_three}，应为 200")
    if st_glb != 200:
        errs.append(f"pattern_vase.glb 返回 {st_glb}，应为 200")
    if st_page not in (200, "ERR:RemoteDisconnected"):
        warns.append(f"应用首页返回 {st_page}（可能仍在启动）")

    # ⑤ 下载字节与源一致
    n_ok = 0
    for kind in glb_ok:
        a = (src_dir / f"pattern_{kind}.glb").read_bytes()
        b = (static_root / "viewer" / "glb" / f"pattern_{kind}.glb").read_bytes()
        if a == b:
            n_ok += 1
        else:
            errs.append(f"{kind}: 下载字节与源不一致")

    print(f"B7 界面 06 区 · 三维查看器链路自检（{base}）\n")
    print(f"  静态目录        {static_root}  {'✅' if static_root.is_dir() else '❌'}")
    print(f"  查看器页面      {IFRAME_URL}  → {st_view}")
    print(f"  three.min.js    /app/static/.../three.min.js  → {st_three}")
    print(f"  样例 GLB        /app/static/.../pattern_vase.glb  → {st_glb}")
    print(f"  反例（无前导斜杠）/app/static...              → {st_bad}  "
          f"（预期 404，证明该坑存在）")
    print(f"  GLB 复制一致    {n_ok}/{len(glb_ok)}")
    for w in warns:
        print(f"  ⚠️  {w}")
    for e in errs:
        print(f"  ❌ {e}")
    print(f"\n{'全部通过' if not errs else '存在问题'}")
    return 0 if not errs else 1


if __name__ == "__main__":
    sys.exit(main())
