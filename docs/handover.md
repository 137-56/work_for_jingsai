# 纹初迹现 · 项目接手文档（Handover）

> **这份文档的用途**：交给另一个工作区 / 另一个 AI 会话接手本项目。
> 因此它是**自包含**的——不依赖本对话历史、不依赖本工作区的 memory、不依赖仓库外的文档也能读懂。
> 事实截止：**2026-10-28 18:30**。之后若有改动，以 `git log` 为准。

---

## 0. 先读：四件必须由人工确认的事

接手 AI 不要自行决定这四件事，**先问 Mr.G**：

1. **赛程状态**。本工作区记忆中国赛截止日为 **2026-10-15**，而当前是 10-28。
   提交包已在桌面生成（见 §11），但**是否已提交、是否已过截止、是否还有二轮/决赛环节，AI 无从判断**。
2. **桌面有两个提交包**：`AIC-2026-49790132-算法模型创新-纹初迹现`（正式版）与
   `...-纹初迹现(xiaozixuande)`（Web 演示版）。**哪个是定稿、是否两份都要交，需人工确认。**
3. **提交包中间层目录名是赛方模板占位名**：`AIC-2026-12345678-算法模型创新-作品名称-代码与数据`
   （编号 `12345678` 与「作品名称」都是模板字样，未改）。四分类在其下。
   **是否需要改名、改成什么，以赛方要求为准，不要凭观感自行改名。**
4. **「你溯源溯到哪里」的回答口径**（见 §10 的立论张力）。母题库本身是 AI 辅助再设计的图，
   与"AI 生成不可信"的立论存在张力。**这条 2026-09-14 就识别了，至今没有定稿口径**——
   接手后应尽快找 Mr.G 敲定，**不要自行编说辞**。

---

## 1. 项目是什么

**纹初迹现：传统纹样可溯源生成系统**。

核心主张：AI 生成传统纹样的通病是「三不」——不可解释、不可追溯、不可控。
本项目用**可解释的组合式生成**替代"让模型凭空画"：
把需求解析成文化配方 → 从真实纹样母题库检索元素 → 按传统构图程式组合 →
生成的同时即确定每个元素的出处与授权 → 过一道文化校验 → 输出元素级溯源卡片。

> 一句话对外口径：**别人的 AI 给你一张图，本系统给你一张图 + 一张配料表。**

**三种溯源层次**（贯穿全项目的三分法，不要退化回"三个功能"）：

| 层次 | 界面位置 | 回答的问题 |
|---|---|---|
| 元素级 | 生成与溯源页 | 这张图的每个部件来自哪条母题 |
| 谱系级 | 纹样谱系页 | 这类纹样在谱系上跟谁最近 |
| 风险级 | 版权审查页 | 一张设计图与本库是否雷同 |

### 身份常量

| 项 | 值 |
|---|---|
| 团队编号 | `AIC-2026-49790132` |
| 赛题 | 算法模型创新 |
| 作品名 | 纹初迹现 |
| 提交包根目录命名规范 | `参赛团队编号-赛题名称-作品名称-XX` |

> ⚠️ 历史文件里作品名写作**「剪纹有据」**（如 `文档/剪纹有据-项目技术报告.docx`）。
> **现名是「纹初迹现」**，接手后引用旧文件时注意这个不一致，别把旧名写进新材料。

---

## 2. 环境与位置

```
D:\work\work_space\DeskTop\DeskBox\
├── 竞赛\
│   ├── work\                  ← 工程仓库（本接手文档所在，git 管理）
│   │   ├── app.py             Streamlit 界面入口
│   │   ├── src/               处理管线 M1–M7
│   │   ├── scripts/           工具与自检脚本
│   │   ├── tests/             单元测试
│   │   ├── docs/              契约 / 指标 / 图表（入库）
│   │   ├── data/              母题库 / 索引 / 实物佐证层（部分入库）
│   │   ├── rules/             文化规则库 25 条
│   │   ├── web/               Three.js 查看器源码（必须入库）
│   │   └── static/            web/ 的运行时副本（不入库，自动生成）
│   ├── 文档\                  ← 仓库外：实施指引 / 报告 / PPT（**不进 git**）
│   └── .workbuddy\memory\     本工作区的 AI 记忆（接手方看不到，无需关心）
└── AIC-2026-49790132-...      提交包（桌面）
```

**Python 一律用仓库内的 venv**：

