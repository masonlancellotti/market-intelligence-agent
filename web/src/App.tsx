import { useEffect, useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { useSSE } from "./lib/sse";
import { CommandPalette } from "./components/CommandPalette";
import {
  IconBriefs, IconConviction, IconFilings, IconJournal, IconMacro, IconMarkets,
  IconMoon, IconSignals, IconSun, IconSystem, IconToday,
} from "./components/icons";
import Today from "./pages/Today";
import Markets from "./pages/Markets";
import MarketDetail from "./pages/MarketDetail";
import Signals from "./pages/Signals";
import Macro from "./pages/Macro";
import Filings from "./pages/Filings";
import Briefs from "./pages/Briefs";
import BriefDetail from "./pages/BriefDetail";
import Conviction from "./pages/Conviction";
import Journal from "./pages/Journal";
import System from "./pages/System";
import Design from "./pages/Design";

const NAV: [string, string, any][] = [
  ["/", "Today", IconToday], ["/markets", "Markets", IconMarkets], ["/signals", "Signals", IconSignals],
  ["/macro", "Macro", IconMacro], ["/filings", "Filings", IconFilings], ["/briefs", "Briefs", IconBriefs],
  ["/conviction", "Conviction", IconConviction], ["/journal", "Journal", IconJournal], ["/system", "System", IconSystem],
];

function useTheme(): [string, () => void] {
  const [theme, setTheme] = useState(() => localStorage.getItem("theme") || "auto");
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "auto") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);
  const toggle = () => setTheme((t) => (t === "dark" ? "light" : t === "light" ? "auto" : "dark"));
  return [theme, toggle];
}

export default function App() {
  const [theme, toggle] = useTheme();
  const { connected } = useSSE();
  const loc = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [loc.pathname]);

  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      {/* Sidebar (compact widths fall back to the bottom tab bar) */}
      <aside className="material sidebar-desktop" style={{
        width: 214, flex: "none", borderRight: "var(--hairline) solid var(--separator)",
        padding: "16px 12px", position: "sticky", top: 0, height: "100vh",
        display: "flex", flexDirection: "column", gap: 2,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 8px 14px" }}>
          <Glyph />
          <span className="title3">Meridian</span>
        </div>
        {NAV.map(([to, label, Icon]) => (
          <NavLink key={to} to={to} end={to === "/"}
            className={({ isActive }) => `sidebar-item ${isActive ? "active" : ""}`}>
            <Icon /> <span>{label}</span>
          </NavLink>
        ))}
        <div style={{ marginTop: "auto", display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px" }}>
          <button className="sidebar-item" onClick={toggle} style={{ padding: 6 }} title={`Theme: ${theme}`}>
            {theme === "dark" ? <IconMoon /> : <IconSun />}
          </button>
          <span className="footnote sec-label" title={connected ? "Live" : "Reconnecting"}>
            <span style={{ color: connected ? "var(--green)" : "var(--gray)" }}>●</span> {connected ? "Live" : "…"}
          </span>
        </div>
      </aside>

      <main style={{ flex: 1, minWidth: 0, padding: "22px clamp(16px, 3vw, 34px) 90px" }}>
        <Routes>
          <Route path="/" element={<Today />} />
          <Route path="/markets" element={<Markets />} />
          <Route path="/markets/:ticker" element={<MarketDetail />} />
          <Route path="/signals" element={<Signals />} />
          <Route path="/macro" element={<Macro />} />
          <Route path="/filings" element={<Filings />} />
          <Route path="/briefs" element={<Briefs />} />
          <Route path="/briefs/:id" element={<BriefDetail />} />
          <Route path="/conviction" element={<Conviction />} />
          <Route path="/journal" element={<Journal />} />
          <Route path="/system" element={<System />} />
          <Route path="/design" element={<Design />} />
        </Routes>
      </main>

      {/* Bottom tab bar (compact widths) */}
      <nav className="material tabbar" style={{
        position: "fixed", bottom: 0, left: 0, right: 0, zIndex: 40,
        borderTop: "var(--hairline) solid var(--separator)",
        display: "none", justifyContent: "space-around", padding: "8px 4px calc(8px + env(safe-area-inset-bottom))",
      }}>
        {NAV.slice(0, 5).map(([to, label, Icon]) => (
          <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => `sidebar-item ${isActive ? "active" : ""}`}
            style={{ flexDirection: "column", gap: 2, background: "transparent", minWidth: 56 }}>
            <Icon /> <span className="caption">{label}</span>
          </NavLink>
        ))}
      </nav>

      <CommandPalette />
      <style>{`
        @media (max-width: 720px) {
          .sidebar-desktop { display: none !important; }
          .tabbar { display: flex !important; }
        }
      `}</style>
    </div>
  );
}

function Glyph() {
  return (
    <svg width="26" height="26" viewBox="0 0 32 32">
      <rect width="32" height="32" rx="8" fill="var(--blue)" />
      <path d="M6 20c3-9 5-9 8 0s5 9 8 0" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
