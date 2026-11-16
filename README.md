# 纹初迹现 · 传统纹样可溯源生成系统

> 参赛作品的技术实现。已通过对外材料合规自查，**不包含任何机构标识与人员身份信息**。

---

## 这是什么

AI 生成传统纹样已不稀奇，但结果普遍"三不"：**不可解释、不可追溯、不可控** ——
既说不清元素出处与文化依据，也难判是否与已有作品雷同，AIGC 因而进不了文创与版权交易场景。

本作品提出 **「可解释的组合式生成」** 范式：不让模型凭空画，而是

1. 把一句自然语言需求解析为结构化的《纹样文化配方》（场合 / 寓意 / 母题 / 配色）
2. 基于 Chinese-CLIP 从**真实纹样母题库**检索元素
3. 按传统构图程式组合
4. 生成的同时即确定每个元素的出处与授权（**非事后推测**）
5. 过一道**文化校验**（寓意冲突 / 场合失配 / 色彩越界）
6. 输出**元素级溯源卡片**
7. （可选）AI 风格化 + 3D 器物形态预览
8. 可审查任意设计图与本库的**版权相似度风险**
9. 提供**全库纹样谱系**（100 条母题的关联网络与五族划分）

> 一句话：**别人的 AI 给你一张图，本系统给你一张图 + 一张配料表。**

三条能力支柱对应**三种溯源层次**，互不替代：
**元素级**（每个部件的出处）→ **谱系级**（这类纹样跟谁最近）→ **风险级**（是否与库内雷同）。

---

## 赛事阶段与提交状态

> 本节只写可核对的事实；赛方未写明的项不推测、不补齐。

**当前阶段：全国半决赛**（第八届全球校园人工智能算法精英大赛 · 算法主题赛 · 智能文化）

| 节点 | 时间 |
|---|---|
| 材料提交截止 | **2026-11-19 23:59**（逾期视为弃赛） |
| 半决赛评审 | 2026-11-20 至 11-22，线上材料评审（答辩视频提前上传，评委集中评审） |
| 晋级规则 | 设 **60 分**基准分数线，**前 40%** 晋级全国总决赛 |

### 源码冻结声明

**主线代码冻结在 HEAD，不再接受功能性改动。** 原因不是"没时间"，而是规则决定的：半决赛答辩视频
要求**一镜到底、无剪辑**，录制完成后无法重剪，任何未经全量回归的改动都是**不可逆风险**。
因此本仓库当前状态即提交状态 —— `src/` / `scripts/` / `config.yaml` 与数据集不再变动；
除外的只有文档修正与指标复算。

### 定稿产物：材料取数只有唯一来源

**`outputs/R20261028160834-1A63`**，由 `src/run_source.py` 的 `FINAL_RUN` 常量固定指向
（仓库根绝对定位，不依赖当前工作目录）。

报告、PPT、作品简介里出现的每一个数值、每一张截图，**均出自这一个 run，不混用其他 run**。
`outputs/` 下另有历次调试 run，仅作过程留痕，**材料取数一律不引用**。
`scripts/check_final_run_immutable.py` 对定稿 run 做**逐字节不可变**基线校验。

### 提交物（报名系统，三类）

| 序号 | 提交物 | 说明 |
|---|---|---|
| 1 | 答辩 PPT | `../文档/半决赛/半决赛_终稿.pptx`，16 页 |
| 2 | 答辩视频 | 腾讯会议录制，一镜到底、全员出镜、**≤6 分钟**、内含作品演示；**替换**原视频，不并存 |
| 3 | 作品文件 | 赛题规则要求的作品文件（含本仓库代码与定稿 run 产物） |

### 材料为何不在本仓库

`../文档/` 目录在**本仓库之外**（与 `work/` 同级），不纳入版本控制。
原因：该目录存放赛方通知原件、内部备赛方案、历次沟通与核查记录，
**含机构与人员信息的内部文档不入库**。本仓库只保证"能跑出材料"，不承载材料本身。

---

## 快速开始

### 1. 环境

```bash
cd work
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # Windows
# 其他平台：.venv/bin/pip install -r requirements.txt
```