```
D:\work\work_space\DeskTop\DeskBox\竞赛\work\.venv\Scripts\python.exe
```

本文档中一律记作 `$PY`。用系统 Python 会报 `No module named 'faiss'`。

- **无需 GPU**，CLIP 走 CPU，普通笔记本可跑。
- torch 为 CPU 版；matplotlib 走国内镜像。
- `.env` 存 `DASHSCOPE_API_KEY`（阿里云百炼，M1 意图解析与 M5 风格化用）。
  **没有 key 也能跑**：M1 退化为规则兜底解析，M5 不可用，其余模块正常。

---

## 3. 五分钟跑起来

```bash
cd /d/work/work_space/DeskTop/DeskBox/竞赛/work

# ① 数据契约校验（应输出 [PASS]）
$PY scripts/validate_samples.py

# ② 建向量索引（首次需下载 CLIP 权重）
$PY scripts/build_index.py

# ③ 启动界面
$PY -m streamlit run app.py        # → http://localhost:8501
```

界面三个标签页：**生成与溯源** / **版权相似度审查** / **纹样谱系**。

**纯命令行跑一次**（两种等价方式）：

```bash
# 方式 A：模块入口
$PY -m src.pipeline "做一个春节用的窗花，要喜庆"

# 方式 B：在代码里调用
$PY -c "from src.pipeline import run; r = run('做一个春节用的窗花，要喜庆'); print(r['recipe']['recipe_id'], r['errors'])"

# 落盘到 outputs/<recipe_id>/
$PY -c "from src.pipeline import run, save_all; save_all(run('做一个春节用的窗花，要喜庆'))"
```

> ⚠️ **`pipeline.run()` 只返回 dict，不落盘**；落盘要另调 `save_all()`。
> 返回的键是 `user_request / errors / recipe / hits / card / _texture`。
> **`violations` 不在顶层**，它在 `r['recipe']['violations']` 里——这是最容易找错的地方。
> `_texture` 下划线开头 = 内部用，不落盘。

产物落在 `outputs/<recipe_id>/`：`recipe.json` / `card.json` / `card.md` /
`provenance_card.png` / `design_board.png` / `composed_pattern.png`。

**3D 导出**：

```bash
$PY -m src.glb_export --recipe outputs/<recipe_id>     # 梅瓶 / 方盒 / 团扇 三个 GLB
```

**谱系图**：

```bash
$PY scripts/build_kinship_graph.py                     # 产物在 docs/figures/
```

---

## 4. 架构

### 模块表

| 模块 | 文件 | 职责 |
|---|---|---|
| M1 意图解析 | `src/m1_intent.py` | 一句话 →《纹样文化配方》（LLM + 规则兜底） |
| M2 元素检索 | `src/m2_retrieve.py` | Chinese-CLIP + faiss；三招调优（类别前缀 / 多查询 / 元素二次筛选） |
| M3 文化校验 | `src/m3_validate.py` | 25 条规则，四类约束引擎 |
| M4 设计依据板 | `src/m4_compose.py` | `compose_board()`——素材 + 理由，给人看 |
| M4a 组合纹样合成 | `src/m4_compose.py` | `compose_pattern()`——真正的图案 |
| M5 AI 风格化 | `src/m5_stylize.py` | 可选。**输出不可溯源**，与溯源严格分区 |
| M6 溯源卡片 | `src/m6_provenance.py` | 元素 → 出处 → 寓意 → 授权 |
| M7 版权预警 | `src/m7_copyright.py` | 双路相似度（phash + CLIP 语义）→ 风险分级 |
| 界面 | `app.py` | Streamlit |
| 3D | `pattern_layout.py` / `preview3d.py` / `glb_export.py` | 分区贴图 / 静态渲染 / GLB 导出 |

> **M4 与 M4a 同在 `src/m4_compose.py`**，是上下游关系：依据板解释"为什么这样组合"，组合图是组合的结果。
> `clip_model.py` 用 `lru_cache` 做单例，M2 与 M7 共用。
> `pipeline.py` 的原则是**任何单点失败都不中断整条管线**——失败降级并记进 `errors`，不往上抛。

### 两层数据架构（★ 口径关键，对外表述不能错）

| 层 | 来源 | 规模 | 作用 | 参与元素级溯源 |
|---|---|---|---|---|
| 语义层（母题库） | Wényàng | **100 条** | M2 检索依据 / M3 校验依据 | ✅ 是 |
| 实物佐证层 | 克利夫兰艺术博物馆 | 303 件 | **仅提供织物肌理（材质层）** | ❌ 否 |

