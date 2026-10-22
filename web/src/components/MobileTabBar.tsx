export type MobileTab = "chat" | "pipeline" | "tools" | "settings";

const TABS: { key: MobileTab; label: string; ico: string }[] = [
  { key: "chat", label: "对话", ico: "💬" },
  { key: "pipeline", label: "管线", ico: "🧭" },
  { key: "tools", label: "工具", ico: "🧰" },
  { key: "settings", label: "设置", ico: "⚙️" },
];

export function MobileTabBar({
  active,
  onChange,
}: {
  active: MobileTab;
  onChange: (t: MobileTab) => void;
}) {
  return (
    <nav className="tabbar" aria-label="主导航">
      {TABS.map((t) => (
        <button
          key={t.key}
          className={`tabbar__item ${active === t.key ? "tabbar__item--active" : ""}`}
          onClick={() => onChange(t.key)}
          aria-current={active === t.key}
        >
          <span className="ico">{t.ico}</span>
          {t.label}
        </button>
      ))}
    </nav>
  );
}
