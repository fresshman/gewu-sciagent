# 格物 · 长周期记忆

> 本文件是**共享层索引**：只放跨角色、跨课题复用的一句话结论 + 指向细节的路径。
> 细节在各角色工作区 `agents/<role>/MEMORY.md`（`gewu-distillation` 承载课题档案与失败模式）。
> **维护纪律**：结论被后续实测证伪时必须就地更正并注明，不得保留旧结论。

## 项目
- 项目：格物 (Gewu) — 通用学术科学智能体（AI4S，科学智能体方向）
- 技术栈：书生大模型 (Intern-S2 / Intern-S1-Pro / Intern-S1 / InternVL) + OpenClaw 原生编排
  + Python MCP 工具层（7 个自研 server / 49 个业务工具）
- 参考实现领域：大颗粒原煤 LIBS 光谱热值预测（MIL 方法）

## 已沉淀的方法 / 经验
（由 distillation 智能体在每轮科研后追加；下表为当前已固化的条目）

| 结论 | 细节位置 |
|---|---|
| 参考实现 5 折 RMSE `214.57 ± 25.71` kcal/kg；hybrid 相对 PLSR(233.95) 改进 8.28%，**5 折方向全为负** | `agents/gewu-distillation/MEMORY.md` |
| 小样本结论必须带三件套：配对 t + 95% CI + Wilcoxon；n=5 时 Wilcoxon 最小可达 p=0.0625，**永远不显著**，不可单独引用为显著 | 同上 |
| 组件级消融为**阴性**：FiLM/SupCon/huber 均未检出（p≥0.29、CI 全跨 0、fold4 单折主导 14–19×），既不可宣称有效也不可宣称无效 | 同上 |
| 消融的配置口径必须声明：347.55 那组（MSE/无 SupCon/无 FiLM）与 214.57（huber+SupCon+FiLM）**不可相减** | 同上 |
| 工具层/推理层分离：`default` venv 故意不含 torch，`mil_model` 用 subprocess 拉起 torch 解释器（「需建合并 venv」旧结论已废止） | 同上 |
| 编译退出码 0 **≠** 中文没丢：必须看 `parse_log` 的缺字计数，否则会静默产出只剩 ASCII 的 PDF | `docs/verification/2026-11-09-pdf-pipeline.md` |
| 本机能跑 **≠** clone 能跑：每次推送后做真实 clone 验证，硬编码路径与未入库依赖只有这样才会暴露 | `docs/verification/2026-11-04-clean-unpack-drill.md` |
| 已沉淀技能 **9 个唯一**（`find . -name SKILL.md | wc -l` 数出 42 个文件，9 个唯一名；多出的是各 Agent 工作区副本，属 OpenClaw 技能发现机制的必需冗余） | `openclaw/workspace/skills/` |

## 领域速记
- LIBS：激光诱导击穿光谱；大颗粒原煤热值预测为回归任务。
- MIL：多示例学习；本课题用 ResNet1D(base=16) + SupCon 预训练 + TransMIL 注意力聚合 + FiLM(PLSR 得分)，
  预测的是**残差**，最后加回 PLSR 预测值。

## 未闭环（不要在别处说成已完成）
- 最终配置下 TransMIL vs Mean/Max 池化对比；单 seed、未做 2³ 交互效应
- 期刊等级仍为本地种子（`local_seed_unverified`）
- 领域泛化只有 1 个领域包；**无演示视频**；**无托管 CI**；A2A 协议层与 Computer Use 未使用
