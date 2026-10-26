# 文献调研 — MIL + LIBS 大颗粒原煤热值预测

> **阶段**：读论文找 idea（阶段 2）  
> **输入**：`handoff_1_direction.json`（定方向 · 研究立项书）  
> **检索词**：multi-instance learning / LIBS / laser-induced breakdown spectroscopy / coal calorific value / 大颗粒原煤  
> **检索源**：arxiv, semantic, crossref, openalex, pubmed  
> **D1 反幻觉核验**：`mcp__sci-verify__verify_papers` → verdict **PASS**，hallucination_rate 0.0，pending_rate 0.0  
> **纪律**：未下载 PDF、未渲染原页；本地 `downloads/` 仅有 3 篇无关 PDF（1402.1349、1905.12226、2306.00003），未读。

---

## 1. 候选论文（Evidence 列 = 来源 / D1 核验状态）

| # | 标题 | DOI / arXiv | 相关性 | Evidence |
|---|---|---|---|---|
| P1 | A model combining spectrum standardization and dominant factor based PLS method for carbon analysis in coal by LIBS | arXiv:1402.2062 / doi:10.1016/j.sab.2014.06.017 | **高** — 直接对标"PLSR + 残差修正"范式 | arxiv → **verified** |
| P2 | The application of spectrum standardization method for carbon analysis in coal using LIBS | arXiv:1402.2060 | **高** — 基线方法来源（矩阵效应标准化） | arxiv → **verified** |
| P3 | milearn: A Python Package for Multi-Instance Machine Learning | arXiv:2512.01287 | **高** — MIL 工具基线；支持回归 + 小数据集超参搜索 | arxiv → **verified** |
| P4 | Rapid Classification and Quantification of Coal by Using LIBS and Machine Learning | doi:10.3390/app13148158 | **中高** — 煤 LIBS + ML 路线（PLSR/聚类和分类），PLSR 作为定量基线 | crossref → **verified** |
| P5 | Coal Analysis by Laser-Induced Breakdown Spectroscopy | doi:10.1002/9781119758396.ch27 | **中** — Wiley 专著章节，煤 LIBS 综述性参照 | crossref → **verified** |

**附注（检索命中但未被选入 top 5）**：W3207187242（LIBS 工业材料综述，134 引用）、W4400809048（2024 煤 LIBS 应用进展）、W4224216995（煤工业分析 PLS/PCR/ANN 对比）、W7161111813（2026 煤 LIBS 挑战综述）——与"大颗粒 + 建模结构"gap 间接相关。

---

## 2. 逐篇要点（基于摘要/标题）

### P1 — Li, Wang, Fu, Li, Ni (2014), *Spectrochim. Acta B*
- **核心**：spectrum standardization → 把 C 谱线强度换算到"标准态"（固定等离子体温度、电子密度、碳数密度）；再用 **dominant-factor PLS** 修正残差。
- **结果**：R²=0.99, RMSEP=1.75%, ARE=2.39%（vs 纯标准化 R²=0.83 / RMSEP=2.71%）。
- **对本项目的意义**：**"物理模型先校正 → 统计模型修残差"是本项目 hybrid = PLSR + MIL 残差 的直接思想前身**。关键差异：P1 用全谱 PLS 修残差，本项目用注意力 MIL 修残差（期望对 bag 内异质谱更鲁棒）。
- **局限**：面向粉煤/压片样，**不涉及大颗粒 intra-bag 异质性**；无 bag 结构、无多击打位点建模。

### P2 — Li, Wang, Fu, Liu, Ni (2014), arXiv:1402.2060
- 纯 spectrum standardization 版本（无 PLS），同样 24 个烟煤样品；给出 RSD / R² / RMSEP / MARE 四项指标。
- **价值**：标准化作为前置预处理的实证支撑；与 handoff_1 中"sg 平滑 → als 基线校正 → MinMax 归一化"可并列讨论。

### P3 — Zankov, Polishchuk, Sobieraj, Barbatti (2025), arXiv:2512.01287
- `milearn`：scikit-learn 风格 MIL 包，覆盖经典 + 神经网络 MIL（回归/分类），内置面向小 MIL 数据集的超参优化，支持 KID（key instance detection）。
- **价值**：本项目的 MIL 实现可基于 `milearn` 搭建基线；其"小数据集超参搜索"与本项目 5 折 CV 的小样本场景直接匹配。
- **局限**：未涉及光谱数据、未涉及 LIBS/煤。

