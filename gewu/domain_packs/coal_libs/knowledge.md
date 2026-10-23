# 领域知识包：大颗粒原煤 LIBS 光谱热值预测

> 供 RAG / 长周期记忆使用，使通用智能体获得该领域背景。换领域替换本文件即可。
> 本文件描述**已真实落地并跑通**的参考实现（模型权重与未发表数据在外部项目，按路径引用）。

## 1. LIBS（激光诱导击穿光谱）原理
- 高能脉冲激光聚焦样品表面产生等离子体，冷却过程中发射元素特征谱线。
- 谱线强度与元素含量相关，可用于煤中 C/H/O 及灰分、挥发分等指标的间接估算。

## 2. 大颗粒原煤的特殊性
- 颗粒大、成分空间不均，单点光谱代表性差 → 适合用**多示例学习(MIL)**把一次采样视为一个"包(bag)"，
  包内多张谱线为"示例(instance)"，以包级热值标签做弱监督回归。
- 同一 bag 内 instance **无序**（多次激光脉冲），因此聚合需置换不变；位置编码通常关闭。

## 3. 热值（Calorific Value）
- 单位质量煤完全燃烧释放的热量，常用 MJ/kg 或 kcal/kg。
- **单位换算：1 kcal/kg = 0.004184 MJ/kg**。报告时必须显式标注单位，禁止混用。
- 是煤质评价核心指标，传统方法依赖化验，LIBS 提供快速近似。

## 4. 参考实现的方法要点（真实落地版本）

### 4.1 预处理流水线（与训练严格一致）
`sg`（Savitzky-Golay 平滑）→ `als`（非对称最小二乘基线校正）→ `mms`（最小-最大归一化）。
另有 `is_valid_spectrum` 有效性过滤，剔除异常谱线。

### 4.2 双路径融合：PLSR 基线 + MIL 残差修正
```
袋均谱 ──→ PLSR(n_components=7) ─────────────→ plsr_pred
                                                    │
实例矩阵 ─→ ResNet1D 编码 ─→ TransMIL 注意力聚合 ─┐   │
                            ↑ FiLM 用 PLSR 得分调制 │   │
                                                 mil_res│
                                                    ↓   ↓
                          hybrid(kcal/kg) = plsr_pred + mil_res
                                              ↓ ×0.004184
                                          MJ/kg
```
- **PLSR** 提供化学计量学意义上的稳定基线（可解释潜变量）。
- **MIL(ResNet1D + TransMIL_attn)** 学习 PLSR 的**残差**，修正其非线性/基体效应偏差。
- **FiLM** 用 PLSR 得分生成 γ/β 对实例特征做条件调制，让深度路径感知化学计量学信息。
- 残差在归一化空间预测，用 `res_mean/res_std` 反归一化回 kcal/kg。

### 4.3 验证与可复现性
- **5 折交叉验证**（`kfold_split_bags(seed=42)`），每折独立保存 `model.pt` + `plsr.pkl`。
- 消融维度：聚合方式（mean/max/LSE/ABMIL/TransMIL 等）、编码器、融合模式、是否预训练。
- 指标：RMSE / MAE / R²（kcal/kg 空间）。
- 格物侧 `mil_model.cv_summary()` 会**从各折 predictions.json 重算指标**并与官方
  `summary.json` 交叉校验，确认结果未被篡改且可复现。

## 5. 在格物中调用（真实推理，非 demo）

| 工具 | 用途 |
|---|---|
| `mil_model.list_val_bags(fold)` | 列出该折验证集 bag |
| `mil_model.predict_calorific_value(bag_dir, fold)` | 单 bag 真实预测（返回 PLSR / MIL 残差 / hybrid） |
| `mil_model.reproduce_fold(fold)` | 复现该折全部预测，返回 RMSE / MAE / R² |
| `mil_model.cv_summary()` | 5 折指标汇总 + 官方记录交叉校验 |

**铁律**：热值必须来自真实前向推理，禁止编造；模型与未发表数据不出本机。

## 6. 关键文献方向
- LIBS 煤质分析；多示例学习在光谱/成像中的应用；化学计量学（PLS/PCA）与深度聚合。
- 聚合方法谱系：Mean/Max → ABMIL(Ilse et al. 2018) → LSE-Pool → TransMIL(Shao et al. 2021)。
