# E2E 阶段⑥：发表追踪 / 期刊推荐（受控·真实）

你是 gewu-publication。基于 `openclaw/workspace/agents/gewu-writer/handoff_5_draft.json`
（MIL+LIBS 大颗粒原煤热值论文草稿）做**真实**期刊推荐（E2E 阶段⑥，本 E2E 的关键验收点）。

## 执行（真实推荐，禁止编造等级）
1. 用 journal-match 技能真实跑推荐：可调用
   `openclaw/workspace/agents/gewu-publication/skills/journal-match/scripts/run_recommendation.py`
   （格物 default venv 直跑），或遵循 SKILL.md 六步。论文 profile 已隐含于 handoff_1/2/5
   （MIL + LIBS + 大颗粒原煤 + 热值回归；中文候选含《光谱学与光谱分析》《分析化学》）。
2. 每个候选期刊必须：
   - 经 `mcp__sci-verify__verify_papers`（OpenAlex 第4层 D1）做存在性核验；
   - 经 `mcp__sci-verify__get_journal_rank("<刊名>")` 取 **EasyScholar 真实等级/分区**
     （SCI/SSCI/Q区、中科院分区、CSCD/北大核心等）；无数据者标「待核查」，禁止编造。
3. 产出 `reports/2026-10-26-journal-match-mil-libs-coal.html`（单文件 HTML 报告，设计系统见
   skills/journal-match/shared/report-template.md）。
4. 写 `openclaw/workspace/agents/gewu-publication/handoff_6_publish.json`：
   `{stage:6, stage_name:"发表追踪", status, inputs:[handoff_5路径], outputs:[报告路径],
   recommended_tier1:[{name, rank, d1_status}], next:"distillation", next_input:"handoff_6_publish.json"}`

## 纪律
- 期刊等级**必须**来自 get_journal_rank 真实接口，不得模型自断言。
- D1 未核验期刊不得作为"推荐"呈现，降为"待人工确认"。
- 超时前落盘 handoff_6 与 HTML 报告。
