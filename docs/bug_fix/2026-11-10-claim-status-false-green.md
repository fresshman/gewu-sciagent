# 假绿：「有 source 字段」被当成了「已核」

## 现象

论文库第一行（用户自己的稿子）挂着绿色徽章「已核 · 12 条声明 · 均带来源指针」，
底栏写「本稿声明已核 1」。而把这 12 条送进 D2 引擎实测：

```
n_claims 12 · n_grounded 0 · n_drift 0 · n_unverifiable 12
counts: unknown_experiment 5, bad_source 7
```

**一条都对不上。** 徽章的绿色完全来自 `claims.json` 里每条都有 `source` 这个键。

## 根因

`web/proxy/paper_index.mjs` 里：

```js
check: own.claimsCount
  ? { t: "已核", cls: "b-ok", sub: `${own.claimsCount} 条声明 · 均带来源指针` }
```

`claimsCount` 是「数组长度」，不是「通过核验的条数」。两件事在 UI 上长得一样，
于是「有指针」被渲染成「已核」。

同源的还有 `summary.ownChecked`——它用 `check.cls === "b-ok"` 反推计数，
所以徽章一错，汇总跟着错，`PaperLibrary.tsx` 底栏那句「本稿声明已核 1」也是假的。

## 约束（下次照这条做）

1. **列表页不许对「核没核过」下结论。** 判定权只有一处：`gewu/mcp/claim_provenance.py`
   经 `/api/writing/claims` 暴露。列表页最多能说「有 N 条待核」。
2. 任何 `已核 / 通过 / 有效 / verified` 字样，必须能指到**一次真实判定调用**。
   指不到的，改成「待核 / 未跑 / 未知」——宁可难看，不可撒谎。
3. 汇总数字不许从徽章类名反推（`cls === "b-ok"`）。要数就数事实字段。
4. **修 bug 时测试变红，先分清是代码错了还是测试锁错了。**
   这里 `tests/paper_index.test.mjs` 原本写着
   `assert.equal(g("mine").check.t, "已核")`——测试把 bug 锁成了期望值。
   这种测试不是保护，是共犯。

## 怎么验证

```sh
# 列表页不该再出现「已核」描述自己的稿子
curl -s localhost:3112/api/library | jq '.items[] | select(.kind=="own") | .check'
# → {"t":"待核","cls":"b-warn","sub":"12 条声明 · 未跑溯源引擎"}

# 真实判定
curl -s localhost:3112/api/writing/claims | jq '{n_claims,n_grounded,n_unverifiable,counts}'
# → 12 / 4 / 8 / {grounded:4, bad_source:7, metric_not_in_registry:1}
```

回归锚点：`tests/test_claim_provenance.py::test_real_claims_json_is_not_green`
断言 `not rep["all_grounded"]`。数字若变动（比如真的修好了 claims.json），
这条要跟着改——但它绝不允许被删掉换成 `assert True`。
