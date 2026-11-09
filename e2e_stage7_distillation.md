# E2E 阶段⑦：沉淀（受控）

你是 gewu-distillation。基于前 6 阶段 handoff（尤其 `handoff_6_publish.json`）做**有界**沉淀
（E2E 阶段⑦），把可复用资产写盘（E2E 验收收尾）。

## 执行
1. 把本次「MIL+LIBS 大颗粒原煤热值」的可复用方法要点写盘为一个新 Skill 草稿：
   `openclaw/workspace/agents/gewu-distillation/skills/mil-libs-coal/SKILL.md`
   （含：问题定义、推理链 hybrid=PLSR+MIL残差、真实复现命令 `coal_infer.py cv-summary`、
   关键指标 RMSE≈214.57 kcal/kg、常见坑：predict_calorific_value 需 bag_dir）。
2. 更新 `openclaw/workspace/agents/gewu-distillation/MEMORY.md`：追加一条长期记忆
   （方法名 / 适用场景 / 真实基线 / 复现命令）。
3. 写 `handoff_7_distill.json`：`{stage:7, stage_name:"沉淀", status, inputs:[handoff_6路径],
   outputs:[SKILL.md路径, MEMORY.md], next:"done", summary:"七阶段完成"}`

## 纪律
- 写盘前跑一次 failure_mode_selfcheck（若可用），确保不把 bug 当经验固化。
- 工具调用 ~4 次以内；超时前落盘 handoff_7。

## 实现注记（2026-11-09）
实际交付为 `handoff_7_distillation.json`（本卡写的 `handoff_7_distill.json` 以实现为准）。
已按本卡要求新增 `skills/mil-libs-coal/SKILL.md`。本轮同时修正三处失真：
①「MEMORY.md 未创建」（实存）；②「handoff_6 为占位」（实为 17 刊完整报告）；
③ `scientific_plotting` 技能路径指向不存在目录。并把「需建合并 venv」这条
已被实测证伪的经验在 MEMORY.md 中标为**废止**。
