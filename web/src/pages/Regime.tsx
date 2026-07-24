import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { endpoints } from "../lib/api";
import type { ForwardReturns } from "../lib/api";
import { Card, StatTile, Segmented, Loading, Info, RetroPill } from "../components/ui";
import { RegimeBackdrop, RegimeScoreLine, ForwardReturnBars, BUCKETS, bucketColor } from "../components/labcharts";

// Month-year from a YYYY-MM-DD string, TZ-safe (no Date parsing).
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const ym = (d?: string) => (d ? `${MONTHS[+d.slice(5, 7) - 1]} ${d.slice(0, 4)}` : "—");
const fmtSigned = (v: number | null | undefined) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v}%`);

export default function Regime() {
  const hist = useQuery({ queryKey: ["regime-backfill"], queryFn: endpoints.regimeBackfill });
  const fwd = useQuery({ queryKey: ["regime-forward"], queryFn: endpoints.regimeForward });
  const [horizon, setHorizon] = useState<"5 days" | "1 month">("1 month");
  const hkey = horizon === "5 days" ? "h5" : "h20";

  const days = hist.data?.history || [];
  const last = days[days.length - 1];
  const counts = BUCKETS.map((b) => ({ b, n: days.filter((d) => d.bucket === b).length }));

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <header style={{ display: "flex", alignItems: "start", justifyContent: "space-between", flexWrap: "wrap", gap: 10 }}>
        <div style={{ maxWidth: "60ch" }}>
          <h1 className="large-title" style={{ textWrap: "balance" }}>Risk regime</h1>
          <div className="subhead sec-label" style={{ textWrap: "pretty", marginTop: 2 }}>
            One 0–100 gauge of how much risk the market is rewarding — blended from volatility, how many stocks
            are participating, credit conditions, and the dollar. <strong style={{ color: "var(--label)" }}>Higher = calmer,
            risk-seeking markets; lower = stressed, defensive markets.</strong> Recomputed for every trading day of the last two years.
          </div>
        </div>
        <RetroPill />
      </header>

      {hist.isError ? (
        <Card><Err onRetry={() => hist.refetch()} what="the regime history" /></Card>
      ) : hist.isLoading ? (
        <Card><Loading rows={6} /></Card>
      ) : !days.length ? (
        <Card><Empty /></Card>
      ) : (
        <>
          <Takeaway days={days} counts={counts} last={last} fwd={fwd.data} />

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(158px, 1fr))", gap: 12 }}>
            <StatTile label="Regime now" value={last?.score?.toFixed(0) ?? "—"}
              sub={<span style={{ color: bucketColor(last?.bucket || "") }}>● {last?.bucket}</span>} />
            <Tile label="History shown" value={`${days.length}`} sub={`trading days · ${ym(days[0]?.date)} → ${ym(last?.date)}`}
              info="Every market day over roughly the last two years, each scored independently." />
            {counts.map((c) => (
              <Tile key={c.b} label={`${c.b} days`} value={`${Math.round((c.n / days.length) * 100)}%`} sub={`${c.n} of ${days.length}`}
                info={
                  c.b === "Risk-On" ? "Calm, risk-seeking market (score ≥ 65)."
                  : c.b === "Risk-Off" ? "Stressed, defensive market (score ≤ 35)."
                  : "In-between — no strong risk signal (score 35–65)."
                } />
            ))}
          </div>

          <Card title="The S&P 500, coloured by risk regime">
            <p className="footnote sec-label" style={{ marginTop: -4, marginBottom: 12, textWrap: "pretty" }}>
              The white line is the S&P 500 (ticker SPY). The background is tinted by the regime that day —
              green for calm stretches, orange for high-stress ones. Hover for any day's exact reading.
            </p>
            <RegimeBackdrop days={days} />
            <Legend />
          </Card>

          <Card title="The regime score over time">
            <p className="footnote sec-label" style={{ marginTop: -4, marginBottom: 12, textWrap: "pretty" }}>
              The same 0–100 gauge as a line. Above the top dashed line (65) the market is risk-on; below the
              bottom line (35) it's risk-off; the band between is neutral.
            </p>
            <RegimeScoreLine days={days} />
          </Card>

          <Card title="What the market did next, by regime"
            action={<Segmented options={["5 days", "1 month"]} value={horizon} onChange={(v) => setHorizon(v as any)} />}>
            <p className="footnote sec-label" style={{ marginTop: -4, marginBottom: 12, textWrap: "pretty" }}>
              For each regime, how the S&P 500 actually moved over the following {horizon}, across every matching day in
              history. Bars show the <strong style={{ color: "var(--label)" }}>average</strong> move; the thin line is the
              middle-half range (the 25th to 75th percentile of outcomes).
            </p>
            {fwd.isLoading ? <Loading rows={3} /> : fwd.isError ? (
              <Err onRetry={() => fwd.refetch()} what="forward returns" />
            ) : fwd.data ? (
              <>
                <ForwardReturnBars by={fwd.data.by_bucket} horizon={hkey} />
                <table className="lab-table" style={{ marginTop: 14 }}>
                  <thead>
                    <tr>
                      <th>Regime</th>
                      <th>Days<Info label="Days" text="How many historical days fell in this regime." /></th>
                      <th>Average<Info label="Average" text="Mean S&P 500 move over the following window." /></th>
                      <th>Typical<Info label="Typical" text="Median move — half of outcomes were bigger, half smaller." /></th>
                      <th>Worst 25%<Info label="Worst quarter" text="25th percentile: a quarter of outcomes were worse than this." /></th>
                      <th>Best 25%<Info label="Best quarter" text="75th percentile: a quarter of outcomes were better than this." /></th>
                      <th>% up<Info label="Share positive" text="How often the market was simply higher after this window." /></th>
                    </tr>
                  </thead>
                  <tbody>
                    {BUCKETS.map((b) => {
                      const d = fwd.data!.by_bucket[b]?.[hkey];
                      return (
                        <tr key={b}>
                          <td><span style={{ color: bucketColor(b) }}>●</span> {b}</td>
                          <td>{d?.n ?? 0}</td>
                          <td>{fmtSigned(d?.mean)}</td>
                          <td>{fmtSigned(d?.median)}</td>
                          <td>{fmtSigned(d?.p25)}</td>
                          <td>{fmtSigned(d?.p75)}</td>
                          <td>{d?.pct_positive != null ? `${d.pct_positive}%` : "—"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                <p className="caption sec-label" style={{ marginTop: 12, lineHeight: 1.5, textWrap: "pretty" }}>
                  This describes the past over a single two-year window — it is not a forecast, and past patterns need
                  not repeat.
                </p>
              </>
            ) : null}
          </Card>
        </>
      )}
    </div>
  );
}

// Lead with the takeaway: a plain-language sentence computed from the data.
function Takeaway({ days, counts, last, fwd }:
  { days: any[]; counts: { b: string; n: number }[]; last: any; fwd?: ForwardReturns }) {
  const dominant = [...counts].sort((a, b) => b.n - a.n)[0];
  const share = Math.round((dominant.n / days.length) * 100);
  const ro = fwd?.by_bucket?.["Risk-Off"]?.h20;
  const stress = ro && ro.n
    ? <> The striking pattern: after the {ro.n} most-stressed (Risk-Off) days, the S&P 500 was
        <strong> higher a month later {ro.pct_positive}% of the time</strong> ({ro.mean! >= 0 ? "+" : ""}{ro.mean}% on average) —
        historically, buying fear paid.</>
    : null;
  return (
    <div className="takeaway">
      <span className="mark" aria-hidden="true">✦</span>
      <div className="lede">
        The market is currently in a <strong style={{ color: bucketColor(last?.bucket || "") }}>{last?.bucket}</strong> regime
        ({last?.score?.toFixed(0)}/100). Over the past two years it was <strong>{dominant.b}</strong> most of the time
        ({share}% of days).{stress}
      </div>
    </div>
  );
}

function Tile({ label, value, sub, info }: { label: string; value: string; sub: string; info: string }) {
  return (
    <div className="card" style={{ minWidth: 0 }}>
      <div className="footnote sec-label" style={{ marginBottom: 6, display: "flex", alignItems: "center" }}>
        {label}<Info label={label} text={info} />
      </div>
      <div className="tnum title2" style={{ letterSpacing: "-0.01em" }}>{value}</div>
      <div className="caption sec-label" style={{ marginTop: 4 }}>{sub}</div>
    </div>
  );
}

function Legend() {
  return (
    <div style={{ display: "flex", gap: 16, marginTop: 12, flexWrap: "wrap" }}>
      {BUCKETS.map((b) => (
        <span key={b} className="caption sec-label legend-chip">
          <span className="legend-sw" style={{ background: bucketColor(b), opacity: 0.55 }} /> {b}
        </span>
      ))}
    </div>
  );
}

function Empty() {
  return (
    <div style={{ padding: "8px 0" }}>
      <div className="subhead">No two-year history yet.</div>
      <div className="footnote sec-label" style={{ marginTop: 6, textWrap: "pretty" }}>
        Build it with one command (no API keys needed):
      </div>
      <code className="lab-code" style={{ display: "inline-block", marginTop: 8 }}>python manage.py backfill-regime --years 2</code>
    </div>
  );
}

function Err({ onRetry, what }: { onRetry: () => void; what: string }) {
  return (
    <div style={{ padding: "12px 0" }}>
      <div className="subhead">Couldn't load {what}.</div>
      <div className="footnote sec-label" style={{ marginTop: 4 }}>The daemon may still be starting up.</div>
      <button className="segmented" style={{ marginTop: 10, padding: "6px 14px" }} onClick={onRetry}>Try again</button>
    </div>
  );
}
