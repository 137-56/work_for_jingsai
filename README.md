# 纹有其源 · 传统纹样可溯源 AI 生成系统

> 本仓库是参赛作品的技术实现，已通过对外材料合规自查，**不包含任何机构标识与人员身份信息**。

---

## 这是什么

AI 生成传统纹样已不稀奇，但结果普遍"三不"：**不可解释、不可追溯、不可控** —— 不知元素出处与文化依据，也难判是否与已有作品雷同，AIGC 因而进不了文创与版权交易场景。

本作品提出**「可解释的组合式生成」**范式：不让模型凭空画，而是

1. 把一句自然语言需求解析为结构化的《纹样文化配方》（场合 / 寓意 / 母题 / 配色）
2. 基于 Chinese-CLIP 从**真实纹样母题库**检索元素
3. 按传统构图程式组合
4. 生成的同时即确定每个元素的出处与授权（**非事后推测**）
5. 过一道**文化校验**（寓意冲突 / 场合失配 / 色彩越界）
6. 输出**元素级溯源卡片**

一句话：**别人的 AI 给你一张图，本系统给你一张图 + 一张配料表。**

---

## 目录结构

```
work/
├── src/                     处理管线
│   ├── m1_intent.py         ① 需求解析：一句话 →《纹样文化配方》
│   ├── m2_retrieve.py       ② 元素检索：Chinese-CLIP + faiss（三招调优）
│   ├── m3_validate.py       ③ 文化校验：四类约束引擎
│   ├── m6_provenance.py     ⑥ 溯源卡片：元素 → 出处 → 寓意 → 授权
│   ├── clip_model.py        CLIP 单例加载
│   ├── pipeline.py          端到端编排
│   └── utils.py             配置与路径解析
├── scripts/                 一次性工具与自检
│   ├── wenyang_to_samples.py   源数据 → samples.json（支持 --append 增量）
│   ├── enrich_samples.py       补录源数据未用字段（关联纹样 / 色彩建议）
│   ├── auto_annotate.py        LLM 批量标注 occasion / elements
│   ├── review_annotation.py    标注抽检清单（只读）
│   ├── apply_annotation.py     抽检结果合并回 samples.json（带写盘前体检）
│   ├── validate_samples.py     契约校验（10 条规则）
│   ├── build_index.py          建向量索引
│   └── fetch_artifacts.py      （备用）抓取公版文物佐证
├── data/
│   ├── samples.json         纹样母题库（100 条，契约见 docs/schema.md）
│   ├── images/              母题参考图
│   └── index/               向量索引产物
├── rules/culture_rules.json 文化规则库
└── docs/schema.md           数据契约（冻结）
```

---

## 环境与运行

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt        # Windows；其他平台用 .venv/bin/pip

# 数据侧
.venv/Scripts/python.exe scripts/validate_samples.py        # 契约校验，应输出 [PASS]
.venv/Scripts/python.exe scripts/build_index.py             # 建索引

# 跑一次完整管线
.venv/Scripts/python.exe -c "from src.pipeline import run; run('做一个春节用的窗花，要喜庆')"
```

无需 GPU，普通笔记本即可运行（CLIP 走 CPU）。

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

### 公版文物佐证（备用，未纳入主流程）

文物图像与元数据：**The Metropolitan Museum of Art Open Access**，**CC0**（公有领域，不限用途）。
每件文物记录保留馆藏编号与来源链接。

### 使用范围

本作品为**学术竞赛用途，不涉及商业使用**。依据 CC BY-NC 4.0 的非商业条款，该用途在许可范围内；
若后续转为商业应用，需另行向原作者取得授权。

### 本项目不使用的数据源

**故宫博物院数字文物库**：其授权条款明确禁止"利用画面作为素材进行 AI 创作、全部二次创作行为"
以及"制作 VR / AR / 小程序 / APP / H5 等具有线上、线下数字展示行为"，与本作品的用法直接冲突，
故**未采用**。详见 `文档/B1-5_外部数据源可行性验证.md`。

---

## 说明与边界

- **母题库规模为 100 条**（数据源全集）。本作品的"详实"靠**标注质量与来源可追溯**，不靠条数堆砌。
- **`dynasty` 字段全库为「不详」**：源数据不含朝代信息，且纹样母题本身跨朝代
  （如缠枝莲纹自唐沿用至清），填具体朝代属编造。**本项目不虚构朝代。**
- CLIP 对细粒度纹样的区分能力有限，检索依靠**语义层硬约束**（构成元素二次筛选）兜底 ——
  消融实验显示关闭该层会使 Top-1 从 97% 降至 58%。
- 各项指标的测试集规模与测量方法见 `docs/metrics.json`。
