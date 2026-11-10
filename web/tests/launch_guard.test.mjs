// web/shared/launch_guard.mjs 的行为测试
// 盯的不变量：**默认拒绝**。版本解析失败、25.x、24.15 都必须判"不满足"，
// 因为这条闸门的失败模式是"静默用错 Node 去跑 openclaw"，代价是每句话都失败。
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  parseNodeVersion,
  nodeGateOk,
  parseNpmRootG,
  openclawEntryFromRoot,
  pickRuntime,
  formatRefusal,
  formatDegradedWarning,
  NODE_GATE_TEXT,
} from "../shared/launch_guard.mjs";

test("版本解析：容忍 v 前缀与末尾附加信息，解析不了返回 null 而不是 0.0.0", () => {
  assert.deepEqual(parseNodeVersion("v24.16.0"), [24, 16, 0]);
  assert.deepEqual(parseNodeVersion("24.16.0"), [24, 16, 0]);
  assert.deepEqual(parseNodeVersion(" v26.1.2\n"), [26, 1, 2]);
  for (const bad of ["", "node", "v24", "24.16", null, undefined, 24]) {
    assert.equal(parseNodeVersion(bad), null, String(bad));
  }
});

test("闸门边界：24.16 是下限且 25.x 整条线被排除，26.1 是下一段下限", () => {
  const pass = ["v24.16.0", "v24.16.1", "v24.99.0", "v26.1.0", "v26.9.0", "v27.0.0"];
  const fail = [
    "v22.22.2", // 本机实测踩到的版本
    "v23.11.0",
    "v24.15.9", // 差一个补丁就够，但仍必须拒绝
    "v25.0.0",
    "v25.8.1", // 25.x 整条线被 openclaw 排除
    "v26.0.0", // 26.0 不够，要 26.1
    "garbage",
    "",
    null,
  ];
  for (const v of pass) assert.equal(nodeGateOk(v), true, v);
  for (const v of fail) assert.equal(nodeGateOk(v), false, String(v));
});

test("npm root -g 解析：取最后一行非空、去掉尾部分隔符（Windows 反斜杠同样处理）", () => {
  assert.equal(parseNpmRootG("C:\\Users\\a\\.npm-global\\node_modules\r\n"), "C:\\Users\\a\\.npm-global\\node_modules");
  assert.equal(parseNpmRootG("/usr/local/lib/node_modules/\n"), "/usr/local/lib/node_modules");
  assert.equal(parseNpmRootG("npm warn foo\n/opt/lib/node_modules"), "/opt/lib/node_modules");
  assert.equal(parseNpmRootG(""), null);
  assert.equal(parseNpmRootG(null), null);
});

test("入口只允许真实 .mjs 形态，不在模块里拼 shell 垫片", () => {
  const p = openclawEntryFromRoot("C:\\g\\node_modules");
  assert.match(p.replace(/\\/g, "/"), /node_modules\/openclaw\/openclaw\.mjs$/);
  assert.equal(openclawEntryFromRoot(null), null);
});

test("挑运行时：前一个不满足就继续找，且保留拒绝理由", () => {
  const { picked, rejected } = pickRuntime([
    { path: "/n22", version: "v22.22.2" },
    { path: "/n24", version: "v24.15.0" },
    { path: "/n26", version: "v26.9.0" },
  ]);
  assert.equal(picked.path, "/n26");
  assert.equal(rejected.length, 2);
  assert.match(rejected[0].reason, /不满足闸门/);

  // 取不到版本的候选也要说明，不许静默跳过
  const r2 = pickRuntime([{ path: "/broken", version: null }, { path: "/ok", version: "v24.16.0" }]);
  assert.equal(r2.picked.path, "/ok");
  assert.match(r2.rejected[0].reason, /取不到版本号/);
});

test("挑运行时：全都不满足时 picked 为 null（调用方据此拒绝启动）", () => {
  const { picked, rejected } = pickRuntime([
    { path: process.execPath, version: "v22.22.2" },
    { path: "/n25", version: "v25.0.0" },
  ]);
  assert.equal(picked, null);
  assert.equal(rejected.length, 2);
  assert.equal(pickRuntime([]).picked, null);
  assert.equal(pickRuntime(undefined).picked, null);
});

test("拒绝文案：中文、点名当前版本与要求、给出可执行修法，且不出现英文堆栈", () => {
  const msg = formatRefusal({
    nodeVersion: "v22.22.2",
    entryPath: "C:/g/node_modules/openclaw/openclaw.mjs",
    port: 3112,
    rejected: [{ path: "C:/node22/node.exe", reason: "v22.22.2 不满足闸门" }],
  });
  assert.match(msg, /拒绝启动/);
  assert.match(msg, /v22\.22\.2/);
  assert.ok(msg.includes(NODE_GATE_TEXT));
  assert.match(msg, /bash start-gewu\.sh/);
  assert.match(msg, /GEWU_NODE=/);
  assert.match(msg, /OPENCLAW_MJS=/);
  assert.match(msg, /3112/);
  assert.match(msg, /已检查过的运行时/);
  // 不该把 openclaw 的英文报错糊到用户脸上
  assert.doesNotMatch(msg, /node:sqlite|ExperimentalWarning|trace-warnings/);
});

test("拒绝文案：找不到入口时说的是入口，不是版本（归因不能串）", () => {
  const msg = formatRefusal({ nodeVersion: "v26.1.0", entryPath: null, port: 3000 });
  assert.match(msg, /找不到 openclaw 入口/);
  assert.doesNotMatch(msg, /不满足要求/);
});

test("降级文案：明确写出网关不会被拉起，避免使用者误以为能用", () => {
  const w = formatDegradedWarning({ nodeVersion: "v22.22.2", entryPath: null });
  assert.match(w, /降级启动/);
  assert.match(w, /\/api\/chat/);
  assert.match(w, /v22\.22\.2/);
});
