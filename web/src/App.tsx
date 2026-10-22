import { useEffect, useState, useCallback } from "react";
import { ThemeProvider } from "./theme/ThemeProvider";
import { useIsDesktop } from "./hooks/useMediaQuery";
import { getAgents, getStages, getModels, getHealth, sendChat } from "./api/client";
import type { Agent, Stage, ModelOption, ChatMessage } from "./types";
import { TopBar } from "./components/TopBar";
import { PipelinePanel } from "./components/PipelinePanel";
import { ChatPanel } from "./components/ChatPanel";
import { RightPanel } from "./components/RightPanel";
import { MobileTabBar, type MobileTab } from "./components/MobileTabBar";
import { SettingsPanel } from "./components/SettingsPanel";

let msgSeq = 0;
const uid = () => `m${++msgSeq}`;

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
      const userMsg: ChatMessage = { id: uid(), role: "user", text, ts: Date.now() };
      const botId = uid();
      const botMsg: ChatMessage = {
        id: botId,
        role: "assistant",
        agentId: selectedAgent.id,
        text: "",
        ts: Date.now(),
        streaming: true,
      };
      setMessages((prev) => [...prev, userMsg, botMsg]);
      setIsStreaming(true);

      const finalize = () => {
        setMessages((prev) =>
          prev.map((x) => (x.id === botId ? { ...x, streaming: false } : x))
        );
        setIsStreaming(false);
      };

      sendChat(selectedAgent.id, text, {
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
        onDone: finalize,
      }).catch((e) => {
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
    [selectedAgent, isStreaming]
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
        />

        {isDesktop ? (
          <>
            <div className="col-left">
              <PipelinePanel stages={stages} agents={agents} />
            </div>
            <div className="col-center">
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
                <ChatPanel
                  stages={stages}
                  messages={messages}
                  agents={agents}
                  selectedAgent={selectedAgent ?? ({ id: "", name: "", role: "", color: "#888", desc: "" } as Agent)}
                  isStreaming={isStreaming}
                  onSend={handleSend}
                />
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
