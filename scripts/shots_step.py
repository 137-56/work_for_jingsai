"""专抓「04 分步进度」—— st.status 只在生成过程中短暂存在。

★ 为什么要单独一个脚本：
  st.status 的存活窗口 = 生成耗时。CLIP 已缓存时生成只要几秒，
  主截图脚本跑完前几阶段后 CLIP 早加载好了，窗口太短抓不到。
  → 必须**重启服务后第一次生成**（CLIP 冷启动 20-40s）才好抓。

★ 诊断：同时记录 stStatusWidget 选择器命中数与正文关键词，
  便于区分"选择器错"与"时序错过"。
"""
import base64
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
TMP = ROOT / "temp_shots"
TMP.mkdir(exist_ok=True)
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8535
CDP_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 9232
CHROME = r"C:/Program Files/Google/Chrome/Application/chrome.exe"
VW, VH = 1500, 2600


def main():
    import websocket
    proc = subprocess.Popen([
        CHROME, "--headless=new", f"--remote-debugging-port={CDP_PORT}",
        "--remote-allow-origins=*", f"--window-size={VW},{VH}",
        "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
        "--user-data-dir=" + str(TMP / "chrome2"), "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(4)
    _id = [0]

    def cmd(method, params=None):
        _id[0] += 1
        mid = _id[0]
        ws.send(json.dumps({"id": mid, "method": method,
                            "params": params or {}}))
        while True:
            m = json.loads(ws.recv())
            if m.get("id") == mid:
                if "error" in m:
                    raise RuntimeError(f"{method}: {m['error']}")
                return m.get("result", {})

    def js(e):
        return cmd("Runtime.evaluate", {"expression": e, "returnByValue": True,
                                        "awaitPromise": True}
                   ).get("result", {}).get("value")

    def shot(name):
        p = cmd("Page.captureScreenshot", {"format": "png"})
        f = TMP / f"{name}.png"
        f.write_bytes(base64.b64decode(p["data"]))
        return f

    try:
        tabs = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{CDP_PORT}/json", timeout=10).read())
        page = next(t for t in tabs if t["type"] == "page")
        ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=180)
        cmd("Page.enable"); cmd("Runtime.enable")
        cmd("Emulation.setEmulatedMedia",
            {"features": [{"name": "prefers-color-scheme", "value": "light"}]})
        cmd("Emulation.setDeviceMetricsOverride",
            {"width": VW, "height": VH, "deviceScaleFactor": 1, "mobile": False})

        cmd("Page.navigate", {"url": f"http://127.0.0.1:{PORT}/"})
        for _ in range(60):
            if js("document.querySelectorAll('[data-testid=\"stTab\"]').length"):
                break
            time.sleep(2)
        print("页面就绪")
        time.sleep(5)

        print("点击生成…")
        js("""(()=>{const b=[...document.querySelectorAll('button')]
              .find(x=>x.innerText.includes('生成纹样方案'));
              if(b){b.click();return true}return false})()""")

        hit = False
        t0 = time.time()
        best = 0
        # ★ 不依赖 `stStatusWidget` 选择器 —— 实测该 testid 在当前 Streamlit 版本
        #   恒为 0（版本差异）。改用**正文关键词**判定，并采用
        #   "步骤数创新高就截图" 的策略，保证留下的是步骤最全的那一帧。
        for i in range(240):                       # 最多 72s
            time.sleep(0.28)
            t = js("document.body.innerText") or ""
            marker = [w for w in ("解析需求", "从样本库检索", "文化规则校验",
                                  "实物织物肌理", "组装元素级溯源卡片")
                      if w in t]
            if len(marker) > best:
                best = len(marker)
                f = shot("04")
                im = Image.open(f)
                im.crop((0, 0, im.width, min(im.height, VH))).save(
                    OUT / "04_分步进度.png", "PNG")
                print(f"  · {time.time()-t0:5.1f}s 步骤数={best} {marker} → 已存")
                hit = True
            if "① 纹样文化配方" in t and not marker:
                print("  生成已完成，取步骤最全的一帧")
                break

        if hit:
            print(f"  ✓ 分步进度完成（最多 {best} 个步骤）")
        else:
            shot("04_fail")
            print("  ✗ 未抓到；诊断图 temp_shots/04_fail.png")
        return 0 if hit else 2
    finally:
        try:
            ws.close()
        except Exception:
            pass
        proc.terminate()


if __name__ == "__main__":
    sys.exit(main())
