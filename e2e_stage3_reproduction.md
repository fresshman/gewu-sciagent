# E2E 阶段③：复现（受控·真实推理）

你是 gewu-reproduction。基于 `openclaw/workspace/agents/gewu-ideation/handoff_2_litreview.json`
与 `openclaw/workspace/agents/gewu-director/handoff_1_direction.json` 做**真实**复现（E2E 阶段③）。

## 执行（真实工具，禁止编造）
1. 调用**真实** mil-model 工具（以下三者均无需额外路径参数，直接可用）：
   - `mcp__mil-model__cv_summary`：复现 5 折交叉验证指标（应与官方 RMSE≈214.57 kcal/kg 对齐），
     记录 mean_rmse_kcal_kg、std、mean_rmse_MJ_kg、逐折 hybrid_rmse/plsr_rmse、cross_check。
   - `mcp__mil-model__reproduce_fold`：复现第 0 折验证集全部预测，返回 RMSE/MAE/R² 与逐 bag 明细。
   - `mcp__mil-model__list_val_bags`：列出第 0 折验证集 bag 列表（可选）。
   ⚠️ **不要调用 `predict_calorific_value`**：它必须传真实 `bag_dir` 磁盘路径，本环境未提供样本包目录，
   调用必失败并触发重试超时。若确实想单 bag 预测，须先用 `list_val_bags` 取真实 bag_dir 再传。
2. 写两个文件到 `openclaw/workspace/agents/gewu-reproduction/`：
   - `handoff_3_repro.json`：`{stage:3, stage_name:"复现", status, inputs:[handoff_2路径,handoff_1路径], outputs:[...], baseline_metrics:{rmse_kcal, rmse_mj, mae, n_folds, per_fold:{}}, next:"improver", next_input:"handoff_3_repro.json"}`
   - `repro_lock.json`：数据路径（COAL_PROJECT_ROOT 引用，不写死绝对路径）、预处理超参
     （sg/als/mms）、PLSR n=7、MIL 结构、随机种子、指标口径——防方法漂移。

## 纪律
- 必须用真实 mil-model 工具取真实数值，**禁止编造**；工具调用 ~8 次以内。
- 超时前必须落盘 `handoff_3_repro.json`。
- 真值隔离：预测值不得回填当真值。
