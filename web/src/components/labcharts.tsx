// V2 retrospective research charts — hand-rolled SVG in the Apple HIG token system.
// Regime buckets use status semantics (always paired with a text label, never colour-alone):
//   Risk-On → green, Neutral → gray, Risk-Off → orange (red reserved for live alerts).
import { useRef, useState } from "react";
import type { RegimeDay, Dist, ReliabilityPoint } from "../lib/api";
import { fmtPrice } from "../lib/format";

export const BUCKETS = ["Risk-On", "Neutral", "Risk-Off"] as const;
export const bucketColor = (b: string): string =>
  b === "Risk-On" ? "var(--green)" : b === "Risk-Off" ? "var(--orange)" : "var(--gray)";

const PAD = { l: 44, r: 14, t: 12, b: 22 };

function useHover() {
  const [i, setI] = useState<number | null>(null);
  return { i, setI };
}

// Contiguous same-bucket runs → background bands.
function bands(days: RegimeDay[]) {
  const out: { start: number; end: number; bucket: string }[] = [];
  let s = 0;
  for (let k = 1; k <= days.length; k++) {
    if (k === days.length || days[k].bucket !== days[s].bucket) {
      out.push({ start: s, end: k - 1, bucket: days[s].bucket });
      s = k;
    }
  }
  return out;
}