> **无需 GPU**，普通笔记本即可（CLIP 走 CPU）。
> torch 装的是 CPU 版；若默认源装不到，用
> `pip install torch --index-url https://download.pytorch.org/whl/cpu`。
> matplotlib 走国内镜像：`pip install matplotlib -i https://pypi.tuna.tsinghua.edu.cn/simple`

配 `.env`（从 `.env.example` 复制），填入：

```
DASHSCOPE_API_KEY=sk-xxxxxxxx     # 阿里云百炼，M1 意图解析与 M5 风格化要用
```

> 没有 key 时，M1 会退化为**规则兜底解析**（仍能跑通，但配方质量下降）。

### 2. 准备数据（首次）

```bash
.venv/Scripts/python.exe scripts/validate_samples.py    # 契约校验，应输出 [PASS]
.venv/Scripts/python.exe scripts/build_index.py         # 建向量索引（首次需下载 CLIP 权重）
```

### 3. 启动界面（推荐）

```bash
.venv/Scripts/python.exe -m streamlit run app.py
```

浏览器打开 http://localhost:8501 ，界面分三个标签页：

| 标签页 | 内容 |
|---|---|
| **生成与溯源** | ① 配方 → ② 元素检索 → ③ 文化校验 → ④ 溯源卡片 → ⑤ AI 风格化（可选）→ ⑥ 3D 文创预览 |
| **版权相似度审查** | 上传任意图片，与本库比对给出**风险分级**（M7） |
| **纹样谱系** | 全库 100 条母题的关联网络、五族谱系图、消融实验结果（**全库级视图**） |

三个标签页对应**三种溯源层次**：

- **元素级**（生成与溯源）—— 这张图的每个部件来自哪条母题，生成时即确定；
- **谱系级**（纹样谱系）—— 这类纹样在谱系上跟谁最近，元素级给不出的信息；
- **风险级**（版权审查）—— 一张设计图与本库是否雷同，会不会踩到已有纹样。

> ⚠️ 生成流程本身有依赖：先加载 CLIP 模型（首次约 20–40 秒），再走 ①→⑥。
> 「纹样谱系」页是**全库级**的，与当前配方无关，可独立查看，不必先生成。

在 ① 处输入一句需求（如「做一个有吉祥寓意的窗花，用于春节礼品包装」），点生成即可。

### 4. 或：纯命令行跑一次

```bash
# 只跑管线（结果在内存里，返回 dict）
.venv/Scripts/python.exe -c "
from src.pipeline import run
r = run('做一个春节用的窗花，要喜庆')
print(r['recipe']['recipe_id'], r['errors'])"

# 跑完并落盘到 outputs/<recipe_id>/
.venv/Scripts/python.exe -c "
from src.pipeline import run, save_all
save_all(run('做一个春节用的窗花，要喜庆'))"
```

产物落在 `outputs/<recipe_id>/`，含配方、检索结果、溯源卡片、设计依据板、组合纹样图。

### 5. 3D 预览与导出

```bash
# 单独导出某配方的三形态 GLB（梅瓶 / 方盒 / 团扇）
.venv/Scripts/python.exe -m src.glb_export --recipe outputs/<recipe_id>
```

产物 `.glb` 是业界通用格式，可拖进 Blender / Unity 或任意在线 glTF 预览器。
界面 ⑥ 区也内嵌了 Three.js 查看器，可直接旋转查看并下载。

> ★ 改 3D 代码前**先读** `../文档/省赛/B8_3D交付说明.md`（三条铁律 + 自检脚本 + 已踩的坑）。

### 6. 重新生成纹样谱系图

```bash
.venv/Scripts/python.exe scripts/build_kinship_graph.py
```

产物落在 `docs/figures/`：五族谱系图 + 母题关联网络 + 元素共现网络 + 统计 JSON。
界面的「纹样谱系」页直接读这些文件；**指标卡与五族名单是从 `samples.json` 现算的**，
不写死在代码里（数据一变，图与文字会不同步）。

```bash
# 可选：控制网络图上标注的节点数
.venv/Scripts/python.exe scripts/build_kinship_graph.py --top-label 30
```

---

## 系统架构

### 七模块主链路

