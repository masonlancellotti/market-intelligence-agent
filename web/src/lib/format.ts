// Formatting helpers — tabular, terminal-grade.

export const fmtPrice = (v: number | null | undefined, dp = 2): string =>
  v == null ? "—" : v.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });

export const fmtPct = (v: number | null | undefined, dp = 2): string =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(dp)}%`;

export const fmtNum = (v: number | null | undefined, dp = 1): string =>
  v == null ? "—" : v.toFixed(dp);

export const fmtCompact = (v: number | null | undefined): string => {
  if (v == null) return "—";
  const a = Math.abs(v);
  if (a >= 1e12) return `${(v / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return `${v}`;
};

export const dirClass = (v: number | null | undefined): string =>
  v == null ? "" : v > 0 ? "up" : v < 0 ? "down" : "";

export const fmtTime = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(+d) ? iso : d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
};

export const fmtDate = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(+d) ? iso : d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
};

export const ago = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  const s = (Date.now() - +new Date(iso)) / 1000;
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
};
