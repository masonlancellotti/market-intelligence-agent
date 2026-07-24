// Core UI primitives: Card, StatTile, Delta, Badge, Segmented, Sparkline, TrendBadge.
import { useEffect, useRef, useState } from "react";
import { dirClass, fmtPct, fmtPrice } from "../lib/format";

export function Card({ title, action, hero, children, className = "" }: any) {
  return (
    <section className={`card ${hero ? "card-hero" : ""} ${className}`}>
      {(title || action) && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
          {title && <h2 className="headline">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function Delta({ pct, dp = 2 }: { pct: number | null | undefined; dp?: number }) {
  const d = dirClass(pct);
  return <span className={`delta ${d}`}>{fmtPct(pct, dp)}</span>;
}

export function Badge({ kind, children }: { kind: string; children: any }) {
  const cls = kind === "P0" ? "badge-p0" : kind === "P1" ? "badge-p1" : kind === "P2" ? "badge-p2"
    : kind === "green" ? "badge-green" : "badge-blue";
  return <span className={`badge ${cls}`}>{children}</span>;
}

export function StatTile({ label, value, delta, sub, ev }: any) {
  return (
    <div className="card" style={{ minWidth: 0 }}>
      <div className="footnote sec-label" style={{ marginBottom: 6 }}>{label}{ev && <EvidenceRef id={ev} />}</div>
      <div className="tnum title2" style={{ letterSpacing: "-0.01em" }}>{value}</div>
      {delta != null && <div style={{ marginTop: 6 }}><Delta pct={delta} /></div>}
      {sub && <div className="caption sec-label" style={{ marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

export function Segmented({ options, value, onChange }: { options: string[]; value: string; onChange: (v: string) => void }) {
  const wrap = useRef<HTMLDivElement>(null);
  const [thumb, setThumb] = useState({ left: 2, width: 0 });
  useEffect(() => {
    const el = wrap.current?.querySelector<HTMLButtonElement>(`button[data-v="${value}"]`);
    if (el) setThumb({ left: el.offsetLeft, width: el.offsetWidth });
  }, [value, options.join()]);
  return (
    <div className="segmented" ref={wrap}>
      <span className="thumb" style={{ transform: `translateX(${thumb.left - 2}px)`, width: thumb.width }} />
      {options.map((o) => (
        <button key={o} data-v={o} onClick={() => onChange(o)}
          style={{ color: o === value ? "var(--label)" : "var(--secondaryLabel)" }}>{o}</button>
      ))}
    </div>
  );
}

// Live-updating number with green/red flash on change (§13.1).
export function LiveNum({ value, prefix = "", dp = 2 }: { value: number | null; prefix?: string; dp?: number }) {
  const prev = useRef(value);
  const [cls, setCls] = useState("");
  useEffect(() => {
    if (prev.current != null && value != null && value !== prev.current) {
      setCls(value > prev.current ? "flash-up" : "flash-down");
      const t = setTimeout(() => setCls(""), 620);
      prev.current = value;
      return () => clearTimeout(t);
    }
    prev.current = value;
  }, [value]);
  return <span className={`tnum ${cls}`}>{prefix}{fmtPrice(value, dp)}</span>;
}

// 1.5px sparkline with gradient underfill, green/red vs baseline (§13.1).
export function Sparkline({ data, width = 120, height = 34, baseline }: { data: number[]; width?: number; height?: number; baseline?: number }) {
  if (!data || data.length < 2) return <svg width={width} height={height} />;
  const min = Math.min(...data), max = Math.max(...data);
  const range = max - min || 1;
  const base = baseline ?? data[0];
  const up = data[data.length - 1] >= base;
  const color = up ? "var(--green)" : "var(--red)";
  const x = (i: number) => (i / (data.length - 1)) * width;
  const y = (v: number) => height - ((v - min) / range) * (height - 4) - 2;
  const line = data.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const fill = `${line} L${width},${height} L0,${height} Z`;
  const gid = `sg${Math.round(base * 1000) % 100000}`;
  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.22" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={fill} fill={`url(#${gid})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

export function TrendBadge({ rsi, changePct }: { rsi?: number | null; changePct?: number | null }) {
  const trend = changePct == null ? "—" : changePct > 0 ? "▲" : changePct < 0 ? "▼" : "▬";
  const cls = changePct == null ? "" : changePct > 0 ? "up" : "down";
  return <span className={`tnum ${cls}`} title={`RSI ${rsi?.toFixed(0) ?? "—"}`}>{trend}</span>;
}

export function EvidenceRef({ id }: { id: string }) {
  return <sup className="caption accent" style={{ marginLeft: 3, fontVariantNumeric: "tabular-nums" }} title={id}>◦</sup>;
}

export function Loading({ rows = 3 }: { rows?: number }) {
  return <div style={{ display: "grid", gap: 8 }}>{Array.from({ length: rows }).map((_, i) => (
    <div key={i} className="skeleton" style={{ height: 44 }} />))}</div>;
}