实物佐证层**没有** `name` / `elements` / `meaning` 字段，用模型去编这些字段
等于重蹈「用 AI 生成内容充当文化依据」的覆辙。

**对外一律表述：纹样层元素级可溯；材质层仅实物可溯。两者不得混称 100% 可溯源。**

---

## 5. 数据口径（不许违背）

1. **Wényàng 100 条是唯一母题源，已定稿，不扩库**。源数据全集就是 100 条。
   **任何外部数据都不得写进 `data/samples.json`**。
2. **The Met 60 件公版文物已抓好放在 `data/artifacts/`，但处于暂停/备用状态，不计入当前版本**。
   是否启用另议，不要擅自接入。
3. **故宫博物院数字文物库不可用**——其授权明确禁止 AI 创作与数字展示，与本作品用法冲突。
   不要尝试接入。
4. **`dynasty` 字段全库为「不详」，不虚构**。源数据无朝代信息，纹样母题本身跨朝代
   （缠枝莲纹自唐沿用至清），填具体朝代属编造。
5. **不许编数据**。任何补录必须来自源数据原文。历史教训：曾把源数据没有的母题写进 `elements`。
6. **授权**：Wényàng 图像与文字 = CC BY-NC 4.0（署名 · 限非商业），代码 MIT；
   克利夫兰 = CC0。署名要求见 `文档/数据来源署名规范.md`。
7. **`related_motifs` 存的是纹样名，不是 id**（如 `"宝相花纹"`）。
   524 条原始引用中 505 条能对上库内 `name`，**对上 `id` 的是 0 条**。
   ★ 接手后若按 id 做关联，会**全数落空**——这是实测过的坑。

### 谱系的三个数（口径不同，不要混用）

| 数 | 含义 | 出处 |
|---|---|---|
| **385** | 谱系图去重后的边数 | `docs/figures/kinship_stats.json` → `n_edge` |
| **505** | 能对上库内 name 的原始引用数 | 同上 → `raw_refs` |
| **524** | `related_motifs` 字段原始条目总数 | 直接扫 `samples.json` |

README 与对外材料统一写 **「100 母题 / 385 边 / 5 族」**。

---

## 6. 硬规则（违反 = 返工）

### 代码层

1. **GLB 的 UV 必须与静态预览的 UV 完全一致。**
   `glb_export.vertex_uv()` ↔ `preview3d._*_hit` 指向同一组公式，两处都有"必须同步"标注。
   改动任一处必须同时改另一处并跑两个方向的验证——否则"预览看到的"≠"下载到的"。
2. **`m4_compose.crop_pattern` / `pattern_crop_box` 不要随意优化**（注释已写明）。
3. **改 3D 代码前先读 `文档/B8_3D交付说明.md`**（三条铁律 + 六个自检脚本 + 已踩的坑）。
4. **3D 布局几何必须匹配载体几何**：旋转体 → 环一圈展开图；方盒 → 一张图印一面（不绕圈）；
   圆平面（团扇）→ 极坐标同心；方平面（盒盖）→ 方框 + 方块。**一套逻辑套到底必错。**
5. **形态集（vase 梅瓶 / box 方盒 / fan 团扇）变更要同步 4 个文件共 6 处**：

   | 文件 | 位置 | 性质 |
   |---|---|---|
   | `src/preview3d.py` | `FORMS` 定义（约 509 行） | ★ 唯一定义源 |
   | `web/viewer.html` | `const FORMS = [...]`（约 124 行） | ★ **JS 独立副本，无 import，必须手改** |
   | `app.py` | 110 行 `order` ／ 122 行 `label` 字典 ／ 417–419 行 ⑥ 区三列 | 界面侧三处 |
   | `scripts/check_glb_uv.py` | 210 行 `FILL_MIN` 阈值表 ／ 274 行 `for kind in (...)` | 自检侧两处 |

   **自动跟随、不用手工改的**：`src/glb_export.py`（`from src.preview3d import FORMS`）、
   `scripts/check_render3d.py`（`P.FORMS`）——这两处是 import，跟着定义源走。
   ★ 新增形态若忘加 `FILL_MIN`，不会报错，会静默 fallback 到 `FILL_MIN_DEFAULT = 0.35`。
   ★ `check_render3d.py` 已改为按 `kind` 三分支（旧版按 `prof/half` 二分，团扇两边都不走会静默失效）。
   ★ `plate` 赏盘形态**已移除**（近平面套带状展开图必然错位，改两轮无效），文档里见到的赏盘是历史残留。

