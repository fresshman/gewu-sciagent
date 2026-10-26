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
