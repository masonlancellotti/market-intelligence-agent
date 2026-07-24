import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { endpoints } from "../lib/api";
import { Card, StatTile, Loading } from "../components/ui";
import { BriefMarkdown } from "../components/BriefMarkdown";
import { fmtDate } from "../lib/format";

export default function Journal() {
  const { data, isLoading } = useQuery({ queryKey: ["journal"], queryFn: endpoints.journal });
  const cal = data?.calibration;

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <header>
        <h1 className="large-title">Journal</h1>
        <div className="subhead sec-label">The system grades you, not just the market.</div>
      </header>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12 }}>
        <StatTile label="Predictions resolved" value={<span className="tnum">{cal?.n ?? 0}</span>} />
        <StatTile label="Mean Brier" value={<span className="tnum">{cal?.mean_brier ?? "—"}</span>} sub="lower is better" />
        <StatTile label="Hit rate" value={<span className="tnum">{cal?.hit_rate != null ? `${Math.round(cal.hit_rate * 100)}%` : "—"}</span>} />
      </div>

      <Card title="Calibration curve" action={<span className="footnote sec-label">predicted vs realized</span>}>
        {cal && cal.calibration.length ? <CalibrationChart data={cal.calibration} /> :
          <div className="footnote sec-label" style={{ padding: 16 }}>Resolve predictions to plot calibration.</div>}
      </Card>

      <Card title="Decision log">
        {isLoading ? <Loading rows={6} /> : (data?.entries || []).map((j) => (
          <div key={j.id} className="hairline" style={{ padding: "10px 0", display: "flex", gap: 12 }}>
            <div style={{ width: 120, flex: "none" }}>
              <div className="caption sec-label">{fmtDate(j.ts)}</div>
              <span className="badge badge-p2">{j.kind}</span>
              {j.ticker && <Link to={`/markets/${j.ticker}`} className="footnote accent" style={{ display: "block", marginTop: 4 }}>{j.ticker}</Link>}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}><BriefMarkdown markdown={j.markdown} /></div>
          </div>
        ))}
        {!isLoading && !(data?.entries || []).length && <div className="footnote sec-label" style={{ padding: 12 }}>No journal entries yet.</div>}
      </Card>
    </div>
  );
}

function CalibrationChart({ data }: { data: { bucket: string; predicted: number; realized: number; n: number }[] }) {
  const W = 320, H = 240, pad = 32;
  const sx = (v: number) => pad + v * (W - 2 * pad);
  const sy = (v: number) => H - pad - v * (H - 2 * pad);
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ maxWidth: 360 }}>
      {/* perfect-calibration diagonal */}
      <line x1={sx(0)} y1={sy(0)} x2={sx(1)} y2={sy(1)} stroke="var(--separator)" strokeDasharray="4 4" />
      {[0, 0.5, 1].map((t) => (
        <g key={t}>
          <text x={sx(t)} y={H - 10} textAnchor="middle" fontSize="10" fill="var(--tertiaryLabel)">{t * 100}%</text>
          <text x={10} y={sy(t) + 3} fontSize="10" fill="var(--tertiaryLabel)">{t * 100}%</text>
        </g>
      ))}
      <polyline fill="none" stroke="var(--blue)" strokeWidth="2"
        points={data.map((d) => `${sx(d.predicted)},${sy(d.realized)}`).join(" ")} />
      {data.map((d, i) => (
        <circle key={i} cx={sx(d.predicted)} cy={sy(d.realized)} r={3 + Math.min(d.n, 6)} fill="var(--blue)" fillOpacity="0.7">
          <title>{d.bucket}: predicted {Math.round(d.predicted * 100)}%, realized {Math.round(d.realized * 100)}% (n={d.n})</title>
        </circle>
      ))}
    </svg>
  );
}
