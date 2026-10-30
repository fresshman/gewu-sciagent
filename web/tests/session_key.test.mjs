// web/shared/session_key.mjs 的行为测试：node --test "tests/**/*.test.mjs"
// 盯的是「tail 与轮次必须落在同一个会话名下」这条不变量——裸 key 会让工具计数闸门全程失明。
import { test } from "node:test";
import assert from "node:assert/strict";
import { canonicalSessionKey } from "../shared/session_key.mjs";

test("裸 key 补上调用方 agent 前缀", () => {
  assert.equal(canonicalSessionKey("gewu-director", "gewu-seven-1030"),
    "agent:gewu-director:gewu-seven-1030");
});

test("前端自动生成的 key 原样通过（生产路径零行为变化）", () => {
  const k = "agent:gewu-reproduction:6f0a1c2e-9d3b-4a11-8f55-0c2b1a9e7d44";
  assert.equal(canonicalSessionKey("gewu-reproduction", k), k);
});

test("已带 agent: 前缀但指向别的 agent 时不改写命名空间", () => {
  assert.equal(canonicalSessionKey("gewu-director", "agent:gewu-reproduction:resume-1"),
    "agent:gewu-reproduction:resume-1");
});

test("幂等：归一化两次与一次相同（续跑复用同一 key 不会套娃）", () => {
  const once = canonicalSessionKey("gewu-director", "drill-1");
  assert.equal(canonicalSessionKey("gewu-director", once), once);
});

test("空 key / 空 agent 直接抛，不静默造出畸形会话名", () => {
  assert.throws(() => canonicalSessionKey("gewu-director", ""), /runKey 不能为空/);
  assert.throws(() => canonicalSessionKey("", "drill-1"), /agent 不能为空/);
});

test("paper/translate 这类带冒号的命名空间 key 仍会被前缀化（它们不走 tail，不受本修影响）", () => {
  assert.equal(canonicalSessionKey("gewu-writer", "paper:2406.05975:uuid-9"),
    "agent:gewu-writer:paper:2406.05975:uuid-9");
});