// SPY price line over a regime-shaded background — the signature chart.
export function RegimeBackdrop({ days, height = 300 }: { days: RegimeDay[]; height?: number }) {
  const W = 900,
    H = height;
  const wrap = useRef<HTMLDivElement>(null);
  const { i, setI } = useHover();
  const pts = days.filter((d) => d.spy_close != null);
  if (pts.length < 2) return null;
  const xs = (k: number) => PAD.l + (k / (days.length - 1)) * (W - PAD.l - PAD.r);
  const vals = days.map((d) => d.spy_close ?? NaN);
  const min = Math.min(...vals.filter((v) => !isNaN(v)));
  const max = Math.max(...vals.filter((v) => !isNaN(v)));
  const range = max - min || 1;
  const ys = (v: number) => PAD.t + (1 - (v - min) / range) * (H - PAD.t - PAD.b);
  const line = days
    .map((d, k) => (d.spy_close == null ? "" : `${k === 0 ? "M" : "L"}${xs(k).toFixed(1)},${ys(d.spy_close).toFixed(1)}`))
    .filter(Boolean)
    .join(" ")
    .replace(/^L/, "M");

  const onMove = (e: React.MouseEvent) => {
    const r = wrap.current!.getBoundingClientRect();
    const rel = ((e.clientX - r.left) / r.width) * W;
    const k = Math.round(((rel - PAD.l) / (W - PAD.l - PAD.r)) * (days.length - 1));
    setI(Math.max(0, Math.min(days.length - 1, k)));
  };
  const hov = i != null ? days[i] : null;

  return (
    <div ref={wrap} style={{ position: "relative" }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img"
        aria-label="SPY price with regime-shaded background" style={{ display: "block" }}
        onMouseMove={onMove} onMouseLeave={() => setI(null)}>
        {bands(days).map((b, k) => (
          <rect key={k} x={xs(b.start)} y={PAD.t} width={Math.max(1, xs(b.end) - xs(b.start))}
            height={H - PAD.t - PAD.b} fill={bucketColor(b.bucket)} opacity={0.1} />
        ))}
        {[0, 0.5, 1].map((f) => {
          const v = min + f * range;
          return (
            <g key={f}>
              <line x1={PAD.l} x2={W - PAD.r} y1={ys(v)} y2={ys(v)} stroke="var(--separator)"
                strokeWidth="0.5" strokeDasharray="2 3" />
              <text x={PAD.l - 6} y={ys(v) + 3} textAnchor="end" fontSize="10"
                fill="var(--tertiaryLabel)" fontFamily="var(--font-mono)">{fmtPrice(v, 0)}</text>
            </g>
          );
        })}
        <path d={line} fill="none" stroke="var(--label)" strokeWidth="1.6" strokeLinejoin="round" />
        {hov && hov.spy_close != null && (
          <g>
            <line x1={xs(i!)} x2={xs(i!)} y1={PAD.t} y2={H - PAD.b} stroke="var(--separator)" strokeWidth="1" />
            <circle cx={xs(i!)} cy={ys(hov.spy_close)} r="3.5" fill={bucketColor(hov.bucket)}
              stroke="var(--systemBackground)" strokeWidth="1.5" />
          </g>
        )}
      </svg>
      {hov && (
        <div className="chart-tip" style={{ left: `${(xs(i!) / W) * 100}%` }}>
          <div className="caption sec-label">{hov.date}</div>
          <div className="tnum footnote">SPY {fmtPrice(hov.spy_close, 2)}</div>
          <div className="caption" style={{ color: bucketColor(hov.bucket) }}>
            ● {hov.bucket} · {hov.score.toFixed(0)}
          </div>
        </div>
      )}
    </div>
  );
}

// Regime score 0–100 timeline with zone tints + threshold lines.
export function RegimeScoreLine({ days, height = 150 }: { days: RegimeDay[]; height?: number }) {
  const W = 900,
    H = height;
  const wrap = useRef<HTMLDivElement>(null);
  const { i, setI } = useHover();
  if (days.length < 2) return null;
  const xs = (k: number) => PAD.l + (k / (days.length - 1)) * (W - PAD.l - PAD.r);
  const ys = (v: number) => PAD.t + (1 - v / 100) * (H - PAD.t - PAD.b);
  const line = days.map((d, k) => `${k === 0 ? "M" : "L"}${xs(k).toFixed(1)},${ys(d.score).toFixed(1)}`).join(" ");
  const zones: [number, number, string][] = [
    [65, 100, "var(--green)"],
    [35, 65, "var(--gray)"],
    [0, 35, "var(--orange)"],
  ];
  const onMove = (e: React.MouseEvent) => {
    const r = wrap.current!.getBoundingClientRect();
    const rel = ((e.clientX - r.left) / r.width) * W;
    const k = Math.round(((rel - PAD.l) / (W - PAD.l - PAD.r)) * (days.length - 1));
    setI(Math.max(0, Math.min(days.length - 1, k)));
  };
  const hov = i != null ? days[i] : null;
  return (
    <div ref={wrap} style={{ position: "relative" }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Composite regime score over time"
        style={{ display: "block" }} onMouseMove={onMove} onMouseLeave={() => setI(null)}>
        {zones.map(([lo, hi, c], k) => (
          <rect key={k} x={PAD.l} y={ys(hi)} width={W - PAD.l - PAD.r} height={ys(lo) - ys(hi)} fill={c} opacity={0.07} />
        ))}
        {[35, 65].map((v) => (
          <line key={v} x1={PAD.l} x2={W - PAD.r} y1={ys(v)} y2={ys(v)} stroke="var(--separator)"
            strokeWidth="0.5" strokeDasharray="3 3" />
        ))}
        {[0, 50, 100].map((v) => (
          <text key={v} x={PAD.l - 6} y={ys(v) + 3} textAnchor="end" fontSize="10"
            fill="var(--tertiaryLabel)" fontFamily="var(--font-mono)">{v}</text>
        ))}
        <path d={line} fill="none" stroke="var(--blue)" strokeWidth="1.6" strokeLinejoin="round" />
        {hov && (
          <g>
            <line x1={xs(i!)} x2={xs(i!)} y1={PAD.t} y2={H - PAD.b} stroke="var(--separator)" strokeWidth="1" />
            <circle cx={xs(i!)} cy={ys(hov.score)} r="3.5" fill={bucketColor(hov.bucket)}
              stroke="var(--systemBackground)" strokeWidth="1.5" />
          </g>
        )}
      </svg>
      {hov && (
        <div className="chart-tip" style={{ left: `${(xs(i!) / W) * 100}%` }}>
          <div className="caption sec-label">{hov.date}</div>
          <div className="tnum footnote">Score {hov.score.toFixed(1)}</div>
          <div className="caption" style={{ color: bucketColor(hov.bucket) }}>● {hov.bucket}</div>
        </div>
      )}
    </div>
  );
}

// Reliability curve: predicted (x) vs realized (y), identity diagonal, points sized by n.
export function ReliabilityCurve({ points, height = 300, hue = "var(--blue)" }:
  { points: ReliabilityPoint[]; height?: number; hue?: string }) {
  const W = 340,
    H = height;
  const p = { l: 40, r: 16, t: 14, b: 32 };
  const xs = (v: number) => p.l + v * (W - p.l - p.r);
  const ys = (v: number) => p.t + (1 - v) * (H - p.t - p.b);
  const maxN = Math.max(1, ...points.map((d) => d.n));
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Reliability curve" style={{ display: "block" }}>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={xs(t)} x2={xs(t)} y1={p.t} y2={H - p.b} stroke="var(--separator)" strokeWidth="0.5" strokeDasharray="2 3" />
          <line x1={p.l} x2={W - p.r} y1={ys(t)} y2={ys(t)} stroke="var(--separator)" strokeWidth="0.5" strokeDasharray="2 3" />
          <text x={xs(t)} y={H - p.b + 14} textAnchor="middle" fontSize="10" fill="var(--tertiaryLabel)" fontFamily="var(--font-mono)">{t}</text>
          <text x={p.l - 6} y={ys(t) + 3} textAnchor="end" fontSize="10" fill="var(--tertiaryLabel)" fontFamily="var(--font-mono)">{t}</text>
        </g>
      ))}
      {/* perfect-calibration reference */}
      <line x1={xs(0)} y1={ys(0)} x2={xs(1)} y2={ys(1)} stroke="var(--separator)" strokeWidth="1.5" strokeDasharray="4 4" />
      <text x={xs(0.98)} y={ys(0.9)} textAnchor="end" fontSize="9.5" fill="var(--tertiaryLabel)" fontStyle="italic">perfect</text>
      {points.length > 1 && (
        <path d={points.map((d, k) => `${k === 0 ? "M" : "L"}${xs(d.predicted)},${ys(d.realized)}`).join(" ")}
          fill="none" stroke={hue} strokeWidth="1.6" opacity={0.5} />
      )}
      {points.map((d, k) => (
        <circle key={k} cx={xs(d.predicted)} cy={ys(d.realized)} r={4 + (d.n / maxN) * 7} fill={hue}
          fillOpacity={0.85} stroke="var(--systemBackground)" strokeWidth="1.5">
          <title>{`predicted ${(d.predicted * 100).toFixed(0)}% · realized ${(d.realized * 100).toFixed(0)}% · n=${d.n}`}</title>
        </circle>
      ))}
      <text x={(p.l + W - p.r) / 2} y={H - 4} textAnchor="middle" fontSize="10" fill="var(--secondaryLabel)">rule said this probability →</text>
      <text x={p.l - 30} y={p.t + 2} fontSize="10" fill="var(--secondaryLabel)">↑ actual</text>
    </svg>
  );
}

