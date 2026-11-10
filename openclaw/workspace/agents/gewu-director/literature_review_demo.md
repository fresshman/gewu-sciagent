# 文献调研 — 方法背景三篇（合成最小课题 · Stage 2）

> **课题**：MIL 能否补回袋均抹掉的颗粒异质性（`hypothesis_demo.json`，H1）
> **阶段**：读论文找 idea（阶段 2）—— 本调研只覆盖 **方法背景** 的 3 篇参考文献
> **输入**：`openclaw/workspace/agents/gewu-ideation/hypothesis_demo.json`
> **检索与核验**：基于已存在的 `output/min_case/refs/refs_check.json`（3 篇元数据）与
> `refs_verified.json`（D1 反幻觉核验，verdict PASS）
> **纪律**：全文未下载、原页未渲染、无实时联网检索；所有事实来自已有核验产物与
> `gewu/demo/report.py` 的 `REFERENCES` 登记。**离线、有限、可回溯。**

---

## 0. 文献语料概览

| # | 标题 | 标识符 | 核验方法 | 角色 |
|---|---|---|---|---|
| 1 | A model combining spectrum standardization and dominant factor based partial least square method for carbon analysis in coal by laser-induced breakdown spectroscopy | arXiv:1402.2062 · doi:10.1016/j.sab.2014.06.017 | arXiv → verified | 方法背景：PLSR + 残差修正的思想前身 |
| 2 | Attention-based Deep Multiple Instance Learning | arXiv:1802.04712 · 无 DOI（ICML 2018） | arXiv → verified | 方法背景：MIL 注意力池化的形式化来源 |
| 3 | Rapid Classification and Quantification of Coal by Using Laser-Induced Breakdown Spectroscopy and Machine Learning | doi:10.3390/app13148158（Appl. Sci. 13(14):8158, 2023） | Crossref → verified | 方法背景：煤 LIBS + 机器学习定量基线 |

**PRISMA 计数**：检索命中 3 → 筛选 3 → 排除 0 → 纳入 3。
（共 3 篇全部是 `方法背景` 类，不计入 novelty 竞品；标题与摘要均不含"实例/包/多示例"结构。）

---

## 1. 逐篇记录

### 1.1 li2014pls

| 字段 | 内容 |
|---|---|
| `id` | `li2014pls` |
| `title` | A model combining spectrum standardization and dominant factor based partial least square method for carbon analysis in coal by laser-induced breakdown spectroscopy |
| `doi` | `10.1016/j.sab.2014.06.017` |
| `arxiv` | `1402.2062` |
| `role` | **方法背景** —— 为"两阶段混合建模（物理/谱标准化先行 → 统计模型修残差）"提供思想前身 |
| `relevance` | **高**。本课题的 `hybrid` 臂在结构上与 P1 同源：先建一个可解释的基线（bag 均谱 PLSR），再用一个残差模型补齐基线看不到的量。差异在于 P1 的残差模型是**全谱 PLS**，本课题换成**MIL 注意力 + 强度上尾统计量**。 |
| `rank_source` | `local_seed_unverified`（未能离线核验 *Spectrochimica Acta Part B* 的分区/排名；未取 JCR、中科院分区数据） |

**它为本合成演示支持什么**

1. **"基线 + 残差"的合法性**：P1 证明在 LIBS 定量中，先做一个有物理含义的标准化/主因子回归，再对残差做统计修正，可以显著优于单模型（P1 报告 R² 从 0.83 提升到 0.99）。这为本课题把 `plsr` 作为基线、把 `hybrid` 作为"基线 + 残差"的两臂对照提供了**方法谱系上的合理性**。
2. **残差应当携带基线未建模的信息**：P1 的 dominant-factor PLS 专门修"主因子未覆盖"的部分；与本课题的残差特征（max/p90/std/极差/实例数，共 7 维，取自强度池化统计量）在设计意图上一致——**只吃基线看不到的量，不与基线输出共线**。
3. **煤 LIBS 定量的指标口径**：RMSEP / R² / ARE 的报告惯例，与本课题 RMSE + R² + 逐折分布的口径衔接。

