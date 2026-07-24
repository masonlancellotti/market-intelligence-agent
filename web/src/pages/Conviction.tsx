import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { endpoints, type Memo } from "../lib/api";
import { Card, Badge, Loading } from "../components/ui";
import { BriefMarkdown } from "../components/BriefMarkdown";
import { fmtDate } from "../lib/format";

const COLUMNS = [
  ["research", "Research"], ["staged", "Staged"], ["live", "Live"], ["closed", "Closed"],
] as const;

export default function Conviction() {
  const { data, isLoading } = useQuery({ queryKey: ["memos"], queryFn: () => endpoints.memos() });
  const [selected, setSelected] = useState<number | null>(null);
  const kanban = data?.kanban || {};

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <header>
        <h1 className="large-title">Conviction</h1>
        <div className="subhead sec-label">No position without a memo. The memo, not the mood, is what gets reviewed.</div>
      </header>

      {isLoading ? <Loading rows={4} /> : (
        <div className="xscroll">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(220px, 1fr))", gap: 14 }}>
            {COLUMNS.map(([key, label]) => (
              <div key={key}>
                <div className="footnote sec-label" style={{ marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                  {label} · {(kanban[key] || []).length}
                </div>
                <div style={{ display: "grid", gap: 10 }}>
                  {(kanban[key] || []).map((m) => <MemoCard key={m.id} memo={m} onClick={() => setSelected(m.id)} />)}
                  {!(kanban[key] || []).length && <div className="footnote ter-label" style={{ padding: 10 }}>—</div>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {selected != null && <MemoDetail id={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function ScoreRing({ score }: { score: number }) {
  const r = 20, c = 2 * Math.PI * r;
  const color = score >= 70 ? "var(--green)" : score >= 50 ? "var(--orange)" : "var(--red)";
  return (
    <svg width="52" height="52" viewBox="0 0 52 52">
      <circle cx="26" cy="26" r={r} fill="none" stroke="var(--fill)" strokeWidth="5" />
      <circle cx="26" cy="26" r={r} fill="none" stroke={color} strokeWidth="5" strokeLinecap="round"
        strokeDasharray={c} strokeDashoffset={c * (1 - score / 100)} transform="rotate(-90 26 26)" />
      <text x="26" y="30" textAnchor="middle" className="tnum" fontSize="15" fontWeight="700" fill="var(--label)">{score}</text>
    </svg>
  );
}

function MemoCard({ memo, onClick }: { memo: Memo; onClick: () => void }) {
  return (
    <div className="card" onClick={onClick} style={{ cursor: "pointer", padding: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span className="headline">{memo.ticker}</span>
        <Badge kind={memo.direction === "short" ? "P1" : "green"}>{memo.direction}</Badge>
      </div>
      <div className="footnote sec-label" style={{ margin: "6px 0", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
        {memo.thesis}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span className={`tnum caption ${(memo.gate_score ?? 0) >= 70 ? "up" : "down"}`}>Gate {memo.gate_score ?? "—"}/100</span>
      </div>
    </div>
  );
}

function MemoDetail({ id, onClose }: { id: number; onClose: () => void }) {
  const { data } = useQuery({ queryKey: ["memo", id], queryFn: () => endpoints.memo(id) });
  const m = data?.memo;
  const rt = typeof m?.redteam_verdict === "string" ? safeJson(m.redteam_verdict) : m?.redteam_verdict;
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 90, background: "rgba(0,0,0,0.35)", display: "flex", justifyContent: "flex-end" }}>
      <div className="material" onClick={(e) => e.stopPropagation()} style={{ width: "min(560px, 94vw)", height: "100%", overflowY: "auto", padding: 24, borderLeft: "var(--hairline) solid var(--separator)" }}>
        {!m ? <Loading rows={6} /> : (
          <div style={{ display: "grid", gap: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
              <div>
                <h2 className="title1">{m.ticker} <span className="sec-label title3">{m.direction}</span></h2>
                <Badge kind="blue">{m.status}</Badge>
              </div>
              {m.gate && <ScoreRing score={m.gate.score} />}
            </div>
            <Card title="Thesis"><p className="body">{m.thesis}</p></Card>

            {m.gate && (
              <Card title={`The Gate — ${m.gate.score}/100`}>
                {Object.entries(m.gate.breakdown).map(([k, b]: any) => (
                  <div key={k} className="hairline" style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", gap: 8 }}>
                    <span className="footnote" style={{ color: b.ok ? "var(--label)" : "var(--secondaryLabel)" }}>{b.ok ? "✓" : "○"} {b.label}</span>
                    <span className="tnum footnote">{b.points}/{b.max}</span>
                  </div>
                ))}
              </Card>
            )}

            {rt && (
              <Card title={`Red Team — ${rt.verdict}`}>
                {(rt.objections || []).map((o: any, i: number) => (
                  <div key={i} className="hairline" style={{ padding: "7px 0" }}>
                    <div className="footnote"><Badge kind={o.severity >= 4 ? "P0" : "P2"}>S{o.severity}</Badge> {o.objection}</div>
                  </div>
                ))}
                <div className="caption sec-label" style={{ marginTop: 8 }}>What would change my mind:</div>
                {(rt.what_would_change_my_mind || []).map((w: string, i: number) => <div key={i} className="footnote">• {w}</div>)}
              </Card>
            )}

            {!!(m.predictions || []).length && (
              <Card title="Predictions & Brier">
                {m.predictions!.map((p) => (
                  <div key={p.id} className="hairline" style={{ padding: "7px 0", display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <div className="footnote" style={{ flex: 1 }}>{p.claim}<span className="ter-label"> · by {p.horizon_date}</span></div>
                    <span className="tnum footnote">{Math.round(p.probability * 100)}%</span>
                    {p.resolution && <Badge kind={p.resolution === "true" ? "green" : "P0"}>{p.resolution}</Badge>}
                    {p.brier != null && <span className="tnum caption sec-label">B{p.brier}</span>}
                  </div>
                ))}
              </Card>
            )}

            {!!(m.journal || []).length && (
              <Card title="Journal">
                {m.journal!.map((j) => (
                  <div key={j.id} className="hairline" style={{ padding: "6px 0" }}>
                    <div className="caption sec-label">{fmtDate(j.ts)} · {j.kind}</div>
                    <BriefMarkdown markdown={j.markdown} />
                  </div>
                ))}
              </Card>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function safeJson(s: string) { try { return JSON.parse(s); } catch { return null; } }
