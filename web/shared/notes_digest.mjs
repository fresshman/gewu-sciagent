// 阅读笔记 → 送复现 handoff 里的表示（上下文瘦身 T2：handoff 侧）
//
// 替代原先的 `notesFull.slice(0, 4000)` 硬截断。四条硬约束沿用 T1「摘要 + 落盘 + 回取」：
//  0) 装得下就整篇原样带上（mode=full_verbatim）。摘要只在旧代码开始切正文时才登场——
//     实测一份 2,363 字符的真实规模笔记做摘要后体积只降 14.2%，却把 8/10 条核心数值句挤出内联，
//     比旧截断更亏：省不出信息量的压缩等于自残。
//  1) 数值行/主张行永远整句原样保留。`RMSE=214.5699±25.7094 kcal/kg` 被切掉半截就是
//     反幻觉事故——赛题卖点是数值可溯源，所以「要么整句进摘要，要么整块不内联并明说」，
//     绝不出现「留下前一半数字」的第三种状态。
//  2) 散文只在句子/空白边界收尾，且预算不够时先丢散文头、不丢数值句（数值句先占预算）。
//  3) 摘要只当目录用：全文留在磁盘上，复现员用 Read 本地读原文（零网关往返，
//     比 expand 一次远程回取便宜得多——实测一次网关往返 10~20s）。

const SENTENCE_TERMINATORS = "。！？；!?;\n";

// 数值句判定：含数字 且（命中指标/超参/单位关键词 或 带小数/±/%）
const NUMERIC_HINT =
  /(rmse|mae|mse|msre|\br²\b|\br2\b|\bf1\b|auc|\bap\b|iou|precision|recall|accuracy|\bp[-=]?\s*value|p<|系数|精度|误差|偏差|方差|信噪比|检出限|\blod\b|\blos\b|热值|kcal|mj|kg|wt%|℃|epoch|batch|learning|\blr\b|hidden|dim|layer|层|维度|参数|节点|特征|样本|实例|数据|折|交叉验证|seed|时间|耗时|秒|分钟|小时)/i;

// 主张句判定：阅读阶段留下的判断，复现员要对着验，丢了就等于把结论丢了
const CLAIM_HINT =
  /(创新|贡献|结论|局限|不足|未来|待验证|需验证|需要验证|存疑|疑问|无法复现|未提及|声称|表明|假设|疑问点|风险|注意|坑|limitation|contribution|novelty|claim)/i;

// 单句超过这个长度就只进「长句清单」，不整句内联（仍然给路径，不切半句）
const LONG_SENTENCE = 500;
// 同形行（只差数字的表格行/列表行）每个形状最多内联这么多条，其余折成计数
const REPEAT_HEAD = 5;

export function stripFrontMatter(md) {
  const m = String(md || "").match(/^---\n([\s\S]*?)\n---\n\n?([\s\S]*)$/);
  return m ? { frontMatter: m[1], body: m[2] } : { frontMatter: "", body: String(md || "") };
}

