# 接口契约（冻结版 v1.0）

> 本文件是 A 线（工程）与 B 线（内容）之间**唯一的硬接口**。
> **冻结日期：2026-09-14** ｜ 冻结后不再改动，除非两人同时在场。
> 谁的文件谁改，**绝不交叉编辑同一个文件**。
> 冻结对象共**三份**：`samples.json`（§1）、`culture_rules.json`（§2），以及二者共同依赖的 `Recipe` 配方结构（§3）。

---

## 0. 为什么这份文档必须先写

两个人并行开发时，唯一的失败原因就是"接口对不上"。schema 一改，两边都要返工。
**宁可第一天少写代码，也要把 schema 定死。**

数据流向：

```
B 产出 ──→ data/samples.json        ──→ A 消费（建索引、检索、溯源卡片）
B 产出 ──→ rules/culture_rules.json ──→ A 消费（文化校验）
A 产出 ──→ src/*.py、scripts/*.py    ──→ 提供脚本给 B 调用
```

---

## 1. `data/samples.json` — 纹样样本库元数据

### 1.1 文件形态

UTF-8 编码的 **JSON 数组**，每个元素是一个样本对象。

```json
[
  {
    "id": "WENYANG-001",
    "name": "缠枝莲纹",
    "category": "植物花卉纹",
    "dynasty": "不详",
    "carrier": ["瓷器", "织锦", "刺绣", "家具", "屏风", "建筑装饰"],
    "applications": [],
    "meaning": "以莲花与卷曲藤蔓连续展开，常见于瓷器、织锦与建筑装饰。寓意清雅、连绵、生生不息。",
    "occasion": ["文人雅玩", "日常陈设"],
    "elements": ["莲花", "卷草", "藤蔓"],
    "related_motifs": ["宝相花纹", "牡丹纹", "菊花纹", "莲瓣纹", "卷草纹"],
    "palette": [
      {"colors": ["青绿", "米白", "浅金"], "style": "清雅古典"},
      {"colors": ["朱砂", "墨绿", "金色"], "style": "华丽富贵"}
    ],
    "source": "中国传统纹样图鉴 Wényàng",
    "source_url": "https://github.com/dososo/chinese-traditional-patterns",
    "license": "CC BY-NC 4.0（署名 · 限非商业用途）",
    "image_path": "data/images/WENYANG-001.jpg",
    "phash": "ce4e91d9d2b241b5",
    "clip_vec_index": 0
  }
]
```

> ⚠️ **本示例 2026-09-18 已更正。** 原为 `GUGONG-108723` + `license: "公版 / Open Data"`，
> 那套口径来自"用故宫博物院数字文物库作主数据源"的旧方案，**该方案已作废**——
> 故宫授权明确禁止 AI 创作与数字展示（见 `文档/B1-5_外部数据源可行性验证.md`）。
> **照旧示例写会写出错误的授权声明。**

### 1.2 字段定义

| 字段 | 类型 | 必填 | 说明 | 约束 |
|---|---|---|---|---|
| `id` | string | ✅ | 样本唯一标识 | 全局唯一；建议 `<来源前缀>-<原始编号>`；**建库后不得修改**（phash/向量都依赖它） |
| `name` | string | ✅ | 母题名 | **主键级字段**，母题白名单由此生成；2–8 字，不含标点 |
| `category` | string | ✅ | 纹样类别 | 只能取下方枚举值之一 |
| `dynasty` | string | ⬜ | 朝代 | **现状：全库 100 条均为「不详」**，原因见下方注 · 不虚构 |
| `carrier` | string[] | ✅ | 常见载体（可多个） | 数组；每项须在下方载体词表内 |
| `meaning` | string | ✅ | 文化寓意 | 20–60 字，**须在文化上说得通**（人工抽检） |
| `occasion` | string[] | ✅ | 适用场合 | 数组；取值须来自下方场合词表 |
| `elements` | string[] | ✅ | 构成元素 | 数组；每项 2–6 字；是 M2 二次筛选与 M3 校验的输入 |
| `related_motifs` | string[] | ⬜ | **关联纹样**（可选字段，2026-09-18 登记） | 源数据「关联纹样」段的原文条目，**已剔除自指**。全库 100 条共 524 个关联，其中 505 个指向本库内的真实母题 → 供 M2 查询扩展与"同族近邻可解释"使用。**不参与校验、不参与 M3 规则** |
| `palette` | object[] | ⬜ | **色彩建议**（可选字段，2026-09-18 登记） | 每项 `{"colors": string[], "style": string}`。源数据「色彩建议」段（实测有 6 种写法，统一由词表匹配解析）。供 M4 设计依据板提供配色依据。**不参与校验、不参与 M3 规则** |
| `source` | string | ✅ | 来源机构 | 如「中国传统纹样图鉴 Wényàng」 |
| `source_url` | string | ✅ | 出处链接 | **完整可用、不截断**；CC BY-NC 要求链接指向原仓库 |
| `license` | string | ✅ | 授权类型 | **红线相关，不得为空**；如实填写，**不得写成比实际更宽松的授权** |
| `image_path` | string | ✅ | 本地图片相对路径 | 相对工程根目录，如 `data/images/<id>.jpg` |
| `phash` | string | ⬜ | 感知哈希（十六进制） | 建库后由 `scripts/check_phash.py` 回填；M7 使用 |
| `clip_vec_index` | int | ⬜ | 在 `clip_vectors.npz` 中的行号 | **由 `scripts/build_index.py` 自动回填，B 不要手写**；与 faiss 索引行号一一对应 |
| `applications` | string[] | ⬜ | **应用场景**（可选字段，2026-09-17 登记） | 来自数据源「常见载体」段里**不属于受控词表**的词（如「海报背景」「游戏美术」「网站视觉资料库」）。**不参与校验、不参与 M3 规则**，仅供报告引用"作品可应用于哪些场景" |