| 模块 | 文件 | 职责 |
|---|---|---|
| **M1** 意图解析 | `src/m1_intent.py` | 一句话 →《纹样文化配方》（LLM + 规则兜底） |
| **M2** 元素检索 | `src/m2_retrieve.py` | Chinese-CLIP + faiss，**三招调优**（类别前缀 / 多查询 / 元素二次筛选） |
| **M3** 文化校验 | `src/m3_validate.py` | 25 条文化规则，四类约束引擎 |
| **M4** 设计依据板 | `src/m4_compose.py` | 素材 + 配方 → 可视化依据板（`compose_board`） |
| **M4a** 组合纹样合成 | `src/m4_compose.py` | 按构图程式把检索到的元素**真合成**成纹样图（`compose_pattern`） |
| **M5** AI 风格化 | `src/m5_stylize.py` | 可选。**输出不可溯源**，与溯源严格分区 |
| **M6** 溯源卡片 | `src/m6_provenance.py` | 元素 → 出处 → 寓意 → 授权 |
| **M7** 版权预警 | `src/m7_copyright.py` | 双路相似度（感知哈希 + CLIP 语义），输出**风险分级** |
| **B7** 演示界面 | `app.py` | Streamlit 入口 |

> **M4 与 M4a 同在 `src/m4_compose.py`**：M4 产出"依据板"（给人看的素材与理由），
> M4a 产出"组合纹样图"（真正的图案，供 M5 风格化与 3D 贴图使用）。
> 两者是**上下游关系**而非同一件事 —— 依据板解释"为什么这样组合"，组合图是组合的结果。

### 三种溯源层次

| 层次 | 在哪里 | 回答的问题 | 数据来源 |
|---|---|---|---|
| **元素级** | 生成与溯源页 | 这张图的每个部件来自哪条母题？ | `elements` 字段，生成时即确定 |
| **谱系级** | 纹样谱系页 | 这类纹样在谱系上跟谁最近？ | `related_motifs` 字段（100 母题 / 385 边 / 5 族） |
| **风险级** | 版权审查页 | 这张设计图与本库是否雷同？ | 感知哈希 + CLIP 语义双路比对 |

**谱系级不提升检索准确率**（消融实验证明 `expand`/`boost` 三种输入下均无正收益，
详见「关键指标」），它提升的是**可解释性** —— 这正是本系统立项要解决的问题。

### 两层数据架构（★ 口径关键）

| 层 | 来源 | 规模 | 作用 | 是否参与元素级溯源 |
|---|---|---|---|---|
| **语义层**（母题库） | Wényàng | **100 条** | M2 检索依据 / M3 校验依据 | ✅ **是** |
| **实物佐证层** | 克利夫兰艺术博物馆 | 303 件 | **仅提供织物肌理（材质层）** | ❌ 否 |

**实物佐证层为什么不参与溯源**：它没有 `name`（中文母题名）/ `elements`（构成元素）/
`meaning`（寓意）字段。用模型去编这些字段，等于重蹈「用 AI 生成的内容充当文化依据」的覆辙。

**因此对外一律表述为**：纹样层元素级可溯；材质层仅实物可溯。**两者不得混称 100% 可溯源。**

### 3D 交付链（B8）

```
配方 → pattern_layout 分区贴图 ┬→ preview3d 静态三联图
                              └→ glb_export → GLB ─→ Three.js 查看器 + 下载
```

三种形态，各自一套布局几何（**布局几何必须匹配载体几何**）：

| 形态 | 布局 |
|---|---|
| 梅瓶（旋转体） | 环一圈展开图 |
| 包装方盒 | 一张图印一面（不绕圈） |
| 团扇（圆平面） | 极坐标同心 |

---

## 目录结构