### 口径层

6. **指标单一事实来源是 `docs/metrics.json`**（`headline_metrics` 8 项）。
   报告 / PPT / 作品简介取数一律引用它，不到处自算。校验：`scripts/check_metrics.py`。
7. **界面上的指标与名单一律从数据现算，不写死**。谱系页复用 `build_kinship_graph.load_graph()`，
   **不另写一遍读 `samples.json` 的逻辑**——否则"图里画的"与"界面说的"两套代码，迟早不一致。
8. **共享常量只维护一处**（如 `build_kinship_graph.FAMILY_NAMES` 被 app.py 导入）。
9. **"共 N 个 / N 条"必须附清单**，且核对要**实跑脚本看输出**，不要 grep 源码数
   （grep 到的是定义不是行为）。历史教训：文档标"13 项"而实跑输出是"25 条"，无 13 这个数。
10. **文档里引用命令 / 接口 / 路径，必须实跑一遍再写进去。**
11. **不许编数字**。材料之间同一个数必须同步。
12. **负结论必须如实写**。谱系页 ④ 区「消融负结论」——关联数据对检索指标无正向作用
    （`docs/exp_related_motifs.json`），价值在可解释性而非准确率。
    **不写，演示时必被问住；写了，是加分项。** 同类还有：版权预警同门类误报 36.7%、
    结构层对几何类改动完全失效、`FPR=0` 的置信上界约 9.5%（不可写成"误报率 0%"）。
13. **红线声明要写在界面上，不只写在文档里**（2026-09-26 定的约定）。
    署名 / 授权 / "纹样层可溯、材质层仅实物可溯"的口径，界面要能看到。
14. **「纹初迹现」四字信息量偏低**（不含"纹样 / 溯源 / AI"任何关键词）。
    已定名不再改，但对外介绍时**必须配一句副标题**（"传统纹样可溯源生成系统"），
    否则不读材料的人不知道这是什么。历史名「剪纹有据」在旧文件里仍有残留。

### 提交层

13. **禁止 `git add -A`**。提交前必看 `git status --short`，只加明确路径。
    历史教训：曾把含真实手机号与群号的测试文件提交进库。
14. **提交前必跑 `scripts/redline_check.py .`**（红线扫描），0 命中才允许提交。
15. **提交包要单独扫红线**——仓库干净 ≠ 提交包干净（打包脚本会把 gitignore 的文件收进去）。
16. **红线自检会扫注释**：说明文字里**不得原样复述被命中的串**，否则等于自己制造命中
    （本项目已因此返工三次）。详见 `docs/redline_notes.md`。
    **协作消息里同样不许复述。**
17. **清理派生物只用移动，不用删除**。收益只是目录整洁，删错定稿产物的代价不可逆。
18. **测试文件不要落在待提交目录里**，造样本一律用假数据。

---

## 7. 本机环境坑（实测，反复踩过）

| 坑 | 正解 |
|---|---|
| Bash 里 `date`/`head`/`grep`/`wc`/`dirname` 等 coreutils 基本不可用 | 要时间用 `$PY -c "import datetime; print(datetime.datetime.now())"`；过滤统计一律用 Python，别用 shell 管道 |
| PowerShell 工具拿不到 stdout | Python 是最可靠的执行通道 |
| 读不了中文 PDF（报 binary file） | 隔离 venv + pypdf 抽取 |
| `http_proxy=http://127.0.0.1:30603` 会挡住本地请求，本地自检全返 502 | 跑本地 HTTP 自检前 `env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy ...` |
| `nohup ... &` 起的服务十几秒后被回收（netstat 查不到、日志无报错） | 起长驻服务用后台任务机制 |
| `wmic` 已从本机移除 | 查进程命令行用 PowerShell CIM 写临时文件再读回 |
| Streamlit 静态目录必须是 `<app_dir>/static`（**不是** `.streamlit/static/`） | 配 `server.enableStaticServing=true`，URL 前缀 `/app/static/`（**前导斜杠不能少**）。唯一线索是启动日志里的 `no static folder found at ...` |
| Streamlit 标签页选择器不是 `<button>` | 实测 DOM 是 `<div role="tablist"><div data-testid="stTab" role="tab">`；用 `document.querySelectorAll('[data-testid="stTab"]')`。`'button[role="tab"]'` 返回 0，但 innerText 里看得到标签，极易误判为"没渲染" |
| headless 截图深浅混杂 | 必须显式配 `.streamlit/config.toml` 的 `[theme] base = "light"`，否则拿到深色底且同批截图深浅不一 |
| headless 截图 `captureBeyondViewport=true` 触发 Chrome 重排，侧边栏被推偏约 45px、左侧被切 | 用视口截图 + 按内容高度裁剪；`window.scrollTo(0,0)` 无效（Streamlit 主区是内层滚动容器） |
| `st.status` 存活窗口 = 生成耗时；CLIP 缓存后生成仅 9 秒，抓不到 | 必须冷启动服务后第一次生成才抓得到 |
| Three.js 必须用 **r147** | r150+ 已移除 `build/three.min.js`；UMD 版 r148 后废弃。r147 的 UMD `GLTFLoader.js` 已下载到 `web/vendor/`（离线可用） |