**关于 `dynasty` 为什么全库为「不详」（2026-09-18 实测，非疏漏）**：

1. **数据源不含朝代信息**。对 100 条源数据的全量检索，「新石器/商/西周/…/清/民国」等词带「代/朝/时期/风格/式」后缀的命中数为 **0**。
2. **母题在语义上本就不对应单一朝代**。「缠枝莲纹」自唐沿用至清，「回纹」自商周青铜沿用至清瓷器 —— 给它填一个朝代反而是错的。
3. 原本预期的朝代来源（故宫博物院数字文物库）**已因授权问题排除**。
4. 因此该字段**由必备（✅）降为可选（⬜）**，并保留「不详」作为诚实标记。**本项目不虚构朝代**——报告「数据来源与边界」章节按此如实说明。

### 1.3 受控词表（尽量对齐，新值需两人确认）

**`category` 允许值：**
```
植物花卉纹 / 动物瑞兽纹 / 几何锦纹 / 云水山石纹 / 吉祥器物纹 / 文字福寿与组合纹 / 人物故事纹
```

> 前 6 类与主数据源（Wényàng）逐字一致；「人物故事纹」为后续接入故宫数据预留。
> 原「器物图文纹」已统一为「吉祥器物纹」，「文字吉语纹」已统一为「文字福寿与组合纹」。

**`carrier` 允许值：**
```
瓷器 / 织锦 / 刺绣 / 家具 / 屏风 / 建筑装饰 / 建筑彩画 / 石雕 / 木雕 / 服饰 / 壁画 / 漆器 / 玉器 / 金银器 / 剪纸 / 民俗装饰 / 青铜器 / 陶器 / 砖雕 / 年画 / 书画 / 文房器物 / 宗教法器 / 首饰 / 不详
```

> 词表已与主数据源的实际用词对齐。**判据：它是不是一个具体的物 / 工艺门类。**
> 「织绣」「织物」「织物边饰」等变体在导入时归并为「织锦」（见 `scripts/wenyang_to_samples.py` 的 `CARRIER_ALIAS`）。
> 「不详」是兜底值：数据源确实没给传统载体时用它，比留空诚实。
> **「海报背景」「游戏美术」这类应用场景不属于载体** —— 导入时归入 `applications` 字段，不进词表。
> **刻意排除「文创产品」「包装设计」** —— 那是现代应用场景，不是载体，放进来会污染 M3「载体—密度」规则的语义。

**`occasion` 词表：**
```
春节 / 婚庆 / 寿诞 / 开业 / 乔迁 / 节庆通用 / 日常陈设 / 祭祀 / 文人雅玩
```

> 新增受控值**不修改本契约结构**，只扩充取值即可，但须在两人群里说一声。

### 1.4 建库强制校验（A 写、B 执行）

`scripts/validate_samples.py` 必须检查：
1. `id` 唯一；
2. `name` / `license` / `source_url` 非空；
3. `occasion` / `elements` 是数组（不是字符串）；
4. `category` / `carrier` 在受控词表内；
5. `image_path` 指向的文件真实存在。

任一项不通过 → **拒绝入库**，不允许"先放着后面补"。

---

## 2. `rules/culture_rules.json` — 文化规则库

### 2.1 文件形态

UTF-8 编码的 **JSON 数组**，每个元素是一条规则，采用"**触发—约束—动作**"三段式。

