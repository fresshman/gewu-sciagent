# 最小调用示例（接口演示，非真实案例）

> ⚠️ **本目录全部内容都是虚构的接口示例**，用于说明输入/输出契约与自检。
> 它不是任何论文的真实材料，不是正式测试案例，也不是预先写好的答案。
> 平台固定案例由组织方提供；运行时以 `/input/case.json` 与实际 PDF 为准。

## 输入

- `minimal_case.json`：最小的 case，演示 `output_contract` 的字典形态。
- `fixture/paper_excerpt.md`：虚构论文片段，故意含参数与指标数值。
- `fixture/config.yaml`：虚构配置，`lr` 与论文不一致，用来演示**冲突登记**。
- `fixture/reproduce.py`：虚构代码，`batch_size` 默认值与论文不一致，演示三源对齐。
- `fixture/results.json`：虚构复现输出，含逐折指标用于出图。

## 调用

```bash
cd <skill 根目录>
python scripts/repro_cli.py run \
  --case examples/minimal_case.json --inputs examples/fixture \
  --work /tmp/repro-work --out /tmp/repro-out

python scripts/repro_cli.py locate --out /tmp/repro-out --q "learning rate"
python scripts/repro_cli.py finalize --case examples/minimal_case.json --out /tmp/repro-out
```

## 示意输出（仅示意，非正式结果）

见 `example_result.json`。真实运行时 `result.json` 由 Agent 按 `task.md`
与**实际论文**填写，脚本只生成带 `null` 的契约骨架。

预期能看到：`parameters.json` 里 `lr` / `batch_size` 带 `conflict=true`；
`comparison.json` 有容差前置的 PASS/FAIL 行；`figures/` 有逐折复现图；
`repro/run_log.jsonl` 记录每一步。