**本机常驻进程不要动**：`python.exe`（agent gateway）与 `node.exe`（MCP server）是宿主自身的。

---

## 8. 自检脚本清单（改完必跑）

| 脚本 | 验什么 |
|---|---|
| `scripts/validate_samples.py` | 数据契约（10 条规则） |
| `scripts/check_rules.py` | 文化规则结构校验 + 引擎冒烟 |
| `scripts/check_metrics.py` | 指标一致性（跨报告 / PPT / 简介取数），`--strict` 严格模式 |
| `scripts/check_m3_differential.py` | M3 黄金快照差分回归（525 配方，防误报设计见脚本头） |
| `scripts/check_board_layout.py` | 设计板版面：遮挡 / 出框 / 幂等 / 取值长度变体 |
| `scripts/check_glb_uv.py` | 从 `.glb` 字节流**独立重解析**：UV 越界 / 采空白 / 索引完整性 |
| `scripts/preview_glb.py` | **独立** z-buffer 渲染 GLB，人眼验贴图方向 |
| `scripts/check_render3d.py` | 法线朝向 + NaN 污染 |
| `scripts/check_style_ground.py` | 贴图双路线均可渲染 + 地子来源必须不同 |
| `scripts/check_app_embed.py` | 界面 ⑥ 区嵌入链路（★ 需服务已在跑，否则全 502） |
| `scripts/check_submission_pkg.py` | 提交包：同名冲突 / 33 个依赖路径 / 有无 `.env` `.venv` `.git` |
| `scripts/redline_check.py` | 红线扫描 |
| `tests/test_rules.py` | M3 规则引擎，**50 例**（`$PY -m unittest discover -s tests`） |

> ★ `check_glb_uv.py` 与 `preview_glb.py` 是**两条独立实现**（字节流重解析 / 独立光栅化）。
> 数值自检查不出"上下颠倒 / 左右镜像"，只有交叉验证才能发现。
> ★ `tests/test_retrieval.py` 目前是 **0 字节**（待补）。

**改 3D 后必跑**：`check_render3d` → `check_glb_uv` → `preview_glb` → `check_style_ground` → `check_app_embed`。

---

## 9. 最近一轮修复（2026-10-28，已提交）

提交：`0ba1276 fix: 修复 11 项缺陷 —— 方盒贴图留白、M3 静默失效、设计板压字`（17 files, +4605/-120）
与 `2e02a05 docs: 把红线自查的使用规范落盘`。

修的 11 项（择要）：

| 缺陷 | 根因 | 处置 |
|---|---|---|
| 方盒贴图有效率仅 44% | `_center_band` "高度优先"导致方形母题在主画面区只放 1 个，两侧各留白 240px；且旧自检阈值在旧口径下永远放行 | 新增"宽度优先"第二段逻辑（取**第一个可行**的 n，非最大 n——填充比例对 n 单调递减，取最大反而更空）；自检分母改为 UV 实际采样面积，阈值按形态 box 0.80 / vase 0.35 / fan 0.35 |
| 组合纹样图色相不受配方控制 | 色板取色路径问题 | 修正（详见 commit） |
| M3 坏规则**连告警都不产生** | `.get()` 降级把崩溃变成静默，而界面在 violations 为空时打印「未检出文化规则违规」 | 新增 `rule_schema_error()` 显式结构检查；结构错 → `[规则格式异常]`，运行期抛 → `[规则执行异常]` |
| 设计板压字 | `_kv_block` 的 `y += lh` 无条件推进，值折行后压住下一行标签；返回的结束 y 只算一行 | 改为 `y += lh * max(1, len(lines))` 并返回真实底边 |
| 溯源卡片「相似度」列口径不实 | 实际是 CLIP 余弦 + 0.15×构成元素重合的**融合分** | 展示层改称「匹配分」并加口径说明；**字段名 `similarity` 与数据来源一字未动**（schema 已冻结） |

