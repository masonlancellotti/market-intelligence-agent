import { useQuery } from "@tanstack/react-query";
import { endpoints } from "../lib/api";
import type { MacroResp } from "../lib/api";
import { Card, Badge, StatTile, Loading } from "../components/ui";
import { fmtNum, fmtCompact, fmtDate, fmtTime } from "../lib/format";

const SERIES_LABEL: Record<string, string> = {
  DGS2: "2Y Treasury", DGS10: "10Y Treasury", DGS30: "30Y Treasury",
  T10Y2Y: "10Y–2Y Spread", FEDFUNDS: "Fed Funds",
  CPIAUCSL: "CPI (Index)", UNRATE: "Unemployment", PAYEMS: "Nonfarm Payrolls",
};
const RATES = ["DGS2", "DGS10", "DGS30", "T10Y2Y", "FEDFUNDS"];
const MACRO_SERIES = ["CPIAUCSL", "UNRATE", "PAYEMS"];

const seriesValue = (v: number) => (Math.abs(v) >= 1000 ? fmtCompact(v) : fmtNum(v, 2));
const fngColor = (v: number) => (v >= 55 ? "var(--green)" : v <= 45 ? "var(--red)" : "var(--orange)");

function Gauge({ label, value, rating }: { label: string; value: number | null; rating: string }) {
  return (
    <div className="card" style={{ minWidth: 0 }}>
      <div className="footnote sec-label">{label}</div>
      <div className="tnum title1" style={{ marginTop: 4, color: value == null ? "var(--label)" : fngColor(value) }}>
        {value == null ? "—" : Math.round(value)}
      </div>
      <div className="caption sec-label" style={{ marginTop: 2 }}>{rating}</div>
    </div>
  );
}

export default function Macro() {
  const macroQ = useQuery({ queryKey: ["macro"], queryFn: endpoints.macro });
  const data = macroQ.data as MacroResp | undefined;
  const series = data?.series || {};
  const rateKeys = RATES.filter((k) => series[k]);
  const macroKeys = MACRO_SERIES.filter((k) => series[k]);
  const fedOdds = data?.fed_odds || [];
  const events = data?.upcoming_events || [];

  if (macroQ.isLoading) {
    return (
      <div style={{ display: "grid", gap: 18 }}>
        <header><h1 className="large-title">Macro</h1></header>
        <Card><Loading rows={8} /></Card>
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <header><h1 className="large-title">Macro</h1></header>

      <Card title="Rates">
        {rateKeys.length ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 12 }}>
            {rateKeys.map((k) => (
              <StatTile key={k} label={SERIES_LABEL[k] ?? k} value={seriesValue(series[k].value)} sub={fmtDate(series[k].date)} />
            ))}
          </div>
        ) : (
          <Empty text="No rate series loaded." />
        )}
      </Card>

      {macroKeys.length > 0 && (
        <Card title="Inflation & Labor">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 12 }}>
            {macroKeys.map((k) => (
              <StatTile key={k} label={SERIES_LABEL[k] ?? k} value={seriesValue(series[k].value)} sub={fmtDate(series[k].date)} />
            ))}
          </div>
        </Card>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 18 }}>
        <Card title="Fed odds">
          {fedOdds.length ? (
            <div style={{ display: "grid" }}>
              {fedOdds.map((o, i) => (
                <div key={i} className="hairline" style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "10px 0", alignItems: "center" }}>
                  <div style={{ minWidth: 0 }}>
                    <div className="subhead">{o.question}</div>
                    <div className="caption sec-label">{o.venue}</div>
                  </div>
                  <div className="tnum title3">{Math.round(o.yes_prob * 100)}%</div>
                </div>
              ))}
            </div>
          ) : (
            <Empty text="No Fed odds loaded." />
          )}
        </Card>

        <Card title="Sentiment">
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Gauge label="CNN Fear & Greed" value={data?.cnn_fng?.score ?? null} rating={data?.cnn_fng?.rating ?? "—"} />
            <Gauge label="Crypto Fear & Greed" value={data?.crypto_fng?.value ?? null} rating={data?.crypto_fng?.label ?? "—"} />
          </div>
        </Card>
      </div>

      <Card title="Economic calendar">
        {events.length ? (
          <div style={{ display: "grid" }}>
            {events.map((e, i) => (
              <div key={i} className="hairline" style={{ display: "flex", gap: 12, padding: "10px 0", alignItems: "flex-start" }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="subhead" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    {e.name}
                    {e.importance === "high" && <Badge kind="P1">HIGH</Badge>}
                  </div>
                  <div className="caption sec-label" style={{ marginTop: 2 }}>{fmtTime(e.scheduled_at)}</div>
                </div>
                <div className="footnote sec-label tnum" style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  {e.consensus != null && <div>cons {e.consensus}</div>}
                  {e.previous != null && <div>prev {e.previous}</div>}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <Empty text="No upcoming events loaded." />
        )}
      </Card>
    </div>
  );
}

const Empty = ({ text }: { text: string }) => (
  <div className="footnote sec-label" style={{ padding: "12px 0" }}>{text}</div>
);
