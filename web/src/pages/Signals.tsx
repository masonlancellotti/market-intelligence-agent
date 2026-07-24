import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { endpoints } from "../lib/api";
import type { SignalsResp } from "../lib/api";
import { Card, Delta, Badge, StatTile, Loading } from "../components/ui";
import { RegimeGauge } from "../components/RegimeGauge";
import { fmtNum, ago, dirClass } from "../lib/format";

const COMPONENT_LABEL: Record<string, string> = {
  vix: "Volatility (VIX)", hy_oas: "Credit (HY OAS)", curve: "Yield Curve", dollar: "US Dollar",
  breadth: "Breadth", credit_rs: "Credit RS", fear_greed: "Fear & Greed", nfci: "Fin. Conditions",
};

const pctStr = (v: number | null | undefined) => (v == null ? "—" : `${fmtNum(v, 1)}%`);

function CompBar({ label, value }: { label: string; value: number }) {
  const color = value >= 65 ? "var(--green)" : value <= 35 ? "var(--red)" : "var(--orange)";
  const w = Math.max(0, Math.min(100, value));
  return (
    <div style={{ display: "grid", gap: 5 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
        <span className="footnote sec-label">{COMPONENT_LABEL[label] ?? label}</span>
        <span className="footnote tnum">{fmtNum(value, 0)}</span>
      </div>
      <div style={{ height: 6, borderRadius: 3, background: "var(--fill)" }}>
        <div style={{ width: `${w}%`, height: "100%", background: color, borderRadius: 3, transition: "width 500ms var(--ease-spring)" }} />
      </div>
    </div>
  );
}

export default function Signals() {
  const signalsQ = useQuery({ queryKey: ["signals"], queryFn: endpoints.signals });
  const regimeHistQ = useQuery({ queryKey: ["regime-hist"], queryFn: endpoints.regimeHistory });

  const data = signalsQ.data as SignalsResp | undefined;
  const regime = data?.regime;
  const breadth = data?.breadth;
  const alerts = data?.alerts || [];
  const gov = data?.noise_governor as { active?: boolean; at?: string; count?: number } | null | undefined;
  const history = (regimeHistQ.data?.history || []).map((h) => h.score);
  const components: Record<string, number> = regime?.components || {};
  const sectors = breadth?.sector_rs || [];
  const corr = breadth?.correlation_shifts || [];

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <h1 className="large-title">Signals</h1>
        {gov?.active && <Badge kind="P1">Noise governor active{gov.count != null ? ` · ${gov.count}` : ""}</Badge>}
      </header>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(240px, 1fr) minmax(0, 2fr)", gap: 18 }} className="sig-grid">
        <Card title="Regime">
          {signalsQ.isLoading ? (
            <Loading rows={5} />
          ) : (
            <RegimeGauge score={regime?.score ?? null} bucket={regime?.bucket || "—"} history={history} />
          )}
        </Card>
        <Card title="Regime components">
          {Object.keys(components).length ? (
            <div style={{ display: "grid", gap: 12 }}>
              {Object.entries(components).map(([k, v]) => <CompBar key={k} label={k} value={v} />)}
            </div>
          ) : (
            <Empty text="No component data." />
          )}
        </Card>
      </div>

      <Card title="Market internals">
        {breadth ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 12 }}>
            <StatTile label="% above 50DMA" value={pctStr(breadth.pct_above_50dma)} />
            <StatTile label="% above 200DMA" value={pctStr(breadth.pct_above_200dma)} />
            <StatTile label="Advancers" value={breadth.advancers ?? "—"} />
            <StatTile label="Decliners" value={breadth.decliners ?? "—"} />
            <StatTile label="Net New Highs" value={breadth.net_new_highs ?? "—"}
              sub={`${breadth.new_20d_highs ?? "—"} hi / ${breadth.new_20d_lows ?? "—"} lo`} />
          </div>
        ) : (
          <Empty text="Breadth not computed yet." />
        )}
      </Card>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 18 }}>
        <Card title="Sector relative strength">
          {sectors.length ? (
            <div className="xscroll">
              <table className="grid">
                <thead>
                  <tr><th>Sector</th><th className="num-cell">1M</th><th className="num-cell">3M</th></tr>
                </thead>
                <tbody>
                  {sectors.map((s) => (
                    <tr key={s.ticker}>
                      <td><Link to={`/markets/${s.ticker}`} style={{ fontWeight: 600 }}>{s.ticker}</Link></td>
                      <td className="num-cell"><Delta pct={s.ret_1m} /></td>
                      <td className="num-cell"><Delta pct={s.ret_3m} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty text="No sector data." />
          )}
        </Card>

        <Card title="Correlation shifts">
          {corr.length ? (
            <div className="xscroll">
              <table className="grid">
                <thead>
                  <tr><th>Pair</th><th className="num-cell">Now</th><th className="num-cell">Prev</th><th className="num-cell">Δ</th></tr>
                </thead>
                <tbody>
                  {corr.map((c, i) => (
                    <tr key={i}>
                      <td className="tnum">{c.pair.join(" · ")}</td>
                      <td className="num-cell">{fmtNum(c.corr_now, 2)}</td>
                      <td className="num-cell">{fmtNum(c.corr_prev, 2)}</td>
                      <td className={`num-cell ${dirClass(c.delta)}`}>{fmtNum(c.delta, 2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty text="No notable correlation shifts." />
          )}
        </Card>
      </div>

      <Card title="Alerts">
        {signalsQ.isLoading ? (
          <Loading rows={4} />
        ) : alerts.length ? (
          <div style={{ display: "grid" }}>
            {alerts.map((a, i) => (
              <div key={a.id ?? i} className="hairline" style={{ display: "flex", gap: 12, padding: "10px 0", alignItems: "flex-start" }}>
                <Badge kind={a.priority}>{a.priority}</Badge>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="subhead">{a.title}</div>
                  <div className="footnote sec-label">{a.body}</div>
                  <div className="caption sec-label" style={{ marginTop: 2 }}>
                    {a.ticker && <Link to={`/markets/${a.ticker}`} className="accent">{a.ticker}</Link>}
                    {a.ticker ? " · " : ""}{ago(a.fired_at)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <Empty text="Quiet tape — no alerts. (A feature.)" />
        )}
      </Card>

      <style>{`@media (max-width: 820px){ .sig-grid{ grid-template-columns: 1fr !important; } }`}</style>
    </div>
  );
}

const Empty = ({ text }: { text: string }) => (
  <div className="footnote sec-label" style={{ padding: "12px 0" }}>{text}</div>
);