```
work/
├── app.py                   Streamlit 界面（B7）
├── config.yaml              统一配置：模型名 / 阈值 / 路径 / 传统色板
├── requirements.txt         运行依赖
├── redline.yaml             红线词表（**不入库**，仅本地保留）
├── src/                     处理管线（22 个模块 + __init__.py）
│   ├── m1_intent.py         ① 需求解析：一句话 → 《纹样文化配方》（LLM + 规则兜底）
│   ├── m2_retrieve.py       ② 元素检索：CLIP + faiss 三招调优（类别前缀 / 多查询 / 元素二次筛选）
│   ├── m3_validate.py       ③ 文化校验：25 条规则的约束引擎
│   ├── m4_compose.py        ④ 设计依据板（compose_board）+ ④a 组合纹样真合成（compose_pattern）
│   ├── m5_stylize.py        ⑤ AI 风格化（**可选、默认不启用**，输出不进溯源卡片）
│   ├── m6_provenance.py     ⑥ 溯源卡片：元素 → 出处 → 寓意 → 授权
│   ├── m7_copyright.py      ⑦ 版权预警：pHash + CLIP 双路相似度，输出风险分级
│   ├── pipeline.py          端到端编排（任单点失败不中断整条链路）
│   ├── artifact_layer.py    实物佐证层读取：只提供织物肌理（材质层），不参与语义检索
│   ├── clip_model.py        CLIP 加载与编码（lru_cache 单例，M2 / M7 共用同一份权重）
│   ├── semantic_match.py    确定性语义匹配：用 100 条真源给出可复现的匹配理由
│   ├── pattern_layout.py    语义结构 → 器物装饰结构：3D 分区贴图（展开图 / 极坐标 / 盒盖）
│   ├── preview3d.py         3D 静态预览：自写解析求交光线投射（纯 CPU、零新依赖、确定性）
│   ├── glb_export.py        glTF 2.0 二进制（.glb）导出，纹样作为贴图嵌入
│   ├── ai_texture.py        方案 1：AI 生成图作 3D 贴图源（默认档，只换像素不换几何）
│   ├── ai_mesh.py           方案 2：图转 3D 的**接口骨架**（不接外部服务、零网络调用）
│   ├── ai_routes.py         3D 能力路线注册表：哪条路线可用 / 默认档是什么的单一真源
│   ├── style_ground.py      从 M5 风格化图提取 3D 贴图"地子"（底纹 / 底色）
│   ├── disclosure.py        溯源声明文案的单一真源（界面与 3D 查看器共用）
│   ├── run_source.py        定稿 run（FINAL_RUN）的单一真源，绝对定位不依赖 cwd
│   ├── wizard.py            六步向导的叙事编排（纯数据 + 状态派生，不含渲染）
│   └── utils.py             相对路径 → 绝对路径解析
├── scripts/                 工具与自检（44 个脚本）
│   ├── 【数据构建】
│   │   wenyang_to_samples.py     源数据 patterns.json → samples.json（只做机械转换）
│   │   enrich_samples.py         补录源数据未用字段（关联纹样 / 色彩建议），只增不改
│   │   auto_annotate.py          LLM 批量标注 occasion / elements
│   │   review_annotation.py      生成人工抽检清单（只读，不改数据）
│   │   apply_annotation.py       把人工确认结果合并回 samples.json（只动 occasion/elements）
│   │   fix_carriers.py           一次性修正：按新拆分逻辑重跑指定范围的 carrier / applications
│   │   fetch_artifacts.py        The Met 公版中国文物（备用佐证层），不碰 samples.json
│   │   fetch_cleveland.py        克利夫兰 Open Access 中国织物 303 件（实物佐证层）
│   │   filter_cleveland.py       纹理丰富度打分，筛出可作纹样素材的那部分
│   │   eval_filter_methods.py    用 20 张人工标注比对几种筛选方法（选方法的证据脚本）
│   │   build_index.py            建 faiss 向量索引 + id_order 行号反查表
│   │   build_kinship_graph.py    纹样谱系图（五族谱系 + 母题关联网络 + 元素共现）
│   │   exp_related_motifs.py     关联纹样检索增强实验（负结论的出处）
│   │   merge_report.py           把报告分片按固定顺序合并成完整报告 + 缺章体检
│   │   make_arch_diagrams.py     生成架构图 / 流程图 / 三种溯源层次图
│   │   make_data_summary.py      JSON 数据 → 报告可直接引用的 Markdown 摘要
│   │   gen_forms_json.py         由 preview3d.FORMS 生成形态集注册表（禁止手写键值）
│   ├── 【自检 · 数据与指标】
│   │   validate_samples.py       样本库契约校验（schema §1.4，失败即拒绝入库）
│   │   check_rules.py            规则库结构校验（25 条 / 唯一 id / 约束类型分布）
│   │   check_m3_differential.py  M3 规则引擎差分回归（黄金快照，证明重构没改判定）
│   │   calibrate_m7.py           M7 阈值标定 + 按改动类型拆解诊断（B6 / B6b，产出 m7_calibration.json）
│   │   check_metrics.py          报告 / PPT / 作品简介三处取数一致性
│   │   check_ai_boundary.py      AI 新产物边界四条断言（只读）
│   │   check_merge_contract.py   两工程合并的七项结构性断言（只读）
│   │   check_final_run_immutable.py  定稿 run 逐字节不可变基线
│   │   test_culture_rules.py     规则检出率与**真实配方上的误报率**
│   ├── 【自检 · 3D 与界面】
│   │   check_render3d.py         法线朝向 + NaN 污染
│   │   check_glb_uv.py           从 .glb 字节流独立重解析（UV 越界 / 采空白 / 索引）
│   │   preview_glb.py            独立 z-buffer 渲染（交叉验证贴图方向）
│   │   check_glb_sync.py         GLB 在三处（产物 / static / web）是否同源
│   │   check_style_ground.py     贴图双路线均可渲染 + 地子来源必须不同
│   │   check_board_layout.py     设计板版面：元素遮挡 / 出框 / 幂等 / 取值长度变体
│   │   check_viewer_forms_sync.py 形态集注册表一致性门卫（只读）
│   │   check_app_embed.py        界面 ⑥ 区嵌入链路（★ 需服务已在跑）
│   ├── 【验收 · 冒烟】
│   │   smoke_clip.py             读一张图 → 512 维向量 → 检查 L2 范数 ≈ 1.0
│   │   smoke_m1.py               20 个请求跑 M1，统计结构完整率等三项
│   │   smoke_retrieve.py         用库内母题检索自身，看 Top-1 是不是它自己
│   ├── 【截图 · 自动化】
│   │   shots.py                  CDP 驱动界面截图（报告用全套）
│   │   shots_step.py             专抓「04 分步进度」（st.status 只在生成过程中存在）
│   │   shots_web.py              驱动 Web 版走到「文化配方」「元素溯源卡片」
│   ├── 【打包 · 合规】
│   │   redline_check.py          红线自查：扫描目录全文，命中即报错退出
│   │   make_submission_package.py     按赛方四分类打包主版本（可执行 / 模型数据 / 源码 / 图纸）
│   │   make_submission_package_web.py 打包 Web 演示版（work_two）提交材料
│   │   check_submission_pkg.py        模拟"三份材料合并"，核对路径齐备与冲突
│   └── final_run_baseline.json   定稿 run 基线数据（**数据文件，非脚本**）
├── data/
│   ├── samples.json         纹样母题库（100 条，契约见 docs/schema.md）
│   ├── images/              母题参考图
│   ├── index/               向量索引产物
│   ├── artifacts_cle/       克利夫兰实物佐证层
│   └── raw/                 源数据
├── rules/culture_rules.json 文化规则库（25 条）
├── docs/
│   ├── schema.md               数据契约（冻结）
│   ├── metrics.json            ★ 指标单一事实来源
│   ├── m7_calibration.json     M7 阈值标定
│   ├── exp_related_motifs.json 关联数据消融实验（含负结论）
│   ├── m3_guard_matrix.md      规则-场景矩阵
│   ├── redline_notes.md        红线自查口径与历史命中说明
│   └── figures/                图表产物（含 kinship_*.png / kinship_stats.json）
├── web/                     Three.js 查看器（源码，必须入库）
│   ├── viewer.html
│   └── vendor/              three.min.js r147 + GLTFLoader.js
├── static/                  web/ 的运行时副本（不入库，自动生成）
├── tests/                   单元测试：test_rules.py（M3 规则引擎，50 例通过）、test_retrieval.py（检索契约，9 例通过）；均以 `python tests/xxx.py` 直接运行，环境未装 pytest
└── outputs/                 运行产物（不入库；定稿 run 见上文「赛事阶段与提交状态」）
```

