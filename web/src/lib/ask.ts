// 结构化提问块：让 agent 的「我需要你先定一件事」变成一个能点的问卷，
// 而不是一段散文。
//
// 为什么不做成阻塞式工具调用（agent 调 ask_user 后原地等 HTTP 回填）：
// 我们这条链路是 web → proxy → CLI 子进程。工具在子进程里阻塞时，用户一旦
// 关掉标签页或换台机器，答案永远不来，整轮对话就死在那儿，也没有可续的通道。
// 所以这里退一步：agent 照旧结束本回合，只是把问题写成结构化块；用户点选后
// 结果当作下一条普通消息发回去。代价是多一次往返，换来的是「永远不会卡死」。
//
// 块格式（三个反引号 + ask）：
//   ```ask
//   {"question": "…", "why": "…", "options": [{"label": "…", "desc": "…"}], "multi": false}
//   ```
//
// 解析失败一律返回 null，让原文照常按代码块显示——宁可不渲染，也不能悄悄
// 吞掉一段模型输出。

export interface AskOption {
  label: string;
  desc?: string;
}

export interface AskBlock {
  question: string;
  why?: string;
  options: AskOption[];
  multi: boolean;
  /** 原始围栏（含首尾三反引号），用于从正文里剥离 */
  raw: string;
}

/** 选项上限：再多就不是「一页一题」，而是一张需要滚动挑选的菜单 */
const MAX_OPTIONS = 8;

const FENCE = /^```ask[ \t]*\r?\n([\s\S]*?)^```[ \t]*$/m;

function clean(s: unknown): string {
  return typeof s === "string" ? s.trim() : "";
}

export function parseAsk(text: string | undefined | null): AskBlock | null {
  const src = String(text || "");
  if (!src.includes("```ask")) return null;
  const m = FENCE.exec(src);
  if (!m) return null; // 围栏没闭合（多半还在流式输出）——等它闭合再说

  let obj: unknown;
  try {
    obj = JSON.parse(m[1]);
  } catch {
    return null;
  }
  if (!obj || typeof obj !== "object") return null;

  const o = obj as Record<string, unknown>;
  const question = clean(o.question);
  if (!question) return null;
  if (!Array.isArray(o.options)) return null;

  const options: AskOption[] = [];
  for (const raw of o.options) {
    if (!raw || typeof raw !== "object") continue;
    const oo = raw as Record<string, unknown>;
    const label = clean(oo.label);
    if (!label) continue;
    const desc = clean(oo.desc);
    options.push(desc ? { label, desc } : { label });
  }
  // 一个选项的「问卷」等于一段陈述，没有可选性；要求至少两个
  if (options.length < 2) return null;

  return {
    question,
    why: clean(o.why) || undefined,
    options: options.slice(0, MAX_OPTIONS),
    multi: o.multi === true,
    raw: m[0],
  };
}

/** 把提问块从正文里摘掉：正文照旧走 Markdown，问卷由组件单独渲染 */
export function stripAsk(text: string, block: AskBlock | null): string {
  if (!block) return text;
  return text.replace(block.raw, "").replace(/\n{3,}/g, "\n\n").trim();
}

/** 用户的选择 → 回填给 agent 的一句话。单选用标签本身，多选用顿号连。 */
export function answerText(block: AskBlock, picked: number[]): string {
  const labels = picked
    .map((i) => block.options[i]?.label)
    .filter((x): x is string => Boolean(x));
  if (!labels.length) return "";
  return block.multi ? labels.join("、") : labels[0];
}