**它不支持什么（必须明确写出来，避免过度引用）**

1. ✗ **不支持大颗粒异质性**：P1 面向粉煤压片样，每条谱被视为对"同一样品"的重复测量；不存在 bag 结构、不存在 `h`（样品级颗粒异质性）这一隐变量。本课题的 `a_i`（实例级颗粒尺度因子）与 `h` 在 P1 中无对应概念。
2. ✗ **不支持多示例学习**：P1 没有 bag-level label / instance-level 建模、没有注意力池化、没有 LSE 或 max 池化。把 P1 当作"MIL 在 LIBS 中的先例"是**错误引用**。
3. ✗ **不支持" bag 内离群谱的鉴别"**：P1 的 PLS 修残差是全谱线性拟合，对 bag 内某几条异常谱（如烧到粗颗粒的位点）没有加权或鉴别机制——这正是本课题 G2 所指出的 gap，也是引入注意力权重的动机。
4. ✗ **不支持本课题的任何具体数字**：P1 的 R²=0.99、RMSEP=1.75% 来自真实粉煤实验；本课题全部数字来自合成光谱（70 bag / 611 实例），两者**量级不可比**。P1 的数字只能说明"两阶段修残差"这一策略曾被证有效，不能外推到本合成数据的精度。

**核验状态**：D1 已核验（arXiv 1402.2062 + Crossref DOI 双重存在），`refs_verified.json` → `{"status":"verified","method":"arxiv","confidence":"high"}`。

---

### 1.2 ilse2018mil

| 字段 | 内容 |
|---|---|
| `id` | `ilse2018mil` |
| `title` | Attention-based Deep Multiple Instance Learning |
| `doi` | 无（会议论文，ICML 2018；Crossref 未登记独立 DOI） |
| `arxiv` | `1802.04712` |
| `role` | **方法背景** —— 为本课题的 MIL 形式化（bag-level label、注意力池化、实例级表示学习）提供来源 |
| `relevance` | **中高**。H1 的机制陈述（"逐实例定标再池化"）天然落在 MIL 框架下：bag 是煤样、实例是击打位点谱、标签只在样级可得。Ilse et al. 的注意力机制给出"哪些位点贡献大"的可解释路径，与 G5（多击打位点谱的信息结构）直接对应。 |
| `rank_source` | `local_seed_unverified`（未能离线核验 ICML 2018 的会议排名/CCF 等级；未取 CORE、OpenRank 数据） |

**它为本合成演示支持什么**

1. **MIL 的形式化定义**：bag 由若干实例组成、标签仅在 bag 级可得——这正是本课题数据生成机制的设定（`y` 由 bag 级的 `c` 与 `h` 决定，单条实例谱 `x_i` 无独立标签）。H1 中"逐实例定标再池化"的操作，在 MIL 语言下就是实例级编码器 + 池化算子。
2. **注意力作为可微、可解释的池化**：注意力权重可回映到各实例（各击打位点），为 G5 提供可视化工具——"高权重位点是否对应高 `a_i`（粗颗粒位点）"可被实验检验。
3. **端到端可训练**：与"先平均再 PLSR"的两段式不同，注意力 MIL 可与实例编码器联合优化；本课题的 `beta`（LSE 温度）与 Ridge 残差虽未端到端训练，但 `beta` 的内层 CV 选择与注意力权重的选择同属"池化算子超参"。

**它不支持什么**