```json
[
  {
    "id": "R001",
    "name": "场合-意象冲突检查",
    "version": "1.0",
    "severity": "high",
    "source": "《中国传统吉祥图案》相关章节 + 传统民俗通行认知",
    "trigger": {
      "op": "any",
      "conditions": [
        { "field": "intent.occasion", "op": "intersect", "value": ["婚庆", "春节", "寿诞", "开业"] }
      ]
    },
    "constraint": {
      "type": "forbidden_terms",
      "scope": ["structure.center_motif.elements", "intent.blessing"],
      "terms": ["菊花", "素白主色", "挽联纹"],
      "aliases": { "菊": "菊花", "白菊": "菊花" }
    },
    "action": {
      "message": "喜庆场合不宜使用「{term}」，建议替换为「{suggestion}」",
      "suggestions": { "菊花": "牡丹 / 莲花", "素白主色": "正红 / 金色" }
    }
  }
]
```

### 2.2 字段定义

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | ✅ | 形如 `R001`；**全局唯一、不复用**（报告与测试用例都要引用） |
| `name` | string | ✅ | 规则名，人类可读 |
| `version` | string | ✅ | 规则版本，如 `1.0` |
| `severity` | string | ✅ | `high` / `medium` / `low`，**只能是这三个值** |
| `source` | string | ✅ | **文献或资料依据，不得为空**——可审计性的体现 |
| `trigger` | object | ✅ | 触发条件，见 2.3 |
| `constraint` | object | ✅ | 违规判定，见 2.4 |
| `action` | object | ✅ | 告警文案与建议，见 2.5 |

### 2.3 `trigger` 结构

```json
{ "op": "any", "conditions": [ { "field": "...", "op": "...", "value": ... } ] }
```

- `op`：`any`（任一满足，默认）/ `all`（全部满足）
- `conditions[].field`：**点分路径**，取值路径以配方对象为根，例如 `intent.occasion`、`structure.center_motif.elements`、`palette.primary`
- `conditions[].op`：
  | 值 | 语义 | `value` 类型 |
  |---|---|---|
  | `intersect` | 与 value 有交集 | array |
  | `contains` | 包含子串 | string |
  | `equals` | 字符串相等 | string |

### 2.4 `constraint` 结构

`constraint.type` 只能取以下四种：

| `type` | 语义 | 需要的额外字段 |
|---|---|---|
| `forbidden_terms` | 禁止出现某些词 | `scope`(string[])、`terms`(string[])、`aliases`(object，可选) |
| `required_evidence` | 要求某字段有依据 | `field`(string) |
| `domain_check` | 取值须在允许域内 | `field`(string)、`allowed`(string[]) |
| `dependency` | 字段间依赖关系 | `if_field`、`then_field`、`rule`（描述性字符串） |

**`aliases` 规则**：别名字典显式映射同义词；匹配采用双向包含，但**单字词不参与匹配**（如「莲」），避免误报。

### 2.5 `action` 结构

```json
{
  "message": "含 {term} 与 {suggestion} 占位符的告警文案",
  "suggestions": { "被禁词": "建议替换词" }
}
```

- `message` 必须能被 `str.format(term=..., suggestion=...)` 填充
- `suggestions` 缺键时兜底为「传统吉祥纹样」

### 2.6 规则覆盖要求（B 线目标：25 条）

五类各不少于 4 条：

| 类别 | 说明 | 典型 `constraint.type` |
|---|---|---|
| 场合—意象冲突 | 喜庆场合禁用哀悼意象 | `forbidden_terms` |
| 谐音可推导 | 寓意须能由谐音/典推导 | `required_evidence` |
| 纹样等级 | 等级制度约束使用场景 | `forbidden_terms` / `domain_check` |
| 载体—密度 | 载体决定构图密度 | `dependency` |
| 色彩规程 | 色彩须落在传统色域 | `domain_check` |

**每条 `source` 必须非空。** 规则条数与文献依据，直接对应报告的创新性评分。

---

## 3. `Recipe`（纹样文化配方）— 规则取值所依赖的对象

> **为什么这一节必须冻结**：第 2 节里每条规则的 `trigger.conditions[].field` 都是**点分路径**（如 `intent.occasion`、`structure.center_motif.elements`），这些路径指向的就是配方对象。配方里的字段名一旦改动，B 已经写好的规则会**静默失效**——不报错、不崩溃，只是永远不触发。所以配方结构和那两份 JSON 一样，属于硬接口。

### 3.1 配方对象示例

```json
{
  "recipe_id": "R20260918001",
  "user_request": "做一个有吉祥寓意的窗花，用于春节礼品包装",
  "intent": {
    "occasion": ["春节"],
    "purpose": "礼品包装",
    "blessing": ["连年有余", "吉祥"],
    "style": "传统窗花"
  },
  "structure": {
    "center_motif": { "name": "莲年有鱼", "elements": ["莲花", "鲤鱼"], "confidence": 1.0 },
    "border": { "pattern": "回纹", "width_ratio": 0.15 },
    "corner": { "pattern": "如意角花" },
    "symmetry": "四轴对称"
  },
  "palette": {
    "primary": "#C8102E",
    "secondary": "#F2A900",
    "scheme_basis": "传统点染配色"
  },
  "provenance": [],
  "violations": [],
  "schema_version": "1.0"
}
```