---

## 关键指标

> ★ **单一事实来源是 `docs/metrics.json`**。报告 / PPT / 作品简介取数一律引用它，
> 不得到处自算。校验脚本：`scripts/check_metrics.py`。

| 指标 | 结果 | 状态 |
|---|---|---|
| 元素溯源覆盖率 | **100%** | 已达成（架构保证） |
| 元素溯源准确率 | — | ★ 待测（依赖 C3 测试集） |
| 文化规则检出率 | **100%**（5/5） | 已达成（误报 0/3） |
| 检索 Top-5 命中率 | **100%** | 已达成（**索引层自检索、非端到端**，100 条全量） |
| 检索 Top-1 命中率 | **97%** | 已达成 |
| 版权预警检出（语义层） | **100%** | 已达成 |
| 版权预警检出（结构层） | 49.2% | ★ 未达标：对几何类改动完全失效 |
| 版权预警误报（跨门类） | 0 / 30 | 已达成 |
| 版权预警误报（同门类） | 11 / 30 = **36.7%** | ★ 未达标，已列入不足 |

### 消融实验（证明每项策略的必要性）

| 配置 | Top-1 |
|---|---|
| 完整（三招） | **97%** |
| 关闭元素二次筛选 | 58% |
| 关闭类别前缀 | 98% |
| 查询只用母题名 | 78% |

