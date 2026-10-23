# 科研插图（混合策略：数据图本地 / 结构图云端）

本技能规定格物**何时、如何生成论文与报告插图**。核心原则：
**含实验测量数据的图 → 本地 `sci-plot`（matplotlib，数据不出本机）；纯结构/概念图
（无实验数据）→ 云端 `chart-cloud`（包装 @antv/mcp-server-chart）。**

## 为什么是混合策略

- **含数据的统计图**若走云端，需要把数据 POST 到公有云渲染、返回远程图片 URL 再下载，
  对格物这类「本地优先、可能含未发表实验数据」的科研智能体是**数据出域**硬伤，且产物是
  栅格图而非出版级矢量图。因此一律本地 `sci-plot`，同时产出 PDF（矢量，投稿用）+ PNG（300dpi）。
- **思维导图 / 桑基 / 鱼骨 / 组织架构 / 地图**等结构图不含测量值，无出域风险，且 matplotlib
  天生不擅长，故用 `chart-cloud` 云端出图更省力。`chart-cloud` 已通过 `DISABLED_TOOLS` 关掉
  全部 15 个含数据的图类型，**从配置层面强制**实验数据无法经它离开本机。

## 铁律（最高优先级，违反即判定失败）

1. **禁止凭空编造数据画图。** 图中每一个数字必须来自 `sci-compute` / `mil-model` 的真实
   计算结果，或已加载的真实数据文件。指标还没算出来 → 先算再画；算不出来就在正文如实说明，
   **绝不允许"画一个看起来合理的图"**。
2. **标注数值必须与工具返回值完全一致。** `plot_pred_true` 标注的 R²/RMSE/MAE 由工具
   根据实际数据计算，不得手工改写、四舍五入美化或替换成"预期值"。
3. **图注须可追溯。** 每张图要注明数据出处（如"5 折交叉验证均值±标准差"、"测试集 n=..."），
   让审稿人能对照实验还原。
4. **含测量值的图绝不经 `chart-cloud` 出。** 若发现需要画折线/散点/柱状/饼/雷达等统计图，
   一律用 `sci-plot`；`chart-cloud` 只承接思维导图/桑基/鱼骨/组织架构/地图等结构图。

> 铁律 1–3 对应 7-mode 失败清单中的「幻觉实验结果」——插图是最容易无痕造假的地方。

## 选图对照表

### 数据图 → 本地 `sci-plot`（数据不出本机，PDF 矢量 + PNG）

| 场景 | 工具 | 备注 |
|---|---|---|
| LIBS / 光谱、一维信号 | `plot_spectrum` | 波长-强度曲线 |
| 趋势 / 时序 / 随参数变化 | `plot_line` | 可开 `markers` |
| 累积 / 占比趋势 | `plot_area` | |
| 两变量相关性 | `plot_scatter` | 开 `fit=True` 自动给拟合线与 R² |
| 回归模型性能（论文核心图） | `plot_pred_true` | 自动画 1:1 线并标注 R²/RMSE/MAE/n |
| 检验异方差 / 系统偏差 | `plot_residuals` | 残差随预测值分布 |
| 消融实验、多模型对比 | `plot_bar` | 传 `yerr` 画误差棒；`orientation="horizontal"` 为条形 |
| 交叉验证各折分布 | `plot_boxplot` / `plot_violin` | 小提琴图额外呈现密度形态 |
| 单变量分布 | `plot_histogram` | |
| 相关系数 / 混淆矩阵 | `plot_heatmap` | 小矩阵自动标注数值 |
| 训练 / 验证曲线、学习曲线 | `plot_curves` | 传字典，键为曲线名 |
| 构成 / 占比 | `plot_pie` | 数值须非负 |
| 多维指标对比 | `plot_radar` | 至少 3 个维度 |
| 两个量纲不同的序列 | `plot_dual_axes` | 双 Y 轴 |
| 误差 / 贡献分解 | `plot_waterfall` | 从基准逐步增减到终值 |

### 结构 / 概念图 → 云端 `chart-cloud`（无实验数据，可上云）

| 场景 | 工具 | 备注 |
|---|---|---|
| 概念层级 / 思路梳理 | `generate_mind_map` | |
| 因果关系 / 归因 | `generate_fishbone_diagram` | |
| 流程 / 方法步骤 | `generate_flow_diagram` | |
| 流量 / 关系流转 | `generate_sankey_chart` | |
| 关系网络 | `generate_network_graph` | |
| 组织 / 层级结构 | `generate_organization_chart` | |
| 漏斗 / 阶段转化 | `generate_funnel_chart` | |
| 层次占比 | `generate_treemap_chart` | |
| 词频 / 关键词 | `generate_word_cloud_chart` | |
| 中国行政区 / 点位 / 路径 | `generate_district_map` / `generate_pin_map` / `generate_path_map` | 仅中国 |

> `chart-cloud` 暴露的恰是这 12 种；line/area/scatter/bar/pie/radar/… 等 15 种含数据图已被禁用。

## 调用约定（sci-plot）

- 每次调用返回 `pdf`（矢量，投稿用）与 `png`（300 dpi，嵌入 docx 用）两条**绝对路径**。
- 正式文稿 / 投稿引用插图用 **PDF**；docx 草稿嵌入用 PNG。两者都留，别只留一个。
- **中文字体已内置**（Microsoft YaHei / SimHei），标题与轴标签可直接写中文，无需转义处理。
- 用 `list_figures` 查看已生成图片清单。
- 输出目录 `output/figures/`，已被 `.gitignore` 忽略（属运行产物，不进版本库）。

## 常见错误

- 把"印象里大概是多少"的数字传给绘图工具 → 违反铁律 1，直接判失败。
- 只生成 PNG 不留 PDF → 投稿阶段需重做，务必两者都产出。
- `plot_bar` / `plot_boxplot` 的 `labels` 与数据长度不一致 → 工具会返回可读报错，按提示修正即可。
- 需要思维导图 / 桑基 / 鱼骨 / 组织架构 / 地图却用 `sci-plot` 硬画 → 这些不在 `sci-plot`
  能力范围内，改用 `chart-cloud` 云端出图（它们本就不含实验数据，无出域风险）。
- 把论文实验数据塞进 `chart-cloud` 的图（如用桑基图展示真实测量流量）→ 违反铁律 4，存在出域风险。
