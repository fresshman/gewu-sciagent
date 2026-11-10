// 结束原因标签的测试。
//
// 为什么值得单独测：这三个字看起来无害，但它出现在「出错」和「成功」两种
// 完全相反的场合。翻错了不只是不好看——用户会以为一次被中止的运行跑成功了。
// 所以这里除了锁翻译，还锁「认不出来就原样显示」，不许猜。

import { test } from "node:test";
import assert from "node:assert";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, join } from "node:path";
import { transformSync } from "esbuild";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = join(HERE, "..");
const SRC = join(WEB, "src", "lib", "disposition.ts");
const OUT_DIR = join(WEB, "node_modules", ".gw-test");
const OUT = join(OUT_DIR, "disposition.mjs");

mkdirSync(OUT_DIR, { recursive: true });
writeFileSync(
  OUT,
  transformSync(readFileSync(SRC, "utf8"), {
    loader: "ts",
    format: "esm",
    target: "es2022",
  }).code
);
const { dispositionText, dispositionTone } = await import(pathToFileURL(OUT).href);

test("常见结束原因翻成中文", () => {
  assert.strictEqual(dispositionText("success"), "成功");
  assert.strictEqual(dispositionText("timeout"), "超时");
  assert.strictEqual(dispositionText("aborted"), "中止");
  assert.strictEqual(dispositionText("error"), "出错");
});

test("大小写与前后空白不影响判定（协议字段不该让界面出空白）", () => {
  assert.strictEqual(dispositionText("  SUCCESS "), "成功");
  assert.strictEqual(dispositionText("Timeout"), "超时");
});

test("空值给破折号，不显示空串", () => {
  assert.strictEqual(dispositionText(""), "—");
  assert.strictEqual(dispositionText(undefined), "—");
  assert.strictEqual(dispositionText(null), "—");
});

test("认不出来的值原样显示，不猜成「成功」", () => {
  // 带后缀的复合值仍然要认出来（cancelled_by_user → 取消），这不算「认不出来」
  assert.strictEqual(dispositionText("cancelled_by_user"), "取消");
  assert.strictEqual(dispositionText("aborted_by_budget"), "中止");
  // 真正没规则的词，一个字都不改：宁可露出内部字段，也不要翻成错误的结论
  assert.strictEqual(dispositionText("partial"), "partial");
  assert.strictEqual(dispositionText("quarantined"), "quarantined");
});

test("观感色：成功=ok，出错=err，超时/中止=warn（不是 err，也不是 ok）", () => {
  assert.strictEqual(dispositionTone("success"), "ok");
  assert.strictEqual(dispositionTone("error"), "err");
  assert.strictEqual(dispositionTone("timeout"), "warn");
  assert.strictEqual(dispositionTone("aborted"), "warn");
  assert.strictEqual(dispositionTone(""), "warn");
});

test("出错的运行绝不能拿到 ok 色", () => {
  for (const bad of ["error", "failed", "fail"]) {
    assert.notStrictEqual(dispositionTone(bad), "ok", bad);
  }
});