**输入侧消融**：配方只有母题名 → 59%；母题名 + 元素（生产口径）→ 97%。
说明**检索的区分度主要来自 elements，不是母题名**。

**关联数据消融**（`docs/exp_related_motifs.json`）：

| 检索输入 | 基线 Top-1 | + 关联扩展 `expand` | + 关联加权 `boost` |
|---|---|---|---|
| 仅名称 | 0.59 | 0.19 | 0.16 |
| 名称 + 元素 | 0.97 | 0.96 | 0.94 |
| 仅元素 | 0.96 | 0.94 | 0.91 |

**三种输入下关联数据均无正收益**。这是本项目如实报告的一条**负结论**：
谱系数据的价值在**可解释性**，不在准确率。界面的「纹样谱系」页把这条结论直接写给使用者看。

---

## 数据来源与授权

> ★ 本节为**强制性声明**，不得删除或改写。

### 纹样母题库

纹样图像与文字资料：**BLCaptain（爆裂队长NEXT）**，《中国传统纹样图鉴 Wényàng》，
https://github.com/dososo/chinese-traditional-patterns ，授权协议 **CC BY-NC 4.0**
（署名 · 非商业性使用）。本项目仅对原始字段做规范化处理，并补充标注「使用场合」
与「构成元素」两项派生字段；**纹样图像本身未作修改**。

- 图片与文字内容：**CC BY-NC 4.0**（署名 · 限非商业）
- 代码与数据结构：**MIT**

### 实物佐证层

文物图像与元数据：**克利夫兰艺术博物馆（Cleveland Museum of Art）Open Access**，
**CC0**（公有领域，不限用途）。每件记录保留馆藏编号与来源链接。
（备用：**The Metropolitan Museum of Art Open Access**，同为 CC0。）

### 使用范围

本作品为**学术竞赛用途，不涉及商业使用**。依据 CC BY-NC 4.0 的非商业条款，该用途在许可范围内；
若后续转为商业应用，需另行向原作者取得授权。

### 本项目不使用的数据源

**故宫博物院数字文物库**：其授权条款明确禁止"利用画面作为素材进行 AI 创作、全部二次创作行为"
以及"制作 VR / AR / 小程序 / APP / H5 等具有线上、线下数字展示行为"，与本作品的用法直接冲突，
故**未采用**。详见 `../文档/省赛/B1-5_外部数据源可行性验证.md`。

---

## 说明与边界

### 各指标的口径

- **索引层自检索**：输入为「库内母题名 + 该母题构成元素」，检索对象为同批 100 条。
  衡量**排序质量**，**不等同于端到端准确率**。之所以输入库内名称，
  是因为 M1 的母题选择受**白名单约束**（只能从库内选）——这是架构决定的，不是测试集取巧。
- **端到端指标**：★ 待测。一句自然语言需求 → 最终母题是否正确，需人工标注测试集（与 C3 合并执行）。

