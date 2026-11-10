# 溯源解析两处硬伤：列表 metric 崩溃、括注切断 source

这两条都会让**数字本来是对的**声明被判成「不可溯源」。表现一样，改法不同。

## 一、`float(recorded)` 撞上列表 → 整批崩

`coal_mil` 注册表里 `per_fold_rmse_kcal` 是 5 项列表：

```python
truth = float(recorded)   # TypeError: float() argument must be str or number, not 'list'
```

一条声明就能把整个 `verify_claims` 掀翻——不是返回失败，是抛异常，
上层看到的是一整份 claims.json 无结果。

**约束**：注册表 metric 可能是标量、列表、甚至非数字。

- 列表**必须**写下标：`per_fold_rmse_kcal[0]`。不写下标返回 `metric_not_scalar`，
  **不许静默取第一项**——「第一折」和「五折均值」是两个数，猜错等于把整批数字
  记到错的位置上，比不判更糟。
- 标量误加下标 → `metric_not_list`；越界 → `metric_index_out_of_range`；
  非数字 → `metric_not_numeric`。四种分开报，因为改法不同。

## 二、括注里的冒号把 exp_id 切断

真实 claims.json 第 10 条：

```
registry:coal_mil#our_hybrid.config.n_total_params (源: summary.json)
```

`_parse_source` 用 `rest.split(":", 1)` 切 `registry:<domain>:<exp>`，
于是 `(源: summary.json)` 里的冒号让 exp_id 变成 ` summary.json)`，
判定结果 `unknown_experiment`——**一条数字完全正确的声明，被括号里的注释毁了**。

**约束**：解析 source 前先剥尾部括注（`[（(].*$`）。括注不是协议的一部分，
写手天天加，不能假设它干净。

## 三、`registry:<domain>#<exp>.<path>` 这个写法要不要兼容

要，但必须标记。

真实稿子里 12 条有 5 条这么写：把 domain 当实验 id、把 metric 塞进 `#` 锚点。
如果一律判 `unknown_experiment`，一份稿子的全部声明都会「不可溯源」——
**语法错误就被伪装成数据错误**，用户会去改数字，而数字是对的。

处理方式：能解析就解析（`source_style="legacy-anchor"`），但：

- 数值容忍度**不放宽**（1% 相对 + 0.01 绝对，一字不改）；
- 返回里带 `source_style`，让 UI 打「#锚点」标记，提示这不规范。

兼容的是语法，不是判定标准。两者混在一起才是真灾难。

## 怎么验证

```sh
python -m pytest tests/test_claim_provenance.py -q     # 18 passed
```

其中这几条直接对应上面的坑：

- `test_list_metric_without_index_is_refused` — 不写下标必须拒绝
- `test_list_metric_with_index_compares_that_element` — 下标取到的是那一折
- `test_note_with_colon_does_not_truncate_source` — 括注冒号不切 id
- `test_legacy_anchor_source_still_resolves` — `#` 写法能解析且被标记
- `test_claim_metric_miss_falls_back_to_source_anchor` — claim.metric 写错但 source 指对时回退
- `test_scientific_notation_string_value` — `8.963e-1` 早先会被正则截成 `8.963`