### 3.2 字段定义

| 路径 | 类型 | 必填 | 说明 | 谁读它 |
|---|---|---|---|---|
| `recipe_id` | string | ✅ | 形如 `R20260918001`，一次运行一个 | M4/M6 输出目录、M7 报告 |
| `user_request` | string | ✅ | 用户原话，**原样保存**，不做改写 | 报告展示、问题复现 |
| `intent.occasion` | string[] | ✅ | 场合，取值须来自 §1.3 场合词表 | **M3 规则** |
| `intent.purpose` | string | ✅ | 用途（如「礼品包装」） | M3 规则、M5 prompt |
| `intent.blessing` | string[] | ✅ | 寓意词，**须可由中心母题的谐音/象征关系推导** | **M3 规则** |
| `intent.style` | string | ⬜ | 风格（如「传统窗花」） | M5 prompt |
| `structure.center_motif.name` | string | ✅ | 中心母题名，**必须来自样本库 `name` 白名单** | M2 检索、M4 合成 |
| `structure.center_motif.elements` | string[] | ✅ | 中心母题的构成元素 | **M3 规则**、M2 二次筛选 |
| `structure.center_motif.confidence` | float | ⬜ | M1 解析置信度，缺省 `1.0` | 低置信提示 |
| `structure.border.pattern` | string | ⬜ | 边饰纹样名 | M2 检索、M4 合成 |
| `structure.border.width_ratio` | float | ⬜ | 边饰占边长比例；缺省取 `config.compose.border_ratio` | M4 合成 |
| `structure.corner.pattern` | string | ⬜ | 角花纹样名 | M2 检索、M4 合成 |
| `structure.symmetry` | string | ⬜ | 对称方式（「四轴对称」/「二轴对称」） | M4 合成 |
| `palette.primary` | string | ✅ | 主色，`#RRGGBB` | **M3 规则**、M4 合成 |
| `palette.secondary` | string | ⬜ | 辅色，`#RRGGBB` | M4 合成 |
| `palette.scheme_basis` | string | ⬜ | 配色依据说明 | 溯源卡片、报告 |
| `provenance` | object[] | ⬜ | **由 M2/M6 回填**，元素结构见 3.3；M1 阶段为空数组 | M6 溯源卡片 |
| `violations` | object[] | ⬜ | **由 M3 回填**，元素结构见 3.4；M1 阶段为空数组 | 界面告警、报告 |
| `schema_version` | string | ✅ | 固定 `"1.0"` | 版本兼容判断 |

### 3.3 `provenance[]` 元素结构（M2/M6 写入）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `role` | string | ✅ | `center_motif` / `border` / `corner` |
| `element` | string | ✅ | 被溯源的要素名 |
| `source_id` | string | ✅ | 对应 `samples.json` 中的 `id` |
| `source_name` | string | ✅ | 对应样本的 `name` |
| `carrier` | string | ✅ | 载体 |
| `dynasty` | string | ✅ | 朝代 |
| `meaning` | string | ✅ | 寓意 |
| `source` | string | ✅ | 来源机构 |
| `source_url` | string | ✅ | 出处链接，**不截断** |
| `license` | string | ✅ | 授权类型，**不得为空**（红线相关） |
| `similarity` | float | ⬜ | 检索相似度，保留 2 位小数 |

### 3.4 `violations[]` 元素结构（M3 写入）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `rule_id` | string | ✅ | 命中规则 ID，对应 `culture_rules.json` 的 `id` |
| `name` | string | ✅ | 规则名 |
| `severity` | string | ✅ | `high` / `medium` / `low` |
| `source` | string | ✅ | 规则依据，从规则表带出——**保证每条告警都可审计** |
| `term` | string | ⬜ | 命中的具体词（`forbidden_terms` 类规则才有） |
| `message` | string | ✅ | 已填充占位符的告警文案 |

---

## 4. 变更流程（重要）

1. **冻结后如必须改**：两人同时在场，一起改 `docs/schema.md`，同步升级两份 JSON。
2. 改完立即各自 `git pull`，跑一次 smoke test。
3. **不得单方面修改字段名或类型。** 新增**可选**字段可以，但要先在本文件登记。

---

## 5. 冻结确认

| 角色 | 代号 | 确认状态 | 日期 |
|---|---|---|---|
| A（工程） | | ⬜ | |
| B（内容） | | ⬜ | |

> 双方在群里回复"契约确认"后，本表打勾，契约正式生效。
> **⚠️ 在两边都打勾之前，契约处于「已起草、未生效」状态** —— 此时 B 有权提出修改。
