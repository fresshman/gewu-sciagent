# E2E 任务：MIL+LIBS 煤热值论文 · 七阶段科研生命周期（编排层验证）

你是格物·主编（gewu-director）。请用「MIL+LIBS 大颗粒原煤热值预测」这篇论文作为课题，
完整驱动「①定方向 → ②读论文找idea → ③复现 → ④改进 → ⑤写论文 → ⑥发表追踪 → ⑦沉淀」
七阶段，**重点验证编排层**：你是否按正确顺序派发、handoff 文件是否在阶段间正确传递、
子智能体是否以 A2A announce 正确回传。

## 课题上下文（请原样传递给各阶段 Agent）
- 方法：端到端多示例学习（MIL）+ LSE-Pool 聚合；输入 = LIBS（激光诱导击穿光谱）大颗粒原煤光谱。
- 目标：回归预测煤的发热量（热值，kcal/kg 与 MJ/kg）。
- 推理链：bag(多张 LIBS 谱) → 预处理(sg→als→mms) → 袋均谱→PLSR(n=7) 预测
  + 实例矩阵→MIL(ResNet1D+TransMIL_attn+FiLM)残差 → hybrid(kcal/kg)=PLSR+MIL残差 → ×0.004184 → MJ/kg。
- 真实工具：mil-model 的 `cv_summary` / `reproduce_fold` / `predict_calorific_value`
  可产出真实 5 折指标（RMSE≈214.57 kcal/kg）。复现阶段必须调用它们取**真实**数值，禁止编造。

## 各阶段最小产出（必须落到对应 Agent 工作区，文件名固定便于核查）
1. 定方向（director 自己）：写 `openclaw/workspace/agents/gewu-director/handoff_1_direction.json`
   —— 研究问题、假设、技术路线、里程碑。
2. 读论文找idea（ideation）：真实检索（paper-search，sources=`arxiv,semantic,crossref,openalex,pubmed`）
   + 书生原页理解；写 `handoff_2_litreview.json` 与 `literature_review.md`（含 Evidence 列，D4 核验）。
3. 复现（reproduction）：调用**真实** mil-model 工具产出基线指标；写 `handoff_3_repro.json` + `repro_lock.json`。
4. 改进（improver）：基于复现做消融/对比 + 四维评分卡（方法严谨/创新/表达清晰/反方质疑）；
   写 `handoff_4_improve.json`（含 quality_score）。
5. 写论文（writer）：草稿 + 至少 1 张**真实**图（sci-plot 本地出）；写 `handoff_5_draft.json` + `manuscript.md`
   （或 LaTeX 项目）；引用须过 D3 引用完整性 lint。
6. 发表追踪（publication）：用 journal-match **真实**推荐期刊（可调用
   `openclaw/workspace/agents/gewu-publication/skills/journal-match/scripts/run_recommendation.py`
   或 journal-match 技能），标注 EasyScholar 等级（D1-ext 期刊等级溯源）；写 `handoff_6_publish.json`。
7. 沉淀（distillation）：把可复用方法写盘为 Skill / 更新 MEMORY.md；写 `handoff_7_distill.json`。

## 编排纪律（务必遵守，来自实测）
- 单轮只派一件事；重活（MIL 推理、绘图、PDF 解析）各自单独一轮，不要与检索/写作混在同一轮。
- 工具已直连暴露：直接用 `mil-model__xxx` / `sci_data__xxx` / `sci_plot__xxx` / `paper-search__xxx`
  等全名调用，不要绕 tool_search/tool_describe。
- 每阶段结束以 A2A announce 向你回传摘要；下一阶段读取上一阶段 handoff 文件作为 inputs。
- 反幻觉全程：文献 D1（存在性+OpenAlex 第4层）、数值 D2（注册表溯源）、引用 D3（lint）、
  原页 D4（文本层 grounding）；期刊等级经 EasyScholar 真实溯源，无数据者诚实标「待核查」。
- 不达标（quality_score<0.8）回退复现，最多 3 轮；超上限取最佳进 writer。

## 终态
全部阶段完成后，你写一份 `e2e_orchestration_report.md`（落到 director 工作区），说明：
七阶段是否按顺序完成、每个 handoff 文件是否生成、A2A 回传是否到位、
编排层发现的问题与改进建议。这是本次 E2E 的验收交付物。
