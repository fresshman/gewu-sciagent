# 实测记录：英文 LIBS 论文原页多模态理解（2026-10-23）

目的：验证「书生 intern-s2 科学多模态原页理解」在**英文正式期刊论文**（非中文、
含流程图/谱图/散点图/箱线图）上是否真的可用，以及反幻觉校验链是否守得住。

三篇均为用户提供的本地 PDF，**只按路径读取，不入库、不推送**（遵循本机优先原则）：
仓库内不存在任何论文资产，本记录只保留核验得出的 DOI 与结论。

## 一、样本与核验结果

| # | 论文 | 出处 | DOI | 核验方式 | 结果 |
|---|------|------|-----|---------|------|
| A | A temporal and spatial dual-dimension fusion spectra mapping method for rapid detection of coal quality in LIBS（TSDD-SM） | Talanta, 2025 | `10.1016/j.talanta.2025.128106` | CrossRef 标题检索（相似度 1.000） | verified |
| B | Methods for optimization of the original signal in laser induced breakdown spectroscopy（13 类信号优化方法综述） | Spectrochim. Acta Part B 218 (2024) 106982 | `10.1016/j.sab.2024.106982` | CrossRef DOI | verified (high) |
| C | Improving small-sample performance in portable LIBS analysis with transfer learning and synthetic data-driven CNN models | J. Anal. At. Spectrom. | `10.1039/d5ja00490j` | CrossRef DOI | verified (high) |

> A 篇首次核验时走了 Semantic Scholar 模糊标题匹配，无 key 限流返回 `verify_pending`。
> 该次暴露了校验链的真实缺口，已修复（见第四节）。

## 二、原页理解：逐项验证

渲染 `sci-data.render_pdf_pages(dpi=130)` → `image_to_data_uri` → 直接以
`image_url` 发 `intern-s2`（不经 InternVL 转文本），逐项与 PDF 文本层/独立视觉对照核对。

| 验证项 | 页面 | 书生读出 | 对照结果 |
|--------|------|---------|---------|
| 流程图步骤（Fig.3a） | A p5 | Step 1–8 全序列 + 右侧分组标注 `TSDD-SM process` / `Modeling process` | ✅ 与页面逐字一致 |
| 方法示意图符号（Fig.3b） | A p5 | `Position 1/k/n`、`Time 1/n`、`Spatial`/`Temporal` 轴、`Wavelength`、`HOG feature`、矩阵 `A`、`C = A·f(I)`、`Predicted vs True` | ✅ 全部命中，且该页文本层仅 486 字符（只有图注）→ **纯靠图读出来的** |
| 谱图元素标注（Fig.4a） | A p5 | C、Mg、Si、Ti、Al、C–N、Na、K 及坐标轴刻度 | ✅ 一致 |
| 散点图中 R² 标注 | A p5 / A p8 | Fig.4(b) `R²_CV=0.7020`、`R²_P` 首读 0.8551 | ⚠️ **位序错**，正确为 `0.8851` |
| 四子图指标（Fig.6） | A p8 | LIBS `0.8352/0.9320`、TSI `0.9674/0.9669`、SSI `0.961?/0.9811`、TSDD-SM `0.9987/0.9900` | ✅ 与 Table 3 一致；SSI 首读 `0.9619`，表值 `0.9616`（末位误差） |
| "图中没有"的识别 | A p8 | 问 RMSE 时答"图中仅标注 R²，RMSE 仅见于 Table 3" | ✅ **抗幻觉正面样本**：未把表格数字冒充成图内读数 |
| 图号不存在时拒答 | B p14 | 问 Fig.7，答"本页只有 Fig.8，Fig.7 不可见"，并区分正文描述 vs 图中可见 | ✅ 拒答 + 纠错，未编造 |
| 13 组方法数值表（Fig.7） | B p13 | RSD/LOD/EF 的 Before→After 逐编号读出 | ✅ 抽查 `37.2%→2.6%` 与正文表格**完全吻合**；EF `1160`/`10000` 亦在正文出现 |
| 同一回答内部一致性 | B p13 | 表格中 #12 的 After 为 `/`，结论段却写 `37.58%→8.73%` | ❌ **前后打架**，长输出风险 |
| 箱线图分布（Fig.11） | C p9 | 纵轴 R²，图例为三类数据集（Laboratory/Simulated/Small-sample simulated），并纠正提问中"CNN/TL-CNN/RF"的错误预设 | ✅ 主动纠错 + 数值区间目测合理 |

结论：**原页理解在英文正式论文上可用**，尤其擅长流程图/示意图这类"文本层几乎为空、
信息全在图里"的页面；但对**必须精确引用的数字**存在末位/位序误差与长输出自相矛盾
两类风险。

## 三、由此固化的操作纪律（已写入 `gewu-lit-review` SKILL）

1. 图号 ≠ 页码，且一页可能只含部分子图 → 先 `pdf_page_map`，并用**图注所在页**定位。
2. 写进综述/对比表的数字必须二次复读或与正文表格对照，冲突时**以表格为准**。
3. 要求一次性输出结构化表格，约束"无数据写 `/`，结论段不得与表格冲突"。
4. 保留"看不清就写看不清"的提示，这是抗幻觉机制而非能力不足。
5. 长综合任务显式要求"只输出最终结论"，`max_tokens ≥ 3000`（intern-s2 会先吐推理草稿）。

## 四、修复：反幻觉校验链补第 4 层

`gewu/mcp/verify_papers.py` 原为三层（arXiv → CrossRef DOI → S2 模糊标题）。
**只有标题、没有 DOI 的文献一律落到 S2，无 key 时几乎必然 429 → 全部 pending**，
反幻觉校验对这批文献形同失效（本次 A 篇即命中）。

新增 Layer 3.5 `verify_title_crossref()`：S2 未命中时改用 CrossRef `query.title`
检索，标题相似度 ≥ 0.82 才接受其 DOI，方法标记为 `crossref_title_fallback_from_s2`。

自检（真实标题 / 编造标题各一）：

```
真标题 -> ('verified', {'doi': '10.1016/j.talanta.2025.128106', 'crossref_title_ratio': '1.000'})
假标题 -> ('unverified', None)
```

即：真实论文在 S2 限流时仍能落到 verified，编造标题不会被放过。
回归脚本见 `tests/test_verify_papers_fallback.py`。

## 五、跨文献综合（gap 分析）可用，但须人工审数字

基于三篇读图所得的真实信息做跨文献 gap 分析，书生能给出结构化结论：
三篇分别位于**信号层（B）/ 数据层（C）/ 特征表示层（A）**，构成一条互补链条，
彼此不冲突；并明确指出「不同样品形态、不同验证协议、不同指标基准」之间的对比
**不可直接比较**（例如 A 篇的热值 RMSEP 建立在压片/定位扫描样品与外部测试集上）。

该能力可用于 related work 定位与可性质疑预演，但**所有引用数字必须回到第二、
三节的校验纪律**：先核对，再引用。
