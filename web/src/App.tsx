import { useEffect, useState, useCallback } from "react";
import { ThemeProvider } from "./theme/ThemeProvider";
import { useIsDesktop } from "./hooks/useMediaQuery";
import { getAgents, getStages, getModels, getHealth, sendChat } from "./api/client";
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

// 工具结果回填到同工具、仍在运行的步骤，避免重复显示
function mergeStep(prev: RunStep[], step: RunStep): RunStep[] {
  if (step.kind === "tool" && step.phase === "result") {
    for (let i = prev.length - 1; i >= 0; i--) {
      const s = prev[i];
      if (s.kind === "tool" && s.tool === step.tool && s.status === "running") {
        const copy = [...prev];
        copy[i] = { ...copy[i], status: step.status, result: step.result, endedTs: step.ts };
        return copy;
      }
    }
  }
  return [...prev, step];
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
    (text: string) => {
      if (!selectedAgent || isStreaming) return;
      // 续跑：复用上一轮 session-key 让 agent 承接上下文
      const key = pendingResumeKey ?? undefined;
      if (pendingResumeKey) setPendingResumeKey(null);

      const userMsg: ChatMessage = { id: uid(), role: "user", text, ts: Date.now() };
      const botId = uid();
      const botMsg: ChatMessage = {
        id: botId,
        role: "assistant",
        agentId: selectedAgent.id,
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

      sendChat(selectedAgent.id, text, {
        onStart: (_agent, rk) => setCurrentRunKey(rk),
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
            <PaperReader />
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