---

## 常见问题

**Q：跑起来报 `No module named 'faiss'`？**
用了系统 Python。**一律用 `.venv/Scripts/python.exe`**。

**Q：没有 DASHSCOPE_API_KEY 能跑吗？**
能。M1 会退化为规则兜底解析，M5 风格化不可用，其余模块正常。

**Q：⑥ 区 3D 查看器白屏？**
依次检查三处（详见 `../文档/省赛/B8_3D交付说明.md`）：
① 静态目录必须是 `<app_dir>/static`（**不是** `.streamlit/static/`）；
② `.streamlit/config.toml` 里 `server.enableStaticServing = true`；
③ iframe URL 必须带前导斜杠 `/app/static/...`。
启动日志里的 `no static folder found at ...` 是唯一线索。

**Q：改 3D 贴图后要跑什么？**
五个自检脚本（用法见 `../文档/省赛/B8_3D交付说明.md` 第五节）：

```bash
PY=.venv/Scripts/python.exe
$PY scripts/check_render3d.py                              # ① 法线朝向 + NaN
$PY scripts/check_glb_uv.py --dir outputs/<recipe_id>      # ② GLB 独立重解析
$PY scripts/preview_glb.py --dir outputs/<recipe_id> --out outputs/_chk.png   # ③ 独立渲染验方向
$PY scripts/check_style_ground.py                          # ④ 贴图双路线
$PY scripts/check_app_embed.py --port 8794                 # ⑤ 界面嵌入（需服务在跑）
```

改任何 UV 相关代码后**必须同时验静态预览与 GLB**，否则"预览看到的"≠"下载到的"。
其中 ② 与 ③ 是**两条独立实现**（字节流重解析 / 独立 z-buffer 光栅化）——
数值自检查不出"上下颠倒 / 左右镜像"，只有交叉验证才能发现。

**Q：为什么不用故宫数字文物库的图？**
授权明确禁止 AI 创作与数字展示，与本作品用法直接冲突。见上文「不使用的数据源」。

**Q：为什么「纹样谱系」要单独一个标签页，不放进生成流程末尾？**
它是**全库级**视图（100 条母题之间的关联），跟"某一个配方怎么生成"无关。
放进生成页会让使用者误以为它跟当前配方有关。
区分两种溯源：生成页是**元素级**（每个部件来自哪条母题），
谱系页是**谱系级**（这类纹样跟谁最近）—— 两者互补，不是同一件事。

**Q：谱系图能提升检索准确率吗？**
不能，实测也没有。消融实验显示关联数据在三种输入下均无正收益。
它的价值在**可解释性**与结果列表的相关参考。
界面「纹样谱系」页 ④ 区把这条**负结论**直接写给使用者看，不做包装。

---

## 相关文档

`../文档/省赛/` 目录（**仓库外**，与 `work/` 同级，不含机构信息）。下列路径相对本 README 所在目录书写：

| 文档 | 内容 |
|---|---|
| `../文档/省赛/B8_3D交付说明.md` | ★ 3D 部分：三条铁律、自检脚本、环境坑 |
| `../文档/省赛/B7_Streamlit界面_实施指引.md` | 界面搭建过程 |
| `../文档/省赛/B3_文化规则库设计方案.md` | 25 条规则的分类与约束类型 |
| `../文档/省赛/B6_版权预警双路与阈值标定_实施指引.md` | M7 双路与阈值标定方法 |
| `../文档/省赛/B6b_按改动类型拆解_实施指引.md` | 按改动类型诊断 phash/CLIP 表现 |
| `../文档/省赛/B1-5_外部数据源可行性验证.md` | 数据源选型与授权核查 |
| `../文档/省赛/实物佐证层_数据说明.md` | 克利夫兰 303 件字段与筛选口径 |
| `../文档/省赛/数据来源署名规范.md` | 署名要求 |

---

## 合规说明

- 本仓库**不含**校名 / LOGO / 教师姓名 / 群号 / 邀请码等身份信息。
- 提交前自查：`scripts/redline_check.py`（词表在 `redline.yaml`，不入库）。
- 母题参考图与实物佐证图**不入库**（体积大且可脚本重现），仅入库索引与元数据。