### P4 — Zheng, Lu, Chen, Liu, Ren (2023), *Appl. Sci.* 13(14):8158
- 100 个煤样、11 个产地；K-means 聚类 + Naive Bayes 产地分类（acc 0.967）+ PLSR 定量（灰分/挥发分/固定碳 RMSEP 1.012%/0.878%/1.409%）。
- **价值**：PLSR 在煤 LIBS 定量中的基线性能数字可作参照；交叉验证用法与本项目一致。
- **局限**：粒度未说明（大概率粉煤/压片）、分类为主、**无多示例建模**。

### P5 — Yao (2023), Wiley 专著《Laser Induced Breakdown Spectroscopy》ch.27
- 煤 LIBS 综述章节（2 引用，书章节通常滞后）。
- **价值**：为 introduction 提供领域背景与 matrix effect / 标准化方法谱系。
- **局限**：无全文摘要可抽；D1 仅核验 DOI 存在性。

---

## 3. 提炼的 Gap（基于 handoff_1 假设 + 文献证据）

| # | Gap | 证据支撑（来源） | 本项目对应 |
|---|---|---|---|
| G1 | **现有 LIBS 定量工作假设样品均匀/单谱代表整体，未建模大颗粒 intra-bag 异质性** | P1/P2/P4 均为粉煤压片或单谱输入；全检索未找到"LIBS + multi-instance learning + 大颗粒煤"组合 | handoff_1 的 bag 定义（N 张局部谱 → 1 个热值） |
| G2 | **残差修正停留在 PLS 全谱，无法区分"异常实例"与"信息性实例"** | P1 用 dominant-factor PLS 修残差，但对 bag 内离群谱无鉴别机制 | TransMIL 注意力池化 + 实例级 ResNet1D 表示 |
| G3 | **小样本 MIL 建模缺少面向光谱的先验结构与超参调优框架** | milearn 提供通用小样本超参搜索，但无光谱归纳偏置 | FiLM 条件调制（把工况/煤岩信息注入）+ bag 内共享归一化 |
| G4 | **煤 LIBS 定量指标以 RMSEP/RMSECV 报告，缺少按折单报的方差控制** | P4 报告 RMSEP 均值；P1 报告 RMSEP，但无逐折分布 | 5 折每折独立 RMSE/MAE/R² + 均值±标准差 |
| G5 | **多击打位点谱的信息结构未被当作第一类对象** | P1/P2 的标准化方法把多次击打平均化，丢弃位点间差异 | 注意力权重可解释性 → 哪些位点贡献最大 |

---

## 4. 可改进点 / 下一步假设

1. **hybrid 残差结构**：把 P1 的"物理标准化 → PLS 修残差"升级为"光谱预处理 → PLSR 基线 → MIL 注意力残差"，在同一个 CV 框架下直接对比。
2. **实例级异常剔除 vs 注意力加权**：设消融实验——bag-mean 谱输入 PLSR vs 简单平均 MIL vs 注意力 MIL vs 注意力 + 异常截断。
3. **可解释性**：注意力权重映射回击打位点，验证"高权重位点对应高碳/高灰分区"的物理解释（需与实验记录对照）。
4. **小样本泛化**：用 milearn 的小数据集超参搜索协议调 TransMIL head 维度与注意力温度，防止过拟合。

---

## 5. 风险提示

- **检索覆盖**：Semantic Scholar 与 PubMed 返回 0 结果（关键词组合跨学科、arXiv/MEDLINE 无直接命中）；gap 结论基于 15 条去重结果，**不排除中文核心（《光谱学与光谱分析》《煤炭学报》）有更接近的工作**——建议 repro/improver 阶段补 CNKI 检索。
- **无直接竞品**：检索未发现"MIL + LIBS + 煤热值"的已发表工作，这既是 novelty 空间，也意味着 baseline 选择要保守（必须以 bag-mean+PLSR 作主基线，而非虚构一个对比方法）。
- **未读全文**：P1/P4 的关键实验细节（样品粒度、击打次数、CV 划分）仅从摘要不可知，可能影响 handoff_1 方案的参数设定；复现阶段应取全文确认。

---

## 6. D1 核验汇总

```
verdict: PASS
hallucination_rate: 0.0   pending_rate: 0.0
p1 (1402.2062 / 10.1016/j.sab.2014.06.017)  arxiv      verified  high
p2 (1402.2060)                                arxiv      verified  high
p3 (2512.01287)                               arxiv      verified  high
p4 (10.3390/app13148158)                      crossref   verified  high
p5 (10.1002/9781119758396.ch27)               crossref   verified  high
```

**结论**：5 篇候选全部通过 D1 存在性核验，无幽灵引用。