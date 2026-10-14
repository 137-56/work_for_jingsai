"""Web 版交互截图 —— 驱动页面走到「② 文化配方」「④ 元素溯源卡片」。

★ 依据：index.html 的 step1() 注释写明「① 配方（本地即时）」，
  buildRecipe() 与 renderCards() 都用本地 data/patterns.json，不依赖 API。
  只有 step2()（AI 精化）走 /.netlify/functions —— 本地会失败，但不影响本文截图。
"""
import base64
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "web_screenshots"        # 正式归档位置（入库，供打包脚本读取）
OUT.mkdir(parents=True, exist_ok=True)
TMP = OUT / "_tmp"                             # Chrome 用户目录等临时文件
TMP.mkdir(exist_ok=True)
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8600
CDP_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 9241
CHROME = r"C:/Program Files/Google/Chrome/Application/chrome.exe"
VW, VH = 1500, 9000

REQ = ("古人给小孩做一只老虎枕头，想要雄壮的猛虎纹样，"
       "配祥云吉庆，祝愿孩子健康平安")


def trim(path, pad=30):
    im = Image.open(path).convert("RGB")
    a = np.asarray(im)
    bg = im.getpixel((im.width - 6, im.height - 6))
    diff = np.abs(a.astype(int) - np.array(bg)).max(axis=2)
    rows = [y for y in range(im.height) if (diff[y] > 12).any()]
    bot = max(rows) if rows else im.height - 1
    im.crop((0, 0, im.width, min(im.height, bot + pad))).save(path, "PNG")
    return Image.open(path).size


def main():
    import websocket
    proc = subprocess.Popen([
        CHROME, "--headless=new", f"--remote-debugging-port={CDP_PORT}",
        "--remote-allow-origins=*", f"--window-size={VW},{VH}",
        "--hide-scrollbars", "--force-device-scale-factor=1",
        "--no-first-run", "--no-default-browser-check",
        "--user-data-dir=" + str(TMP / "chrome2"), "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(4)
    _id = [0]

    def cmd(m, p=None):
        _id[0] += 1
        mid = _id[0]
        ws.send(json.dumps({"id": mid, "method": m, "params": p or {}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{m}: {msg['error']}")
                return msg.get("result", {})

    def js(e):
        return cmd("Runtime.evaluate", {"expression": e, "returnByValue": True}
                   ).get("result", {}).get("value")

    def shot(name):
        p = cmd("Page.captureScreenshot",
                {"format": "png", "captureBeyondViewport": False})
        f = OUT / f"{name}.png"
        f.write_bytes(base64.b64decode(p["data"]))
        return f

    try:
        tabs = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{CDP_PORT}/json", timeout=10).read())
        page = next(t for t in tabs if t["type"] == "page")
        ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=120)
        cmd("Page.enable"); cmd("Runtime.enable")
        cmd("Emulation.setEmulatedMedia",
            {"features": [{"name": "prefers-color-scheme", "value": "light"}]})
        cmd("Emulation.setDeviceMetricsOverride",
            {"width": VW, "height": VH, "deviceScaleFactor": 1, "mobile": False})
        # 屏蔽 alert（step1 在输入为空时会弹窗，headless 下会卡住）
        cmd("Page.addScriptToEvaluateOnNewDocument",
            {"source": "window.alert=function(){};"})
        cmd("Page.navigate", {"url": f"http://127.0.0.1:{PORT}/index.html"})
        time.sleep(10)

        n_pat = js("(typeof PATTERNS!=='undefined')?PATTERNS.length:0")
        print(f"本地纹样库加载: {n_pat} 条")

        # ① 首屏
        f1 = shot("01_界面_输入文化需求")
        trim(f1)
        print("① 首屏:", Image.open(f1).size)

        # 填入需求并生成配方（本地即时）
        js(f"$('req').value = {json.dumps(REQ, ensure_ascii=False)}")
        time.sleep(1)
        js("step1()")
        time.sleep(8)
        # ★ 隐藏「AI 解析」面板：它在本地必然报错（Netlify Functions 不存在），
        #   报错信息进不了提交材料。该面板线上部署后正常，说明文档里会讲清。
        js("(function(){var e=$('pAI'); if(e) e.style.display='none';"
           "var s=$('aiExplainStatus'); if(s) s.style.display='none';})()")
        time.sleep(1)
        js("window.scrollTo(0,0)")
        time.sleep(3)
        f2 = shot("02_界面_文化配方与元素溯源卡片")
        trim(f2)
        print("② 配方+卡片:", Image.open(f2).size)

        # 检查各面板是否展开
        for pid in ("p1", "p2", "p4"):
            vis = js(f"(function(){{const e=$('{pid}');"
                     f"return e?getComputedStyle(e).display:'missing'}})()")
            print(f"   {pid} display = {vis}")

        ws.close()
        return 0
    finally:
        proc.terminate()


if __name__ == "__main__":
    sys.exit(main())