新增：`tests/test_rules.py`（50 例）、`scripts/check_m3_differential.py` + `data/m3_golden.json`、
`scripts/check_board_layout.py`、`docs/m3_guard_matrix.md`、`docs/redline_notes.md`。

**当前基线**：`outputs/R20261028160834-1A63`（14 文件，2D + 3D 同源）。
`design_board` 1680×2172 ｜ `preview3d_triptych` 1904×1064 ｜ `provenance_card` 2000×1424 ｜ 三个 GLB。
**所有参赛材料一律出自这一个 run，不许混用**（`blessing` 字段跨 run 不一致：有的 run 是三个词，有的是一个词）。

**提交后复跑四条全绿**：50 例 OK ｜ M3 差分 525 配方 / 37 告警 / 覆盖 25-25 逐条一致 ｜
红线 0 命中 ｜ 版面自检 PASS。`git status --short` 空。

---

## 10. 已知限制（不许包装成已解决）

- **方盒竖棱处切半**：每面独立映射整条 strip（"一张图印一面"设计），n=2 铺满后 4 条棱各半只蝠，
  两半不严格可拼。口径：**主画面铺满四壁；竖棱处为通景近似，非严格无缝**。不写"不切半"。
- **方盒上下 84px 白带**是数学下限（区 1178×758 vs 方形母题，"完整 + 不拉伸"必然如此）。
  口径：**留白由 45.5% 降至 22.2%**，不写"无留白"。
- **atlas 39% 死区未回收**，只是不再计分。要回收得改 UV 公式，属高危区。
- **规则库无"场合必填"规则**：补一条会让"25 条"这个数字在断言 / README / 报告 / PPT 全部作废。
- **检索 Top-1 97%**（非 100%），纯 CLIP 基线 58%。
- **版权预警同门类误报 36.7%**（11/30），结构层对几何类改动（旋转 4° / 白边 5%）检出率为 0。
- **`dynasty` 全库为「不详」**，不虚构朝代。
- **母题库 100 条**（源数据全集），"详实"靠标注质量与来源可追溯，不靠条数堆砌。

### ★ 立论与数据源的张力（战略级，评审很可能追问）

Wényàng 的 100 张图是**原创 AI 辅助再设计，不是文物扫描件**（源仓库 README 明确声明
"不直接复制任何具体文物或受保护作品"）。而本作品第一章的立论是
「AI 生成的纹样不可信、不可溯源」——**样本库本身是 AI 图，立论存在张力**。

评委若问「**你溯源溯到哪里**」，需要准备好的回答口径。
**这不是代码缺陷，是必须主动交代的边界**；回答口径需 Mr.G 确认，**AI 不要自行编一套说辞**。
（2026-09-14 已识别，至今未定稿口径——接手后第一件事就是找 Mr.G 确认这条。）

---

## 11. 待办（按优先级）

### A. 材料缺口（当前最高优先）

1. **三份材料的核心指标全部没补齐**。`$PY scripts/check_metrics.py --strict` 报 **22 处缺失**
   （2026-10-28 实测），分布为：`纹初迹现.pptx` 缺 8 项、`剪纹有据_校赛答辩PPT - 副本.pptx` 缺 8 项、
   `作品名称与简介.md` 缺 6 项。
   缺失项集中在：元素溯源覆盖率、元素溯源准确率、文化规则检出率、检索 Top-5 命中率、
   版权预警检出率（结构层 / 语义层）、版权预警误报率（跨门类 / 同门类）。
   这是**材料缺口，不是代码缺陷**——补齐材料即可消除。注意该检查只验"指标覆盖率"，
   **不代表材料完整、也不代表指标取值正确**（脚本自己声明的边界）。
