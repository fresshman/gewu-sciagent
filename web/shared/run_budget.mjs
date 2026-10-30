// 长任务预算闸门：阈值判定收敛成一个可测试的状态机。
//
// 为什么单独一层（此前它是内联在 server.mjs 的 10 秒 setInterval 里）：
// ① 判定时刻错了。轨迹计数只在轮次结束时一次性到达（`sessions tail` 不流式，实测），
//    10 秒轮询读到的恒为 0，而收尾只需 ≤2 秒 —— 工具维度阈值结构上无法触发
//    （实测一轮 50 次调用、硬阈值 30，budget 全程 null）。所以判定必须能由
//    **事件到达的那一刻**驱动，而不是只有一个外部 tick。
// ② 「超阈值」有两种语义，必须分开，否则会把成功轮次追溯打成失败：
//      轮次仍在跑时越线 = exceeded，止损信号（网关轮次不支持外部中断，
//      OpenClaw 2026.10.5 实测；这里的含义是「别再续跑/别再进下一阶段」）；
//      轮次已收尾后才补上越线 = overrun，只记档，不回写 handoff、不改 status。

export function budgetFromEnv(env = process.env) {
  return {
    warnTools: Number(env.GEWU_RUN_BUDGET_WARN_TOOLS) || 20,
    hardTools: Number(env.GEWU_RUN_BUDGET_TOOLS) || 30,
    warnMs: (Number(env.GEWU_RUN_BUDGET_WARN_MINUTES) || 18) * 60_000,
    hardMs: (Number(env.GEWU_RUN_BUDGET_MINUTES) || 25) * 60_000,
    slowGapMs: Number(env.GEWU_RUN_SLOW_GAP_MS) || 120_000,
  };
}

export class BudgetGate {
  constructor(budget) {
    if (!budget) throw new Error("BudgetGate: budget 不能为空");
    this.budget = budget;
    this.warnFired = false;
    this.hardFired = false;
    this.overrun = null;
  }

  /**
   * @param {{toolCalls:number, elapsedMs:number, inFlight?:boolean}} obs
   *        inFlight=false 表示轮次已收尾（此时只可能记 overrun，不再打 exceeded）。
   * @returns {Array<{type:string, dimension:string, toolCalls:number, elapsedMs:number, exceeded?:boolean}>}
   *        需要执行的动作，按 warn → hard 顺序；没越线返回空数组。同一阈值只报一次。
   */
  observe(obs) {
    const b = this.budget;
    const toolCalls = Number(obs.toolCalls) || 0;
    const elapsedMs = Number(obs.elapsedMs) || 0;
    const inFlight = obs.inFlight !== false;
    const events = [];

    const warnDim = this.warnFired ? null
      : toolCalls >= b.warnTools ? "tools"
      : elapsedMs >= b.warnMs ? "wall" : null;
    if (warnDim && inFlight) {
      this.warnFired = true;
      events.push({ type: "budget.warn", dimension: warnDim, toolCalls, elapsedMs });
    }

    const hardDim = (this.hardFired || this.overrun) ? null
      : toolCalls >= b.hardTools ? "tools"
      : elapsedMs >= b.hardMs ? "wall" : null;
    if (hardDim) {
      if (inFlight) {
        this.hardFired = true;
        events.push({ type: "budget.hard", dimension: hardDim, toolCalls, elapsedMs, exceeded: true });
      } else {
        this.overrun = { dimension: hardDim, toolCalls, elapsedMs };
        events.push({ type: "budget.overrun", dimension: hardDim, toolCalls, elapsedMs, exceeded: false });
      }
    }
    return events;
  }

  /** 落进 run 记录 budget 字段的终态摘要。 */
  summary({ toolCalls, elapsedMs }) {
    return {
      exceeded: this.hardFired,
      overrun: this.overrun ? this.overrun.dimension : null,
      toolCalls: Number(toolCalls) || 0,
      elapsedMs: Number(elapsedMs) || 0,
      at: new Date().toISOString(),
    };
  }
}
