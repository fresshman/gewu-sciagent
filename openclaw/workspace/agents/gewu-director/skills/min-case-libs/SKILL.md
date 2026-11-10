---
name: min-case-libs
description: 合成 LIBS 多示例回归最小课题的可复现做法与踩坑记录（由格物七阶段链路自动生成，含子智能体故障恢复）
version: 1.0.0
domain: demo_synth
---

# 最小课题：合成 LIBS + MIL 热值回归

## 何时用
- 需要向第三方证明「七阶段链路能从零跑通」而手上只有私有数据时；
- 需要快速验证某个 MIL 想法（定标方式 / 池化 / 残差）是否值得上真实数据前，先用它做冒烟。

## 怎么跑
```bash
python scripts/run_min_case.py            # 全链路，产出 output/min_case/
python scripts/run_min_case.py --offline  # 不联网（跳过 D1 核验，状态会诚实降级）
python scripts/run_min_case.py --json     # 只输出汇总 JSON（供 sci-exp rerun 使用）
```

## 关键结论（本机实测）
- 袋均谱 PLSR 基线 RMSE = 150.4354 kcal/kg，
  本方法 = 73.0270 kcal/kg
  （51.4562%），配对检验 p = 2.3e-05。
- 内层 CV 选出的 β = [0.0, 0.25, 0.25, 0.25, 0.25]，Ridge α = [1.0, 1.0, 0.3162, 1.0, 1.0]。

## 踩坑记录
1. **逐谱归一化会杀掉尺度信息**：若在特征阶段就除以每谱均值，颗粒异质性同时被除掉，
   MIL 臂会退化成普通回归。要保留尺度，必须先分箱再按实例定标，且把定标放在"生成模型特征"里显式记录。
2. **按 bag 切折，不能按实例切**：同一 bag 的实例跨折会让指标虚高，这是 MIL 里最常见的泄漏。
3. **口径陷阱**：`per-fold 均值` 与 `pooled OOF` 是两个数，混用会让论文与 UI 打架。
   本项目统一以 per-fold 均值为准，pooled 仅作补充并显式标注。
4. **β=0 不是失败**：内层 CV 选到 0 说明该数据上均值池化够用，应如实写；
   强行取 β>0 属于为了叙事而改模型。本例 fold 0 选 β=0，其余四折选 0.25，
   因此增益主要来自逐实例定标（18.38%）与残差建模（33.08%），**不得宣称 LSE 高阶池化有贡献**。
5. **编排故障：子智能体可能无 handoff 落盘就退出**——阶段④（improver）子会话最终结果仅为
   "Now let me write the analysis script and independently verify every number."，
   未写 demo_handoff_4_improver.json。按「失败降级落盘铁律」，director 用 output/min_case 的已核验数据
   确定性恢复该 handoff，并把本条写入经验。恢复后各指标与 pipeline 的 stage4 产出逐位一致。
6. **本机无 TeX 引擎**：阶段⑤ 的 LaTeX 成稿无法编译（pdf_compiled: false），
   需在有 TeX Live / tectonic 的环境执行 xelatex demo_main.tex。
7. **期刊等级不可核验**：EASYSCHOLAR_SECRET_KEY 未设置，5 个候选刊 rank_source 一律标记
   local_seed_unverified，不得对外声称已核验分区。