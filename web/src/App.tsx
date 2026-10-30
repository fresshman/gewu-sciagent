import { useEffect, useState, useCallback } from "react";
import { ThemeProvider } from "./theme/ThemeProvider";
import { useIsDesktop } from "./hooks/useMediaQuery";
import { getAgents, getStages, getModels, getHealth, sendChat, getRun } from "./api/client";
import type { Agent, Stage, ModelOption, ChatMessage, RunStep, RunStatus } from "./types";
import { TopBar } from "./components/TopBar";
import { PipelinePanel } from "./components/PipelinePanel";
import { ChatPanel } from "./components/ChatPanel";
import { RightPanel } from "./components/RightPanel";
import { RunPanel } from "./components/RunPanel";
import { MobileTabBar, type MobileTab } from "./components/MobileTabBar";
import { SettingsPanel } from "./components/SettingsPanel";
import { PaperReader } from "./components/PaperReader";

let msgSeq = 0;
const uid = () => `m${++msgSeq}`;

// 同一次工具调用只占一行。优先按 toolCallId 定位，id 缺失时退回「同工具且仍在运行」。
function findToolSlot(prev: RunStep[], step: RunStep): number {
  if (step.callId) {
    for (let i = prev.length - 1; i >= 0; i--) {
      if (prev[i].kind === "tool" && prev[i].callId === step.callId) return i;
    }
    return -1;
  }
  for (let i = prev.length - 1; i >= 0; i--) {
    const s = prev[i];
    if (s.kind === "tool" && s.tool === step.tool && s.status === "running") return i;
  }
  return -1;
}

// 结果到达后服务端广播的是「已合并」的那一步（phase=call、status=ok/error），不再是新步骤。
// 若只认 phase=result，这条会被追加成新行，原行永远停在「运行中」。
function mergeStep(prev: RunStep[], step: RunStep): RunStep[] {
  if (step.kind === "tool" && (step.status === "ok" || step.status === "error")) {
    const idx = findToolSlot(prev, step);
    if (idx >= 0) {
      const copy = [...prev];
      copy[idx] = { ...copy[idx], ...step, startedTs: copy[idx].startedTs ?? copy[idx].ts };
      return copy;
    }
  }
  return [...prev, step];
}

// done 时回读的 run 记录是权威列表（服务端每步都落盘），只把本地独有的工具行补在末尾。
function reconcileSteps(server: RunStep[], local: RunStep[]): RunStep[] {
  if (!server.length) return local;
  const ids = new Set(server.map((s) => s.callId).filter(Boolean));
  const missing = local.filter((s) => s.kind === "tool" && s.callId && !ids.has(s.callId));
  return missing.length ? [...server, ...missing] : server;
}

function dispositionToStatus(d: string | undefined): RunStatus {
  const s = String(d || "").toLowerCase();
  if (s.includes("timeout")) return "timeout";
  if (s.includes("success")) return "success";
  if (s.includes("error") || s.includes("abort") || s === "") return "error";
  return "error";
}

