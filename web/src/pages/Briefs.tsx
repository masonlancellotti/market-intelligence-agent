import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { endpoints } from "../lib/api";
import type { BriefMeta } from "../lib/api";
import { Card, Badge, Loading, Segmented } from "../components/ui";
import { fmtDate, fmtNum } from "../lib/format";

const KINDS = ["All", "morning", "closing", "midday", "sunday", "event_flash"];
const KIND_BADGE: Record<string, string> = {
  morning: "blue", closing: "P2", midday: "green", sunday: "P1", event_flash: "P0",
};
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replace("_", " ");

export default function Briefs() {
  const [kind, setKind] = useState("All");
  const briefsQ = useQuery({
    queryKey: ["briefs", kind],
    queryFn: () => endpoints.briefs(kind === "All" ? "" : kind),
  });

  const briefs = briefsQ.data?.briefs || [];
  const groups = new Map<string, BriefMeta[]>();
  for (const b of briefs) {
    const key = b.for_date || "—";
    (groups.get(key) || groups.set(key, []).get(key)!).push(b);
  }
  const dates = Array.from(groups.keys()).sort((a, b) => (a < b ? 1 : -1));

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <h1 className="large-title">Briefs</h1>
        <Segmented options={KINDS} value={kind} onChange={setKind} />
      </header>

      {briefsQ.isLoading ? (
        <Card><Loading rows={6} /></Card>
      ) : !dates.length ? (
        <Card><Empty text="No briefs archived yet." /></Card>
      ) : (
        dates.map((date) => (
          <section key={date} style={{ display: "grid", gap: 10 }}>
            <h2 className="title3">{fmtDate(date)}</h2>
            <div className="card" style={{ padding: 0, overflow: "hidden" }}>
              {groups.get(date)!.map((b) => (
                <Link key={b.id} to={`/briefs/${b.id}`} className="hairline"
                  style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 16px" }}>
                  <Badge kind={KIND_BADGE[b.kind] ?? "blue"}>{cap(b.kind)}</Badge>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="subhead">{cap(b.kind)} brief</div>
                    <div className="caption sec-label tnum">{b.model}</div>
                  </div>
                  <span className="tnum footnote sec-label">${fmtNum(b.cost_usd, 3)}</span>
                  <span className="caption" style={{ color: b.delivered_at ? "var(--green)" : "var(--gray)", whiteSpace: "nowrap" }}>
                    ● {b.delivered_at ? "Delivered" : "Pending"}
                  </span>
                  <span className="footnote accent">Open →</span>
                </Link>
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  );
}

const Empty = ({ text }: { text: string }) => (
  <div className="footnote sec-label" style={{ padding: "12px 0" }}>{text}</div>
);
