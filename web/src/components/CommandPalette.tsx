// ⌘K command palette — jump to ticker / brief / page (PLAN.md §13.1).
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { endpoints } from "../lib/api";
import { IconSearch } from "./icons";

const PAGES = [
  ["Today", "/"], ["Markets", "/markets"], ["Signals", "/signals"], ["Macro", "/macro"],
  ["Filings", "/filings"], ["Briefs", "/briefs"], ["Conviction", "/conviction"],
  ["Journal", "/journal"], ["System", "/system"], ["Design", "/design"],
];

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const nav = useNavigate();
  const { data } = useQuery({ queryKey: ["cmd-markets"], queryFn: endpoints.markets, staleTime: 60000 });

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen((o) => !o); }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  const results = useMemo(() => {
    const ql = q.toLowerCase();
    const pages = PAGES.filter(([n]) => n.toLowerCase().includes(ql)).map(([n, p]) => ({ label: n, sub: "Page", to: p }));
    const tickers = (data?.instruments || [])
      .filter((i) => i.ticker.toLowerCase().includes(ql))
      .slice(0, 8)
      .map((i) => ({ label: i.ticker, sub: `${i.tier} · $${i.price ?? "—"}`, to: `/markets/${i.ticker}` }));
    return [...tickers, ...pages].slice(0, 12);
  }, [q, data]);

  if (!open) return null;
  return (
    <div onClick={() => setOpen(false)} style={{
      position: "fixed", inset: 0, zIndex: 100, background: "rgba(0,0,0,0.3)",
      display: "flex", alignItems: "flex-start", justifyContent: "center", paddingTop: "14vh",
    }}>
      <div className="card material" onClick={(e) => e.stopPropagation()} style={{ width: "min(560px, 92vw)", padding: 0, borderRadius: 14, overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "14px 16px", borderBottom: "var(--hairline) solid var(--separator)" }}>
          <IconSearch />
          <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Jump to ticker, brief, or page…"
            style={{ border: 0, background: "transparent", outline: "none", flex: 1, fontSize: 17, color: "var(--label)" }} />
          <span className="badge badge-p2">ESC</span>
        </div>
        <div style={{ maxHeight: 360, overflowY: "auto" }}>
          {results.map((r, i) => (
            <div key={i} className="sidebar-item" style={{ borderRadius: 0, padding: "10px 16px" }}
              onClick={() => { nav(r.to); setOpen(false); setQ(""); }}>
              <span className="headline" style={{ flex: 1 }}>{r.label}</span>
              <span className="footnote sec-label">{r.sub}</span>
            </div>
          ))}
          {!results.length && <div className="footnote sec-label" style={{ padding: 20, textAlign: "center" }}>No matches</div>}
        </div>
      </div>
    </div>
  );
}