export default function App() {
  const isDesktop = useIsDesktop();

  const [agents, setAgents] = useState<Agent[]>([]);
  const [stages, setStages] = useState<Stage[]>([]);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [topic, setTopic] = useState("格物科研工作台");
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [selectedModel, setSelectedModel] = useState("intern-s2");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [mobileTab, setMobileTab] = useState<MobileTab>("chat");
  const [gatewayReachable, setGatewayReachable] = useState<boolean | null>(null);
  // A3: 中间结果落盘 —— 实时步骤、当前运行 key、状态、续跑 key
  const [runSteps, setRunSteps] = useState<RunStep[]>([]);
  const [currentRunKey, setCurrentRunKey] = useState<string | null>(null);
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null);
  const [pendingResumeKey, setPendingResumeKey] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"chat" | "papers">("chat");

  useEffect(() => {
    (async () => {
      try {
        const [a, s, m, h] = await Promise.all([
          getAgents(),
          getStages(),
          getModels(),
          getHealth(),
        ]);
        setAgents(a.agents);
        setStages(s.stages);
        setModels(m.models);
        if (a.agents[0]) setSelectedAgent(a.agents[0]);
        setGatewayReachable(h.gateway.reachable);
      } catch (e) {
        console.error("初始化失败", e);
        setGatewayReachable(false);
      }
    })();
  }, []);

  const handleSend = useCallback(
    (text: string, agentIdOverride?: string) => {
      // 跨阶段衔接（送复现）会在切换 agent 前直接指定目标，不能等 selectedAgent 重渲染
      const agentId = agentIdOverride ?? selectedAgent?.id;
      if (!agentId || isStreaming) return;
      // 续跑：复用上一轮 session-key 让 agent 承接上下文
      const key = pendingResumeKey ?? undefined;
      let liveRunKey = key ?? "";
      if (pendingResumeKey) setPendingResumeKey(null);

      const userMsg: ChatMessage = { id: uid(), role: "user", text, ts: Date.now() };
      const botId = uid();
      const botMsg: ChatMessage = {
        id: botId,
        role: "assistant",
        agentId,
        text: "",
        ts: Date.now(),
        streaming: true,
        runKey: key,
      };
      setMessages((prev) => [...prev, userMsg, botMsg]);
      setIsStreaming(true);
      setRunSteps([]);
      setCurrentRunKey(null);
      setRunStatus("running");

      const finalize = () => {
        setMessages((prev) =>
          prev.map((x) => (x.id === botId ? { ...x, streaming: false } : x))
        );
        setIsStreaming(false);
      };

      sendChat(agentId, text, {
        onStart: (_agent, rk) => { liveRunKey = rk; setCurrentRunKey(rk); },
        onStep: (step) => {
          if (step.kind === "ended" && step.disposition) setRunStatus(dispositionToStatus(step.disposition));
          setRunSteps((prev) => mergeStep(prev, step));
        },
        onDelta: (t) =>
          setMessages((prev) =>
            prev.map((x) => (x.id === botId ? { ...x, text: x.text + t } : x))
          ),
        onError: (err) =>
          setMessages((prev) =>
            prev.map((x) =>
              x.id === botId
                ? { ...x, streaming: false, error: true, text: x.text + `\n\n⚠️ ${err}` }
                : x
            )
          ),
        onDone: (status) => {
          if (status) setRunStatus(status);
          finalize();
          // 步骤已改由网关 transcript_events 轮询生成，实时可见；done 后仍回读一次 run 记录，
          // 把 finalize 时补发的尾部步骤对齐进来（服务端记录为权威）。
          if (liveRunKey) {
            setTimeout(async () => {
              try {
                const rec = await getRun(liveRunKey);
                setRunSteps((prev) => reconcileSteps(rec.steps ?? [], prev));
              } catch {}
            }, 4000);
          }
        },
      }).catch((e) => {
        setRunStatus("error");
        setMessages((prev) =>
          prev.map((x) =>
            x.id === botId
              ? { ...x, streaming: false, error: true, text: x.text + `\n\n⚠️ 网络错误：${String(e)}` }
              : x
          )
        );
        setIsStreaming(false);
      });
    },
    [selectedAgent, isStreaming, pendingResumeKey]
  );

  const handleResume = useCallback((key: string) => {
    setPendingResumeKey(key);
    setCurrentRunKey(key);
    setRunSteps([]);
    setRunStatus(null);
  }, []);

  // 送复现：切到「对话」视图、选中复现员，并立即把指令发进 /api/chat 长任务通道
  const handleReproduce = useCallback(
    (instruction: string) => {
      const reproAgent = agents.find((a) => a.id === "gewu-reproduction");
      if (reproAgent) setSelectedAgent(reproAgent);
      setViewMode("chat");
      setMobileTab("chat");
      handleSend(instruction, "gewu-reproduction");
    },
    [agents, handleSend]
  );

  const gatewayHint =
    gatewayReachable === false
      ? "⚠️ 未连接到 OpenClaw Gateway，请先启动（openclaw gateway run --force）。"
      : "";

  return (
    <ThemeProvider>
      <div className="app">
        <TopBar
          topic={topic}
          agents={agents}
          selectedAgent={selectedAgent ?? ({ id: "", name: "…", role: "", color: "#888", desc: "" } as Agent)}
          onSelectAgent={setSelectedAgent}
          models={models}
          selectedModel={selectedModel}
          onSelectModel={setSelectedModel}
          viewMode={viewMode}
          onViewModeChange={setViewMode}
        />

        {viewMode === "papers" ? (
          <div className="paper-reader-full">
            <PaperReader onReproduce={handleReproduce} isStreaming={isStreaming} />
          </div>
        ) : isDesktop ? (
          <>
            <div className="col-left">
              <PipelinePanel stages={stages} agents={agents} />
            </div>
            <div className="col-center">
              <RunPanel
                runSteps={runSteps}
                runKey={currentRunKey}
                status={runStatus}
                onResume={handleResume}
                resumeKey={pendingResumeKey}
              />
              <ChatPanel
                stages={stages}
                messages={messages}
                agents={agents}
                selectedAgent={selectedAgent ?? ({ id: "", name: "", role: "", color: "#888", desc: "" } as Agent)}
                isStreaming={isStreaming}
                onSend={handleSend}
              />
            </div>
            <div className="col-right">
              <RightPanel variant="desktop" />
            </div>
          </>
        ) : (
          <>
            <main className="col-main">
              {gatewayHint && (
                <div className="composer__hint" style={{ padding: "var(--space-3) var(--space-4)" }}>
                  {gatewayHint}
                </div>
              )}
              {mobileTab === "chat" && (
                <>
                  <RunPanel
                    runSteps={runSteps}
                    runKey={currentRunKey}
                    status={runStatus}
                    onResume={handleResume}
                    resumeKey={pendingResumeKey}
                  />
                  <ChatPanel
                    stages={stages}
                    messages={messages}
                    agents={agents}
                    selectedAgent={selectedAgent ?? ({ id: "", name: "", role: "", color: "#888", desc: "" } as Agent)}
                    isStreaming={isStreaming}
                    onSend={handleSend}
                  />
                </>
              )}
              {mobileTab === "pipeline" && <PipelinePanel stages={stages} agents={agents} />}
              {mobileTab === "tools" && <RightPanel variant="mobile" />}
              {mobileTab === "settings" && (
                <SettingsPanel
                  agents={agents}
                  selectedAgent={selectedAgent ?? ({ id: "", name: "", role: "", color: "#888", desc: "" } as Agent)}
                  onSelectAgent={setSelectedAgent}
                  models={models}
                  selectedModel={selectedModel}
                  onSelectModel={setSelectedModel}
                />
              )}
            </main>
            <MobileTabBar active={mobileTab} onChange={setMobileTab} />
          </>
        )}
      </div>
    </ThemeProvider>
  );
}