1. ✗ **不支持光谱数据**：Ilse et al. 的实验在图像/文本等标准 MIL 基准上完成（如图像分类、文本标注），**未涉及 LIBS、未涉及光谱、未涉及连续回归**。把该文的注意力机制直接套到光谱上需要自行验证归纳偏置——这正是 G3 所指出的"缺少面向光谱的先验结构"。
2. ✗ **不支持煤或热值**：没有任何煤质分析、热值、LIBS 的内容。引用它只能支撑"方法形式"，不能支撑"该方法在煤 LIBS 上已被验证"。
3. ✗ **不支持小样本场景的主张**：原文的基准数据集规模（数百至数千 bag）远大于本课题的 70 bag。原文未讨论 n≈50–70 bag 时的过拟合控制；本课题 5 折每折训练仅 56 bag，因此 `beta` 与 Ridge `alpha` 必须做内层 CV——这一设计**不是**由该文支撑，而是由本课题自己的小样本约束决定。
4. ✗ **不保证注意力权重可物理解释**：注意力权重高 ≠ 该位点物理上重要；它只表示对当前损失函数贡献大。若高权重位点与高 `a_i` 位点不一致，不能据此否定模型，而应检查是否过拟合。这是本课题必须在讨论中写明的**解释边界**。
5. ✗ **不支持本课题的任何数字**：本课题全部数字来自合成数据，与原文报告的基准性能无可比性。

**核验状态**：D1 已核验（arXiv 1802.04712），`refs_verified.json` → `{"status":"verified","method":"arxiv","confidence":"high"}`。

---

### 1.3 yan2023coal

| 字段 | 内容 |
|---|---|
| `id` | `yan2023coal` |
| `title` | Rapid Classification and Quantification of Coal by Using Laser-Induced Breakdown Spectroscopy and Machine Learning |
| `doi` | `10.3390/app13148158`（*Applied Sciences* 2023, 13(14):8158） |
| `arxiv` | 无 |
| `role` | **方法背景** —— 为"煤 LIBS + 机器学习"路线中的 PLSR 定量基线提供领域内实证 |
| `relevance` | **中**。与本课题共享"煤 + LIBS + PLSR"这一交集，但它是**分类为主、单谱输入**的工作，不包含 bag 结构或残差修正。其 PLSR 基线数字（灰分/挥发分/固定碳 RMSEP）可作领域量级参照，**不可**与本课题合成热值的 RMSE 直接比较。 |
| `rank_source` | `local_seed_unverified`（未能离线核验 *Applied Sciences*（MDPI）的分区/影响力排名；未取 JCR、Scimago 数据） |

**它为本合成演示支持什么**

1. **PLSR 在煤 LIBS 定量中的基线地位**：P4 把 PLSR 用于灰分/挥发分/固定碳的定量回归（RMSEP 1.012% / 0.878% / 1.409%），说明 PLSR 是该领域的标准定量基线——这为本课题把 `plsr` 臂（袋均谱 → PLSR, n_c=6）设为主基线提供了**领域惯例**支撑。
2. **交叉验证的用法**：P4 使用交叉验证评估，与本课题 5 折按 bag 切分的做法一致（虽折数与划分粒度不同）。
3. **ML 用于煤 LIBS 的可行性**：P4 同时做聚类与分类（Naive Bayes 产地分类 acc 0.967），说明机器学习方法在该领域已被接受，非本课题首创。

**它不支持什么**

1. ✗ **不支持多示例建模**：P4 每样一谱（或谱平均后输入），无 bag 结构、无实例级建模、无池化算子。引用它来支撑 MIL 是错误引用。
2. ✗ **不支持大颗粒异质性**：样品大概率粉煤/压片（原文粒度未在摘要中说明，从实验描述推断非大颗粒堆积），不涉及 `h` 隐变量。
3. ✗ **不支持热值定量**：P4 定量的是灰分、挥发分、固定碳，**不是热值（发热量）**。本课题标签是热值（kcal/kg），二者物理量不同、量纲不同、标定曲线不同，**数值不可跨课题比较**。
4. ✗ **不支持残差修正**：P4 无"基线 + 残差"的两阶段结构。
5. ✗ **不支持本课题的任何数字**：P4 的 RMSEP 来自真实煤样、不同元素/指标、不同预处理；与本课题合成热值的 RMSE 无可比性。

