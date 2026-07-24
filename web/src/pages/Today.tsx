import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { endpoints } from "../lib/api";
import { Card, Delta, Badge, Loading } from "../components/ui";
import { RegimeGauge } from "../components/RegimeGauge";
import { BriefMarkdown } from "../components/BriefMarkdown";
import { fmtPrice, fmtTime, ago } from "../lib/format";

const SNAPSHOT = ["SPY", "QQQ", "^TNX", "^VIX", "BTC-USD"];

export default function Today() {
  const markets = useQuery({ queryKey: ["markets"], queryFn: endpoints.markets });
  const signals = useQuery({ queryKey: ["signals"], queryFn: endpoints.signals });
  const brief = useQuery({ queryKey: ["latest-morning"], queryFn: () => endpoints.latestBrief("morning") });
  const macro = useQuery({ queryKey: ["macro"], queryFn: endpoints.macro });
  const regimeHist = useQuery({ queryKey: ["regime-hist"], queryFn: endpoints.regimeHistory });

  const bySym = Object.fromEntries((markets.data?.instruments || []).map((i) => [i.ticker, i]));
  const regime = signals.data?.regime;
  const alerts = signals.data?.alerts || [];
  const history = (regimeHist.data?.history || []).map((h) => h.score);

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <header>
        <h1 className="large-title">Today</h1>
        <div className="subhead sec-label">{new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}</div>
      </header>

      {/* Market snapshot strip */}
      <div className="xscroll">
        <div style={{ display: "flex", gap: 12, minWidth: "min-content" }}>
          {SNAPSHOT.map((sym) => {
            const q = bySym[sym];
            const label = sym === "^TNX" ? "US 10Y" : sym === "^VIX" ? "VIX" : sym.replace("-USD", "");
            return (
              <Link key={sym} to={`/markets/${sym}`} className="card" style={{ minWidth: 148, flex: 1 }}>
                <div className="footnote sec-label">{label}</div>
                <div className="tnum title3" style={{ marginTop: 4 }}>{fmtPrice(q?.price, sym === "^TNX" ? 2 : 2)}</div>
                <div style={{ marginTop: 6 }}><Delta pct={q?.change_pct} /></div>
              </Link>
            );
          })}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 2fr) minmax(260px, 1fr)", gap: 18 }} className="today-grid">
        {/* Brief hero */}
        <Card hero title={brief.data?.brief ? `${cap(brief.data.brief.kind)} Brief` : "Latest Brief"}
          action={brief.data?.brief && <Link to={`/briefs/${brief.data.brief.id}`} className="footnote accent">Open →</Link>}>
          {brief.isLoading ? <Loading rows={5} /> : brief.data?.brief ? (
            <div style={{ maxHeight: 520, overflow: "auto" }}>
              <BriefMarkdown markdown={truncate(brief.data.brief.markdown)} evidence={brief.data.brief.evidence} />
            </div>
          ) : <Empty text="No brief yet. It generates at 07:45 ET." />}
        </Card>

        <div style={{ display: "grid", gap: 18, alignContent: "start" }}>
          {/* Regime gauge */}
          <Card title="Regime">
            {signals.isLoading ? <Loading rows={4} /> :
              <RegimeGauge score={regime?.score ?? null} bucket={regime?.bucket || "—"} history={history} />}
          </Card>

          {/* Next calendar events */}
          <Card title="Next up">
            {(macro.data?.upcoming_events || []).slice(0, 3).map((e, i) => (
              <div key={i} className="hairline" style={{ padding: "8px 0", display: "flex", justifyContent: "space-between", gap: 8 }}>
                <div>
                  <div className="subhead">{e.name}</div>
                  <div className="caption sec-label">{fmtTime(e.scheduled_at)}</div>
                </div>
                {e.importance === "high" && <Badge kind="P1">HIGH</Badge>}
              </div>
            ))}
            {!(macro.data?.upcoming_events || []).length && <Empty text="No events loaded." />}
          </Card>

          {/* Unread alerts */}
          <Card title="Alerts" action={<Link to="/signals" className="footnote accent">All →</Link>}>
            {alerts.slice(0, 4).map((a, i) => (
              <div key={i} className="hairline" style={{ padding: "8px 0", display: "flex", gap: 8, alignItems: "start" }}>
                <Badge kind={a.priority}>{a.priority}</Badge>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="footnote" style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{a.body}</div>
                  <div className="caption sec-label">{ago(a.fired_at)}</div>
                </div>
              </div>
            ))}
            {!alerts.length && <Empty text="Quiet tape — no alerts. (A feature.)" />}
          </Card>
        </div>
      </div>
      <style>{`@media (max-width: 900px){ .today-grid{ grid-template-columns: 1fr !important; } }`}</style>
    </div>
  );
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const truncate = (md: string) => md.split("\n").slice(0, 40).join("\n");
const Empty = ({ text }: { text: string }) => <div className="footnote sec-label" style={{ padding: "12px 0" }}>{text}</div>;