// Forward-return distribution by bucket — mean bar + p25–p75 whisker.
export function ForwardReturnBars({ by, horizon }:
  { by: Record<string, { h5: Dist; h20: Dist }>; horizon: "h5" | "h20" }) {
  const rows = BUCKETS.map((b) => ({ bucket: b, d: by[b]?.[horizon] }));
  const all = rows.flatMap((r) => (r.d?.n ? [r.d.p25 ?? 0, r.d.p75 ?? 0, r.d.mean ?? 0] : []));
  const lo = Math.min(-0.5, ...all),
    hi = Math.max(0.5, ...all);
  const span = hi - lo || 1;
  const W = 520,
    rowH = 46,
    H = rows.length * rowH + 16,
    left = 78;
  const x = (v: number) => left + ((v - lo) / span) * (W - left - 16);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`Forward return by regime bucket`} style={{ display: "block" }}>
      <line x1={x(0)} x2={x(0)} y1={8} y2={H - 8} stroke="var(--separator)" strokeWidth="1" />
      {rows.map((r, k) => {
        const y = 8 + k * rowH + rowH / 2;
        const d = r.d;
        if (!d?.n) return (
          <text key={k} x={left} y={y + 3} fontSize="11" fill="var(--tertiaryLabel)">{r.bucket}: no data</text>
        );
        return (
          <g key={k}>
            <text x={8} y={y - 4} fontSize="12" fill="var(--label)">{r.bucket}</text>
            <text x={8} y={y + 11} fontSize="10" fill="var(--tertiaryLabel)" fontFamily="var(--font-mono)">n={d.n}</text>
            <line x1={x(d.p25!)} x2={x(d.p75!)} y1={y} y2={y} stroke={bucketColor(r.bucket)} strokeWidth="2" opacity={0.4} />
            <rect x={Math.min(x(0), x(d.mean!))} y={y - 6} width={Math.max(2, Math.abs(x(d.mean!) - x(0)))} height={12}
              rx={3} fill={bucketColor(r.bucket)} opacity={0.85}>
              <title>{`${r.bucket}: mean ${d.mean}% · median ${d.median}% · ${d.pct_positive}% positive`}</title>
            </rect>
            <text x={x(d.mean!) + (d.mean! >= 0 ? 6 : -6)} y={y + 3} textAnchor={d.mean! >= 0 ? "start" : "end"}
              fontSize="11" fontFamily="var(--font-mono)" fill="var(--secondaryLabel)">{(d.mean ?? 0) >= 0 ? "+" : ""}{d.mean}%</text>
          </g>
        );
      })}
    </svg>
  );
}

function TipStyle() {
  return (
    <style>{`.chart-tip{position:absolute;top:2px;transform:translateX(-50%);pointer-events:none;
      background:var(--toolbar-bg);backdrop-filter:blur(var(--blur));border:var(--hairline) solid var(--separator);
      border-radius:8px;padding:5px 9px;white-space:nowrap;box-shadow:var(--card-shadow);z-index:5;}`}</style>
  );
}