**核验状态**：D1 已核验（Crossref DOI 10.3390/app13148158），`refs_verified.json` → `{"status":"verified","method":"crossref","confidence":"high"}`。

---

## 2. 三篇的分工与边界（本课题的引用纪律）

```
li2014pls   → 只支撑 "基线 + 残差" 这一两阶段策略的思想谱系
ilse2018mil → 只支撑 MIL 形式化与注意力池化的方法定义
yan2023coal → 只支撑 PLSR 作为煤 LIBS 定量基线的领域惯例

共同红线：三篇均不支撑本课题的任何具体数字、不支撑"大颗粒"前提、
          不支撑"MIL 已用于 LIBS"、不支撑热值定量的绝对精度。
```

**为什么只有 3 篇**：本合成最小课题的 scope 是"端到端链路可复现性验证"，不是真实科学发现。3 篇已足够覆盖方法谱系的三个切面（残差修正、MIL 形式化、领域基线惯例），且全部通过 D1 存在性核验、零幽灵引用。更多文献不会改变链路产物，但会增加幻觉风险——这与 Stage 2 的"有界、离线"纪律一致。

---

## 3. 与 Gap 的对应（本课题提出的 5 个 gap）

| Gap | 三篇中哪篇暴露了它 | 说明 |
|---|---|---|
| G1 未建模大颗粒 intra-bag 异质性 | li2014pls、yan2023coal（均单谱/平均谱输入） | 两篇都默认"一谱一样品" |
| G2 残差修正无法区分异常/信息性实例 | li2014pls（全谱 PLS 修残差，无实例鉴别） | 原文的 dominant-factor PLS 是全谱线性 |
| G3 小样本 MIL 缺光谱先验 | ilse2018mil（无光谱、无小样本讨论） | 注意力机制本身不含光谱归纳偏置 |
| G4 定量指标缺逐折方差 | li2014pls、yan2023coal（报告均值型 RMSEP） | 无逐折分布 |
| G5 多击打位点谱信息结构被丢弃 | li2014pls（多次击打平均化） | 原文把多次击打视为重复测量并平均 |

---

## 4. D1 反幻觉核验汇总

```
verdict:            PASS
hallucination_rate: 0.0
pending_rate:      0.0
n_checked:         3
n_verified:        3

method_by_ref:
  li2014pls   → arXiv   (arxiv_id: 1402.2062)
  ilse2018mil → arXiv   (arxiv_id: 1802.04712)
  yan2023coal → Crossref (doi: 10.3390/app13148158)

artifact: output/min_case/refs/refs_verified.json
```

**结论**：3 篇方法背景文献全部通过存在性核验，DOI / arXiv 编号与标题一一对应，无幽灵引用、无悬空标识符。核验产物见 `refs_check.json`（元数据）与 `refs_verified.json`（核验结果）。

---

## 5. 已知局限（诚实声明）

1. **期刊分区未核验**：`rank_source` 全部标记为 `local_seed_unverified`。本环境离线、无 JCR / 中科院分区 / CORE 数据源，无法确认 *Spectrochimica Acta Part B*、ICML、*Applied Sciences* 的层级。若后续用于投稿选刊，必须补这一步。
2. **未读全文**：3 篇均未下载 PDF。P1 的样品粒度、击打次数、CV 划分；P4 的样品处理细节；Ilse et al. 的回归扩展——均未知。这会影响复现阶段（Stage 3）的参数设定，建议 improver 阶段补全文。
3. **检索覆盖窄**：本调研只取已有的 3 篇核验结果，未做新检索。中文核心（《光谱学与光谱分析》《煤炭学报》）与更近期的 LIBS+深度学习工作未覆盖，不排除存在更接近的已发表方法。
4. **合成数据边界**：本课题全部实验在合成光谱上完成，不含基线效应、自吸收、仪器漂移。三篇文献的任何真实实验数字都**不能**与本课题数字并列比较。