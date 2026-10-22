// 格物 Web · 共享种子数据（同时被前端代理与构建读取）
// 7 个 Agent 与 7 阶段科研闭环。颜色取自设计文档的 accent/brand 调色板。

export const AGENTS = [
  { id: "gewu-director",    name: "主编",   role: "总协调",      color: "#185FA5", desc: "拆解研究目标、调度子智能体，跑完科研全生命周期。" },
  { id: "gewu-ideation",    name: "探员",   role: "定方向·读论文", color: "#0F6E56", desc: "调研文献、寻找 idea、确立研究课题。" },
  { id: "gewu-reproduction", name: "复现员", role: "复现",        color: "#534AB7", desc: "复现实验与代码，验证基线方法。" },
  { id: "gewu-improver",    name: "改进员", role: "改进·梳理",    color: "#C2631F", desc: "改进方法、梳理归因与消融实验。" },
  { id: "gewu-writer",      name: "写手",   role: "写论文",      color: "#B23A6B", desc: "撰写论文各章节与图表说明。" },
  { id: "gewu-publication", name: "发表官", role: "发表追踪",    color: "#2E7D9A", desc: "选刊、投稿、追踪审稿与引用。" },
  { id: "gewu-distillation", name: "沉淀师", role: "沉淀",        color: "#5A6B2E", desc: "把方法固化为可复用 Skill 与长周期记忆。" },
];

// status: done=已完成 / active=进行中 / todo=未开始
export const STAGES = [
  { id: "define",     name: "定方向",   status: "done",   agent: "gewu-ideation",    desc: "确定研究问题与课题边界。" },
  { id: "literature", name: "读论文",   status: "done",   agent: "gewu-ideation",    desc: "调研文献、寻找 idea 与方法基线。" },
  { id: "reproduce",  name: "复现",     status: "active", agent: "gewu-reproduction", desc: "复现基线实验与代码。" },
  { id: "improve",    name: "改进",     status: "todo",   agent: "gewu-improver",    desc: "改进方法、做消融与归因。" },
  { id: "write",      name: "写论文",   status: "todo",   agent: "gewu-writer",      desc: "撰写论文与图表说明。" },
  { id: "publish",    name: "发表追踪", status: "todo",   agent: "gewu-publication", desc: "选刊投稿与引用追踪。" },
  { id: "distill",    name: "沉淀",     status: "todo",   agent: "gewu-distillation", desc: "沉淀为可复用能力（复利）。" },
];

export const MODELS = [
  { id: "intern-s2",             name: "Intern-S2 (397B)" },
  { id: "intern-s1-pro",         name: "Intern-S1-Pro" },
  { id: "intern-s1",             name: "Intern-S1" },
  { id: "internvl3.5-241b-a28b", name: "InternVL3.5" },
];

export const RESEARCH_TOPIC = "LIBS 煤热值预测（参考实现）";
