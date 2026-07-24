import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { endpoints } from "../lib/api";
import type { Quote } from "../lib/api";
import { Card, Delta, Loading, Segmented } from "../components/ui";
import { fmtPrice } from "../lib/format";

const TIER_ORDER = ["holding", "active", "monitor", "benchmark"];
const TIER_LABEL: Record<string, string> = {
  holding: "Holding", active: "Active", monitor: "Monitor", benchmark: "Benchmark", other: "Other",
};

export default function Markets() {
  const [filter, setFilter] = useState("All");
  const markets = useQuery({ queryKey: ["markets"], queryFn: endpoints.markets });

  const byTier = markets.data?.by_tier || {};
  const extra = Object.keys(byTier).filter((t) => !TIER_ORDER.includes(t));
  const tiers = [...TIER_ORDER, ...extra];
  const shown = filter === "All" ? tiers : tiers.filter((t) => t === filter);
  const anyRows = shown.some((t) => (byTier[t] || []).length);

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <header style={{ display: "flex", alignItems: "start", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div style={{ maxWidth: "58ch" }}>
          <h1 className="large-title" style={{ textWrap: "balance" }}>Markets</h1>
          <div className="subhead sec-label" style={{ textWrap: "pretty", marginTop: 2 }}>
            Every instrument the desk tracks, grouped by how closely it's watched — from
            <strong style={{ color: "var(--label)" }}> Holdings</strong> (owned) through
            <strong style={{ color: "var(--label)" }}> Benchmarks</strong> (market yardsticks). Tap any row for its chart.
          </div>
        </div>
        <Segmented options={["All", "holding", "active", "monitor", "benchmark"]} value={filter} onChange={setFilter} />
      </header>

      {markets.isLoading ? (
        <Card><Loading rows={8} /></Card>
      ) : !anyRows ? (
        <Card><Empty text="No instruments in this tier yet." /></Card>
      ) : (
        shown.map((tier) => {
          const rows = byTier[tier] || [];
          if (!rows.length) return null;
          return (
            <section key={tier} style={{ display: "grid", gap: 10 }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
                <h2 className="title3">{TIER_LABEL[tier] ?? tier}</h2>
                <span className="footnote sec-label tnum">{rows.length}</span>
              </div>
              <div className="card" style={{ padding: 0, overflow: "hidden" }}>
                <div className="xscroll">
                  <table className="grid">
                    <thead>
                      <tr>
                        <th>Ticker</th>
                        <th>Name</th>
                        <th className="num-cell">Price</th>
                        <th className="num-cell">Change</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((q: Quote) => (
                        <tr key={q.ticker}>
                          <td>
                            <Link to={`/markets/${q.ticker}`}
                              style={{ fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 6 }}>
                              {q.is_stale && (
                                <span title="Stale quote" style={{ color: "var(--orange)", fontSize: 9, lineHeight: 1 }}>●</span>
                              )}
                              {q.ticker}
                            </Link>
                          </td>
                          <td className="sec-label"
                            style={{ maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {q.name}
                          </td>
                          <td className="num-cell">{fmtPrice(q.price)}</td>
                          <td className="num-cell"><Delta pct={q.change_pct} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          );
        })
      )}
    </div>
  );
}

const Empty = ({ text }: { text: string }) => (
  <div className="footnote sec-label" style={{ padding: "12px 0" }}>{text}</div>
);
