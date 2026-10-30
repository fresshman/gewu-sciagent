// web/shared/run_budget.mjs 的行为测试：node --test "web/tests/**/*.test.mjs"
// 盯两条不变量：① 判定要能在事件到达那一刻执行（不靠 10 秒轮询）；
// ② 在飞越限=exceeded，收尾后才越限=overrun，成功轮次不被追溯打成失败。
import { test } from "node:test";
import assert from "node:assert/strict";
import { BudgetGate, budgetFromEnv } from "../shared/run_budget.mjs";

const B = { warnTools: 20, hardTools: 30, warnMs: 18 * 60_000, hardMs: 25 * 60_000 };

test("工具数在飞越硬阈值 → budget.hard / exceeded=true / 维度 tools", () => {
  const g = new BudgetGate(B);
  const ev = g.observe({ toolCalls: 30, elapsedMs: 60_000, inFlight: true });
  assert.deepEqual(ev.map((e) => e.type), ["budget.warn", "budget.hard"]);
  assert.equal(ev[1].exceeded, true);
  assert.equal(ev[1].dimension, "tools");
});

test("轮次已收尾后才补上越限 → 只记 overrun，不打 exceeded", () => {
  const g = new BudgetGate(B);
  const ev = g.observe({ toolCalls: 50, elapsedMs: 374_000, inFlight: false });
  assert.deepEqual(ev.map((e) => e.type), ["budget.overrun"]);
  assert.equal(ev[0].exceeded, false);
  assert.equal(g.hardFired, false);
  assert.deepEqual(g.overrun, { dimension: "tools", toolCalls: 50, elapsedMs: 374_000 });
});

test("墙钟越线（工具数没到）同样触发硬闸门，维度 wall", () => {
  const g = new BudgetGate(B);
  const ev = g.observe({ toolCalls: 3, elapsedMs: 25 * 60_000 + 1, inFlight: true });
  assert.deepEqual(ev.map((e) => e.type), ["budget.warn", "budget.hard"]);
  assert.equal(ev[1].dimension, "wall");
});

test("收尾时补判：在飞期间已经硬触发过就不再重复记账", () => {
  const g = new BudgetGate(B);
  g.observe({ toolCalls: 31, elapsedMs: 60_000, inFlight: true });
  assert.deepEqual(g.observe({ toolCalls: 44, elapsedMs: 70_000, inFlight: false }), []);
});

test("阈值未越线不产生任何动作；软阈值只播一次", () => {
  const g = new BudgetGate(B);
  assert.deepEqual(g.observe({ toolCalls: 5, elapsedMs: 1000, inFlight: true }), []);
  const first = g.observe({ toolCalls: 21, elapsedMs: 1000, inFlight: true });
  assert.deepEqual(first.map((e) => e.type), ["budget.warn"]);
  assert.deepEqual(g.observe({ toolCalls: 25, elapsedMs: 2000, inFlight: true }), []);
});

test("软阈值在收尾后不再补发（成功短轮次不该有预警噪音）", () => {
  const g = new BudgetGate(B);
  assert.deepEqual(g.observe({ toolCalls: 25, elapsedMs: 1000, inFlight: false }), []);
});

test("summary：exceeded 与 overrun 各归各位，字段可直接落 run.budget", () => {
  const g = new BudgetGate(B);
  g.observe({ toolCalls: 50, elapsedMs: 400_000, inFlight: false });
  const s = g.summary({ toolCalls: 50, elapsedMs: 400_000 });
  assert.equal(s.exceeded, false);
  assert.equal(s.overrun, "tools");
  assert.equal(s.toolCalls, 50);
  assert.match(s.at, /^\d{4}-\d{2}-\d{2}T/);
});

test("budgetFromEnv：环境变量覆盖默认阈值，非法值回落默认", () => {
  const b = budgetFromEnv({ GEWU_RUN_BUDGET_TOOLS: "4", GEWU_RUN_BUDGET_WARN_MINUTES: "0", GEWU_RUN_SLOW_GAP_MS: "abc" });
  assert.equal(b.hardTools, 4);
  assert.equal(b.warnMs, 18 * 60_000);
  assert.equal(b.slowGapMs, 120_000);
  assert.deepEqual(budgetFromEnv({}), {
    warnTools: 20, hardTools: 30, warnMs: 18 * 60_000, hardMs: 25 * 60_000, slowGapMs: 120_000,
  });
});

test("构造时缺 budget 直接抛，不静默用 undefined 阈值（判定会永远 false）", () => {
  assert.throws(() => new BudgetGate(), /budget 不能为空/);
});