2. **报告措辞钉死"最终产物为 plain 路线"**。
   贴图有 plain / style 双路线，**只在「地子」（底色层）上不同**，纹样层完全相同。
   最终产物为 plain（style 走 wanx-v1 外部 API，补跑会给最终产物引入无法离线复现的依赖）。
   style 定位为"可选增强"。两模式的口径文案必须不同，写成一样的 = 口径失实：
   - plain：「载体层：程序化生成的标准几何体（非文物三维模型、非 AI 生成）」
   - style：「地子层：底纹取自 AI 风格化图（M5 输出），仅作渲染色底、不承载语义」
3. **端到端指标待测**：一句自然语言 → 最终母题是否正确，需人工标注测试集（README 标 ★ 待测）。

### B. 提交包

4. 确认两个提交包（正式版 / Web 演示版）的定稿关系（见 §0 第 2 条）。
5. 确认中间层占位目录名是否要改（见 §0 第 3 条）。
6. 换编号后重跑 `scripts/check_submission_pkg.py`。

### C. 代码

7. `tests/test_retrieval.py` 仍是 0 字节，待补 M2 检索测试。
8. C1 真实用户测试（`文档/C1_真实用户验证_启动包.md`）——此前被跳过，是否补做由人工定。

---

## 12. 仓库外文档（接手方需要人工提供）

以下在 `D:\work\work_space\DeskTop\DeskBox\竞赛\文档\`，**不进 git**，接手 AI 看不到，需人工拷贝：

| 文档 | 内容 |
|---|---|
| `B8_3D交付说明.md` | ★ 改 3D 前必读：三条铁律、自检脚本清单、环境坑、形态同步清单 |
| `B3_文化规则库设计方案.md` | 25 条规则的分类与约束类型 |
| `B6_版权预警双路与阈值标定_实施指引.md` | M7 双路与阈值标定 |
| `B7_Streamlit界面_实施指引.md` | 界面搭建过程 |
| `B1-5_外部数据源可行性验证.md` | 数据源选型与授权核查 |
| `实物佐证层_数据说明.md` | 克利夫兰 303 件字段与筛选口径 |
| `数据来源署名规范.md` | 署名要求 |
| `剪纹有据-项目技术报告.docx` | 技术报告（**旧作品名**，引用时注意） |
| `纹初迹现.pptx` / `纹初迹现_答辩PPT.pdf` | PPT（待补 6 项核心指标） |

---

## 13. 一页速查

```bash
cd /d/work/work_space/DeskTop/DeskBox/竞赛/work
PY=.venv/Scripts/python.exe

# 日常
$PY -m unittest discover -s tests          # 50 例
$PY scripts/check_rules.py                 # 规则库结构 + 引擎冒烟
$PY scripts/redline_check.py .             # 红线（提交前必跑，0 命中）
$PY scripts/check_m3_differential.py       # M3 差分回归
$PY scripts/check_board_layout.py          # 设计板版面
$PY scripts/check_metrics.py --strict      # 指标一致性（会报材料缺口）

# 改 3D 后
$PY scripts/check_render3d.py
$PY scripts/check_glb_uv.py --dir outputs/<recipe_id>
$PY scripts/preview_glb.py --dir outputs/<recipe_id> --out outputs/_chk.png
$PY scripts/check_style_ground.py

# 生成
$PY -m src.pipeline "做一个春节用的窗花，要喜庆"
$PY -m src.glb_export --recipe outputs/<recipe_id>

# 提交
git status --short          # 先看，只加明确路径
git add <明确路径>
$PY scripts/redline_check.py .
git commit -m "..."
```

---

## 14. 给接手 AI 的三条建议

1. **先跑通再改**。把 §3 的五分钟流程和 §8 的自检脚本各跑一遍，确认环境是好的，
   再动手改任何代码。历史上所有交付事故的根因都是"给之前没跑过"。
2. **事事以证据说话**。报数字必须实跑；不许 grep 源码数充当行为；不许把记忆里的数当现状。
   发现文档与实测不一致时，**以实测为准并回头修文档**。
3. **拿不准先问 Mr.G**，尤其是 §0 的四件事和一切对外口径。
   这个项目最硬的资产是"可溯源"这三个字，任何让它失实的改动都不值得做。
4. **旧日志里有宝**。`竞赛/.workbuddy/memory/2026-*.md` 保留了每天的实测记录，
   本文件只摘了跨会话仍成立的部分。要查某个结论的原始实测过程，去翻对应日期的日志。
