// web/shared/tail_time.mjs 的行为测试：node --test "web/tests/**/*.test.mjs"
// 盯的不变量：tail 回放出来的上一轮轨迹既不能被计入本轮，也不能驱动本轮生命周期。
import { test } from "node:test";
import assert from "node:assert/strict";
import { tailLineMs, isCurrentRoundLine } from "../shared/tail_time.mjs";

const DAY = 86_400_000;
// 2026-10-30 05:34:39.492Z（实测一次回归的轮次开始时刻）
const NOW = Date.parse("2026-10-30T05:34:44.000Z");
const T = (h, mi, s) => Math.floor(NOW / DAY) * DAY + ((h * 60 + mi) * 60 + s) * 1000;

test("行首 HH:MM:SSZ 还原成当天绝对毫秒", () => {
  assert.equal(tailLineMs("05:34:41Z", NOW), T(5, 34, 41));
});

test("解析不出来的时间字段返回 null / 判定为不可用（CLI 噪声行不该被当成历史丢掉）", () => {
  for (const bad of ["", undefined, null, "raw line", "2026-10-30T05:34:41Z", "25:00:00Z", "05:61:00Z"]) {
    assert.equal(tailLineMs(bad, NOW), null, String(bad));
    assert.equal(isCurrentRoundLine(bad, 0, NOW), false, String(bad));
  }
});

test("本轮的行判为本轮：秒级截断让行时间比 startedAt 略早，靠回溯容忍兜住", () => {
  const startedAt = Date.parse("2026-10-30T05:34:39.492Z");
  // 05:34:39.600 发生的调用打印成 05:34:39Z，比 startedAt 早 492ms
  assert.equal(isCurrentRoundLine("05:34:39Z", startedAt, NOW), true);
  assert.equal(isCurrentRoundLine("05:34:41Z", startedAt, NOW), true);
});

test("上一轮的回放判为历史：既不入账，也不会让 session.ended 提前收口", () => {
  const startedAt = Date.parse("2026-10-30T05:34:39.492Z");
  assert.equal(isCurrentRoundLine("04:52:36Z", startedAt, NOW), false); // 实测的 42 分钟前那轮回放
  assert.equal(isCurrentRoundLine("05:34:37Z", startedAt, NOW), false); // 只差 2.5s 也不算本轮
});

test("跨零点：昨天 23:59 的历史还原成未来时刻后回退一天，仍判为历史", () => {
  const midnight = Date.parse("2026-10-30T00:00:35.000Z");
  const startedAt = Date.parse("2026-10-30T00:00:30.000Z");
  assert.equal(isCurrentRoundLine("23:59:00Z", startedAt, midnight), false);
  assert.ok(tailLineMs("23:59:00Z", midnight) < midnight);
});

test("跨零点的另一侧：昨天开跑、今天凌晨的行照样认作本轮", () => {
  const now = Date.parse("2026-10-30T00:01:00.000Z");
  const startedAt = Date.parse("2026-10-29T23:58:00.000Z"); // 长轮次跨过零点
  assert.equal(isCurrentRoundLine("00:00:30Z", startedAt, now), true);
});
