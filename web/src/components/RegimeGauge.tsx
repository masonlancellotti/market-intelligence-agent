// Master regime gauge — an arc 0..100 (PLAN.md §8.3/§13.1).
import { Sparkline } from "./ui";

const RADIUS = 78;
const START = -220; // degrees
const SWEEP = 260;

function polar(cx: number, cy: number, r: number, deg: number) {
  const a = (deg * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}
function arc(cx: number, cy: number, r: number, a0: number, a1: number) {
  const [x0, y0] = polar(cx, cy, r, a0);
  const [x1, y1] = polar(cx, cy, r, a1);
  const large = Math.abs(a1 - a0) > 180 ? 1 : 0;
  return `M ${x0.toFixed(1)} ${y0.toFixed(1)} A ${r} ${r} 0 ${large} 1 ${x1.toFixed(1)} ${y1.toFixed(1)}`;
}

export function RegimeGauge({ score, bucket, history }: { score: number | null; bucket: string; history?: number[] }) {
  const cx = 100, cy = 100;
  const v = score ?? 50;
  const angle = START + (v / 100) * SWEEP;
  const color = v >= 65 ? "var(--green)" : v <= 35 ? "var(--red)" : "var(--orange)";
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
      <svg width={200} height={160} viewBox="0 0 200 150">
        <path d={arc(cx, cy, RADIUS, START, START + SWEEP)} fill="none" stroke="var(--fill)" strokeWidth="12" strokeLinecap="round" />
        <path d={arc(cx, cy, RADIUS, START, angle)} fill="none" stroke={color} strokeWidth="12" strokeLinecap="round"
          style={{ transition: "all 500ms var(--ease-spring)" }} />
        <text x={cx} y={cy - 4} textAnchor="middle" className="tnum" fontSize="40" fontWeight="700" fill="var(--label)">
          {score == null ? "—" : Math.round(v)}
        </text>
        <text x={cx} y={cy + 20} textAnchor="middle" fontSize="13" fill="var(--secondaryLabel)">/ 100</text>
      </svg>
      <div className="headline" style={{ color, marginTop: -8 }}>{bucket}</div>
      {history && history.length > 1 && (
        <div style={{ marginTop: 10 }}><Sparkline data={history} width={180} height={30} baseline={50} /></div>
      )}
    </div>
  );
}