// 按 markdown 标题切段；标题前的内容算「前言」段（level 0）
export function splitSections(body) {
  const lines = String(body || "").split(/\r?\n/);
  const sections = [];
  let cur = { heading: null, level: 0, lines: [] };
  for (const line of lines) {
    const h = line.match(/^(#{1,6})\s+(.*\S)\s*$/);
    if (h) {
      if (cur.lines.some((l) => l.trim())) sections.push(cur);
      cur = { heading: h[2], level: h[1].length, lines: [line] };
    } else {
      cur.lines.push(line);
    }
  }
  if (cur.lines.some((l) => l.trim())) sections.push(cur);
  return sections.map((s) => {
    const text = s.lines.join("\n").trim();
    return { heading: s.heading, level: s.level, text, chars: text.length };
  });
}

// 把段落切成「句单元」：表格行/列表行整体成单元，普通行按句末标点切
export function toUnits(text) {
  const units = [];
  for (const rawLine of String(text || "").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    if (/^(\||[-*]\s|\d+[.)]\s|>|#{1,6}\s)/.test(line) || !/[。！？；!?;]/.test(line)) {
      units.push(line);
      continue;
    }
    let buf = "";
    for (const ch of line) {
      buf += ch;
      if (SENTENCE_TERMINATORS.includes(ch) && ch !== "\n") {
        if (buf.trim()) units.push(buf.trim());
        buf = "";
      }
    }
    if (buf.trim()) units.push(buf.trim());
  }
  return units;
}

function isNumeric(unit) {
  if (!/\d/.test(unit)) return false;
  return NUMERIC_HINT.test(unit) || /\d+\.\d/.test(unit) || unit.includes("±") || /%/.test(unit);
}

// 抽数值句 + 主张句（整句原样，去重保序）。
// limit = 内联预算：按文档顺序尽量填满，装不下的如实报成「未内联 N 条 / M 字符」，
// 绝不出现「只保留半句」的第三种状态。全文扫描请显式传 Infinity（调用方要知道
// 「这篇笔记到底有没有数值」，不能只看到预算内那几条就说没有）。
//
// 同形折叠（沿用 T1 的 head+_tally 做法）：逐袋明细这种「只差数字」的表格行，
// 每个形状只留前 REPEAT_HEAD 条，其余计入 folded。不折叠的话，实测 8.5K 字符的笔记里
// 14 条表格行会先把预算吃光，把 RMSE=214.5699±25.7094 这种唯一的结论句挤到全文里去。
export function extractKeyLines(body, limit = LONG_SENTENCE) {
  const seen = new Set();
  const matched = [];
  for (const unit of toUnits(body)) {
    if (/^#{1,6}\s/.test(unit)) continue; // 标题行进 outline 就够了，别在数值句里重复一遍
    const numeric = isNumeric(unit);
    const claim = CLAIM_HINT.test(unit);
    if (!numeric && !claim) continue;
    if (seen.has(unit)) continue;
    seen.add(unit);
    matched.push({
      text: unit,
      kind: numeric && claim ? "数值+主张" : numeric ? "数值" : "主张",
      chars: unit.length,
      too_long: unit.length > LONG_SENTENCE,
      template: unit.replace(/\d+(?:\.\d+)?/g, "#"),
    });
  }
  const byTemplate = new Map();
  for (const m of matched) {
    const n = (byTemplate.get(m.template) || 0) + 1;
    byTemplate.set(m.template, n);
    m.repeat_ordinal = n;
    m.folded = n > REPEAT_HEAD;
  }
  // 按文档顺序吃预算；单句 >LONG_SENTENCE 和同形折剩下的都不内联
  let left = limit;
  const inline = [];
  for (const m of matched) {
    if (m.too_long || m.folded) continue;
    if (m.chars + 4 > left) break; // 装不下了就停在这里：保持「前缀全有」而不是「挑着有」
    inline.push(m);
    left -= m.chars + 4;
  }
  const inlined = new Set(inline);
  const long = matched.filter((m) => m.too_long);
  const folded = matched.filter((m) => m.folded && !m.too_long);
  const deferred = matched.filter((m) => !inlined.has(m) && !m.too_long && !m.folded);
  const chars = (arr) => arr.reduce((n, x) => n + x.chars, 0);
  return {
    matched,
    inline,
    deferred,
    long,
    folded,
    count: matched.length,
    total_chars: chars(matched),
    inline_chars: chars(inline) + inline.length * 4,
    deferred_chars: chars(deferred),
    folded_chars: chars(folded),
  };
}

// 在 limit 内找一个安全收尾点：句子边界 > 空白边界 > null（宁可不内联这段头）
function clipAtBoundary(text, limit) {
  if (text.length <= limit) return { clipped: text, complete: true };
  const window = text.slice(0, limit);
  let idx = -1;
  for (let i = window.length - 1; i >= 0; i--) {
    if (SENTENCE_TERMINATORS.includes(window[i]) && window[i] !== "\n") { idx = i; break; }
  }
  if (idx >= Math.floor(limit * 0.4)) return { clipped: window.slice(0, idx + 1), complete: false };
  const sp = window.lastIndexOf(" ");
  const tab = window.lastIndexOf("\t");
  const cut = Math.max(sp, tab);
  if (cut >= Math.floor(limit * 0.4)) return { clipped: window.slice(0, cut), complete: false };
  return null; // 没有安全边界，就别切——交给全文路径
}

export function buildNotesDigest(md, opts = {}) {
  const inlineMax = opts.inlineMax ?? 4000;   // 短于这个长度的笔记整篇原样内联（和旧截断同级，零损失）
  const budget = opts.budget ?? 2400;         // 摘要模式下内联文本总预算（不含 JSON 信封）
  const sectionHead = opts.sectionHead ?? 200; // 每段散文头最多这么多字符
  const keyBudget = opts.keyBudget ?? Math.round(budget * 0.7); // 数值句的预算份额

  const { body } = stripFrontMatter(md);
  const full = body.trim();

  // 0) 能整篇装下就整篇装下。摘要只在「旧代码会开始切正文」之后才登场：
  //    实测一份 2,363 字符的真实规模笔记，做摘要后体积只降 14.2%，却把 8/10 条核心数值句挤出内联，
  //    比旧截断更亏。省不出信息量的压缩等于自残。
  if (full.length > 0 && full.length <= inlineMax) {
    return {
      mode: "full_verbatim",
      source_chars: full.length,
      key_lines_total: extractKeyLines(body, Infinity).count,
      text: full,
    };
  }

  const sections = splitSections(body);
  const keys = extractKeyLines(body, keyBudget);

  const digest = {
    mode: "digest",
    source_chars: full.length,
    sections: sections.length,
    outline: [],
    key_lines: keys.inline.map((k) => `${k.kind}｜${k.text}`),
    key_lines_status:
      keys.count === 0
        ? "none"
        : keys.deferred.length === 0 && keys.long.length === 0
          ? keys.folded.length
            ? "inline_with_folds" // 唯一句全在，只差数字的同形行被折成计数：引用汇总值够，逐袋核对要读原文
            : "inline"
          : keys.inline.length === 0
            ? "read_full_text"
            : "partial_read_full_text",
    key_lines_total: keys.count,
    key_lines_uninlined: keys.deferred.length,
    key_lines_folded: keys.folded.length,
    long_lines_uninlined: keys.long.length,
  };
  if (keys.deferred.length) digest.key_lines_uninlined_chars = keys.deferred_chars;
  if (keys.folded.length)
    digest.key_lines_folded_hint = `同形行折叠 ${keys.folded.length} 条（每个形状只留前 ${REPEAT_HEAD} 条，其余只差数字），逐条见全文`;
  if (keys.long.length)
    digest.long_lines_hint = keys.long.map((k) => `${k.kind}｜${k.text.slice(0, 60)}…（整句 ${k.chars} 字符，读原文）`);

  // 数值句按文档顺序吃预算（上面已取好前缀）；这里把它们的开销记进 used，剩下的给段头
  let used = keys.inline_chars;

  // 剩余预算给散文段头；不够就只留目录（outline 仍完整，等于没丢结构）
  let headDropped = 0;
  for (const s of sections) {
    const label = { level: s.level, heading: s.heading || "(前言)", chars: s.chars };
    const body0 = s.text.replace(/^#{1,6}\s+.*?\n?/, "").trim();
    const remaining = budget - used;
    if (remaining >= 60 && body0) {
      const c = clipAtBoundary(body0, Math.min(sectionHead, remaining));
      if (c) {
        label.head = c.clipped + (c.complete ? "" : " …");
        used += label.head.length + 40;
      } else {
        // 找不到安全收尾点：宁可只给目录，也不在数字中间切一刀
        label.head = null;
        label.head_omitted = "no_safe_boundary";
        headDropped++;
      }
    } else if (body0) {
      label.head = null;
      label.head_omitted = "budget";
      headDropped++;
    }
    digest.outline.push(label);
  }
  if (headDropped) digest.sections_without_head = headDropped;
  digest.inline_chars = used;
  return digest;
}
