"""界面截图（CDP 自动化）—— 生成技术报告用的全套截图。

★ 三个关键设计（都是踩出来的）
  1. 视口设得足够高（7000px）→ Streamlit 主区不出现"内层滚动"，
     getBoundingClientRect 拿到的就是文档坐标。否则裁剪全错位。
  2. 分步进度（04）必须检测 st.status 组件（`[data-testid="stStatusWidget"]`），
     **不能只靠文本匹配** —— 初版凭 "正在生成" 匹配，结果拍到了点击前的初始态。
     ★ 且要在**服务刚重启、CLIP 未加载**时抓，否则生成 3 秒就完了，窗口太短。
  3. 截图底部会留大片空白（页面高度 = 视口高度），统一走 trim_blank 裁掉。
     判定时**跳过左侧侧边栏**（侧边栏满高，否则永远判不出空白行）。

用法：
    env -u http_proxy ... .venv/Scripts/python.exe scripts/shots.py [streamlit_port] [cdp_port]
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
OUT.mkdir(parents=True, exist_ok=True)
TMP = ROOT / "temp_shots"
TMP.mkdir(exist_ok=True)

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8533
CDP_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 9230
UPLOAD = ROOT / "data" / "images" / "WENYANG-030.jpg"      # 蝙蝠纹，库内可触发 HIGH
CHROME = r"C:/Program Files/Google/Chrome/Application/chrome.exe"

VW, VH = 1500, 7000
SIDEBAR_X = 400        # 判定空白时跳过左侧侧边栏（其满高且有色）


class CDP:
    def __init__(self, port):
        import websocket
        self._id = 0
        self.proc = subprocess.Popen([
            CHROME, "--headless=new", f"--remote-debugging-port={port}",
            "--remote-allow-origins=*",
            f"--window-size={VW},{VH}", "--hide-scrollbars",
            "--force-device-scale-factor=1",
            "--no-first-run", "--no-default-browser-check",
            "--user-data-dir=" + str(TMP / "chrome"),
            "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(4)
        tabs = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json", timeout=10).read())
        page = next(t for t in tabs if t["type"] == "page")
        self.ws = websocket.create_connection(
            page["webSocketDebuggerUrl"], timeout=180)
        self.cmd("Page.enable")
        self.cmd("Runtime.enable")
        self.cmd("DOM.enable")
        # ★ 强制浅色媒体查询，双保险（config.toml 已设 base=light）
        self.cmd("Emulation.setEmulatedMedia", {
            "features": [{"name": "prefers-color-scheme", "value": "light"}]})
        self.cmd("Emulation.setDeviceMetricsOverride", {
            "width": VW, "height": VH, "deviceScaleFactor": 1, "mobile": False})

    def cmd(self, method, params=None):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method,
                                 "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def js(self, expr):
        r = self.cmd("Runtime.evaluate",
                     {"expression": expr, "returnByValue": True,
                      "awaitPromise": True})
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"])
        return r.get("result", {}).get("value")

    def text(self):
        return self.js("document.body.innerText") or ""

    def wait_text(self, needle, timeout=420, poll=2.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if needle in self.text():
                return True
            time.sleep(poll)
        return False

    def wait_tabs(self, timeout=120):
        for _ in range(int(timeout / 2)):
            if self.js("document.querySelectorAll('[data-testid=\"stTab\"]')"
                       ".length"):
                return True
            time.sleep(2)
        return False

    def click(self, text, tag="button"):
        esc = json.dumps(text, ensure_ascii=False)
        return self.js(f"""
        (() => {{
          const els = [...document.querySelectorAll({json.dumps(tag)})];
          const t = els.find(e => e.innerText.trim().includes({esc}));
          if (t) {{ t.click(); return true; }}
          return false;
        }})()""")

    def goto_tab(self, name):
        esc = json.dumps(name, ensure_ascii=False)
        ok = self.js(f"""
        (() => {{
          const ts = [...document.querySelectorAll('[data-testid="stTab"]')];
          const t = ts.find(x => x.innerText.includes({esc}));
          if (t) {{ t.click(); return true; }}
          return false;
        }})()""")
        time.sleep(2.5)
        return ok

    def coords(self):
        raw = self.js("""
        (() => {
          const o = {};
          [...document.querySelectorAll('h1, h2, h3')].forEach(h => {
            const r = h.getBoundingClientRect();
            const k = h.innerText.trim();
            if (k) o[k] = [Math.round(r.top), Math.round(r.bottom)];
          });
          return JSON.stringify(o);
        })()""")
        return json.loads(raw or "{}")

    def content_h(self):
        """主区真实内容高度（大视口下 ScrollHeight 不准）。"""
        return self.js("""
        (() => {
          let maxB = 0;
          const root = document.querySelector('section.stMain')
                    || document.querySelector('[data-testid="stMain"]')
                    || document.body;
          root.querySelectorAll('*').forEach(e => {
            const r = e.getBoundingClientRect();
            if (r.height > 4 && r.width > 4) maxB = Math.max(maxB, r.bottom);
          });
          return Math.round(maxB);
        })()""") or VH

    def shot(self, name, full=False):
        p = self.cmd("Page.captureScreenshot",
                     {"format": "png", "captureBeyondViewport": full})
        f = TMP / f"{name}.png"
        f.write_bytes(base64.b64decode(p["data"]))
        return f

    def upl(self, path):
        doc = self.cmd("DOM.getDocument", {"depth": -1})
        node = self.cmd("DOM.querySelector",
                        {"nodeId": doc["root"]["nodeId"],
                         "selector": "input[type='file']"})
        if not node.get("nodeId"):
            return False
        self.cmd("DOM.setFileInputFiles",
                 {"files": [str(path)], "nodeId": node["nodeId"]})
        return True

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass
        self.proc.terminate()


def trim_blank(path, bg=(255, 255, 255), tol=10, pad=18, x_from=SIDEBAR_X):
    """裁掉主区上下空白（跳过左侧侧边栏）。"""
    im = Image.open(path).convert("RGB")
    w, h = im.size
    px = im.load()
    xs = list(range(min(x_from, w - 1), w, 10))

    def blank(y):
        for x in xs:
            c = px[x, y]
            if (abs(c[0] - bg[0]) > tol or abs(c[1] - bg[1]) > tol
                    or abs(c[2] - bg[2]) > tol):
                return False
        return True

    top, bot = 0, h - 1
    while top < h - 2 and blank(top):
        top += 1
    while bot > top + 2 and blank(bot):
        bot -= 1
    if bot - top < 40:
        return im
    out = im.crop((0, max(0, top - pad), w, min(h, bot + pad)))
    out.save(path, "PNG")
    return out


def crop(src, dst, y0, y1, pad=16, do_trim=True):
    im = Image.open(src)
    H = im.height
    y0 = max(0, int(y0) - pad)
    y1 = min(H, int(y1) + pad)
    if y1 - y0 < 20:
        y1 = min(H, y0 + 20)
    im.crop((0, y0, im.width, y1)).save(dst, "PNG")
    if do_trim:
        trim_blank(dst)
    print(f"    → {dst.name}  ({Image.open(dst).size})")
    return dst


def main():
    c = CDP(CDP_PORT)
    try:
        print("[1] 打开页面…")
        c.cmd("Page.navigate", {"url": f"http://127.0.0.1:{PORT}/"})
        if not c.wait_tabs():
            print("  ✗ 标签页未出现"); return 1
        print("  ✓ 三个标签页已渲染")
        time.sleep(5)

        print("[2] 触发生成…")
        if not c.click("生成纹样方案"):
            print("  ✗ 找不到生成按钮"); return 1

        # ---- 04 分步进度：检测 st.status 组件，快轮询 ----
        got = False
        for _ in range(150):
            time.sleep(0.4)
            n = c.js("document.querySelectorAll("
                     "'[data-testid=\"stStatusWidget\"]').length") or 0
            if n:
                time.sleep(2.0)          # 等几条 _step 文字流出来
                f = c.shot("04")
                crop(f, OUT / "04_分步进度.png", 0, c.content_h() + 60,
                     do_trim=False)
                got = True
                print("  ✓ 已抓分步进度")
                break
        if not got:
            print("  ! 未抓到分步进度")

        print("[3] 等待生成完成…")
        if not c.wait_text("① 纹样文化配方", timeout=420):
            print("  ✗ 生成未完成"); return 1
        time.sleep(6)
        print("  ✓ 生成完成")

        c.js("window.scrollTo(0, document.body.scrollHeight)"); time.sleep(3)
        c.js("window.scrollTo(0, 0)"); time.sleep(3)
        co = c.coords()
        fgen = c.shot("gen", full=True)

        def y0(k):
            return co.get(k, [0, 0])[0]

        print("[4] 裁剪生成页各区域…")
        if y0("③ 文化规则校验") > y0("① 纹样文化配方"):
            crop(fgen, OUT / "01_配方与检索.png",
                 y0("① 纹样文化配方"), y0("③ 文化规则校验"))
        if y0("⑤ AI 风格化（可选）") > y0("③ 文化规则校验"):
            crop(fgen, OUT / "02_文化校验与溯源卡片.png",
                 y0("③ 文化规则校验"), y0("⑤ AI 风格化（可选）"))
        crop(fgen, OUT / "05_生成页_完整.png", 0, c.content_h() + 40)
        if y0("⑥ 文创效果预览（3D）") > y0("⑤ AI 风格化（可选）"):
            crop(fgen, OUT / "06_风格化区.png",
                 y0("⑤ AI 风格化（可选）"), y0("⑥ 文创效果预览（3D）"))
        crop(fgen, OUT / "08_3D预览区_待生成.png",
             y0("⑥ 文创效果预览（3D）"), c.content_h() + 40)

        # ---------- 谱系页 ----------
        print("[5] 纹样谱系页…")
        if c.goto_tab("纹样谱系"):
            time.sleep(8)
            c.js("window.scrollTo(0, document.body.scrollHeight)"); time.sleep(5)
            c.js("window.scrollTo(0, 0)"); time.sleep(4)
            ck = c.coords()
            fk = c.shot("kin", full=True)
            k0, k2, k3 = (ck.get("① 全库谱系指标", [0, 0])[0],
                          ck.get("② 五族谱系图", [0, 0])[0],
                          ck.get("③ 母题关联网络 / 元素共现网络", [0, 0])[0])
            if k2 > k0:
                crop(fk, OUT / "11_纹样谱系页.png", k0, k3 or k2)
            if k3:
                crop(fk, OUT / "12_谱系页_网络图与负结论.png",
                     k3, c.content_h() + 40)
            crop(fk, OUT / "13_谱系页_完整.png", 0, c.content_h() + 40)
            print("  ✓ 谱系页完成")

        # ---------- 版权审查 ----------
        print("[6] 版权审查页…")
        if c.goto_tab("版权相似度审查"):
            time.sleep(3)
            if c.upl(UPLOAD):
                print("  已上传", UPLOAD.name)
                if c.wait_text("风险等级", timeout=300):
                    time.sleep(6)
                    c.js("window.scrollTo(0, 0)"); time.sleep(2)
                    fc = c.shot("chk", full=True)
                    crop(fc, OUT / "03_版权审查.png", 0,
                         c.content_h() + 40, do_trim=False)
                    trim_blank(OUT / "03_版权审查.png")
                    print("  ✓ 版权审查完成")
                else:
                    print("  ! 未等到风险等级")

        # ---------- 回生成页：风格化 + 3D ----------
        print("[7] 风格化…")
        if c.goto_tab("生成与溯源"):
            time.sleep(3)
            if c.click("生成风格化效果"):
                for _ in range(120):
                    time.sleep(2)
                    if "风格化" in c.text() and (
                            "下载" in c.text() or "结果" in c.text()):
                        break
                time.sleep(10)
                c.js("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(4)
                c.js("window.scrollTo(0, 0)"); time.sleep(3)
                cs = c.coords()
                fs = c.shot("sty", full=True)
                s0 = cs.get("⑤ AI 风格化（可选）", [0, 0])[0]
                s1 = cs.get("⑥ 文创效果预览（3D）", [0, 0])[0]
                if s1 > s0:
                    crop(fs, OUT / "07_风格化结果.png", s0, s1)
                    print("  ✓ 风格化完成")
            else:
                print("  ! 找不到风格化按钮")

            print("[8] 3D 预览…")
            if c.click("生成静态效果图"):
                for _ in range(120):
                    time.sleep(2)
                    if "下载 GLB" in c.text():
                        break
                time.sleep(6)
                c.js("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(4)
                c.js("window.scrollTo(0, 0)"); time.sleep(3)
                c3 = c.coords()
                f3 = c.shot("d3", full=True)
                d0 = c3.get("⑥ 文创效果预览（3D）", [0, 0])[0]
                crop(f3, OUT / "09_3D预览结果.png", d0, c.content_h() + 40)
                crop(f3, OUT / "10_生成页_3D完整.png", 0, c.content_h() + 40)
                print("  ✓ 3D 完成")

        print("\n完成。输出：", OUT)
        return 0
    finally:
        c.close()


if __name__ == "__main__":
    sys.exit(main())
